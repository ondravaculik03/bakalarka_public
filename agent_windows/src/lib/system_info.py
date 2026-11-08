import json
import logging
import platform
import re
import socket
import subprocess
import time

from src import __version__ as AGENT_VERSION

logger = logging.getLogger(__name__)

# Jeden CIM dotaz na pole identity. Agent běží jako SYSTEM (scheduled task),
# takže getpass.getuser() by vrátil "SYSTEM" - Win32_ComputerSystem.UserName
# vrací uživatele přihlášeného ke konzoli, ať se ptá kdokoli.
_CIM_SCRIPT = (
    "$cs = Get-CimInstance -ClassName Win32_ComputerSystem; "
    "$os = Get-CimInstance -ClassName Win32_OperatingSystem; "
    "$bios = Get-CimInstance -ClassName Win32_BIOS; "
    # SilentlyContinue, aby chyba při čtení registru nechala prázdné jen
    # os_edition a neshodila celý skript.
    r"$edition = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -Name EditionID -ErrorAction SilentlyContinue).EditionID; "
    "[PSCustomObject]@{ "
    "current_user = $cs.UserName; "
    "os_version = $os.Version; "
    "os_build = $os.BuildNumber; "
    "serial_number = $bios.SerialNumber; "
    "os_name = ([string]$os.Caption).Trim(); "
    "os_edition = $edition; "
    # Použije se pro uptime_seconds v general health, ať není druhý dotaz na
    # Win32_OperatingSystem. Není to pole identity, proto chybí v _CIM_FIELDS.
    "os_last_boot_time = $os.LastBootUpTime; "
    # Surová čísla, _device_type z nich udělá device_type. Taky chybí
    # v _CIM_FIELDS.
    "pc_system_type = $cs.PCSystemType; "
    "product_type = $os.ProductType "
    "} | ConvertTo-Json -Compress"
)

_CIM_FIELDS = (
    "current_user",
    "os_version",
    "os_build",
    "serial_number",
    "os_name",
    "os_edition",
)

# Jeden dotaz na Defender a firewall. Každý cmdlet má vlastní try/catch, aby
# chyba jedné skupiny (třeba chybějící Defender) neshodila ostatní (třeba
# firewall). Skupina, která selže, zapíše svůj název do _errors místo
# neúplných dat.
_PROTECTION_STATUS_SCRIPT = r"""
$result = @{}
$errors = @()

try {
    $mp = Get-MpComputerStatus
    $result.av_enabled = [bool]$mp.AntivirusEnabled
    $result.av_realtime_protection_enabled = [bool]$mp.RealTimeProtectionEnabled
    $result.av_running_mode = [string]$mp.AMRunningMode
    $result.av_signature_age_days = [int]$mp.AntivirusSignatureAge
    $result.tamper_protection_enabled = [bool]$mp.IsTamperProtected
    $result.av_reboot_required = [bool]$mp.RebootRequired
    $result.av_quick_scan_overdue = [bool]$mp.QuickScanOverdue
    $result.av_full_scan_overdue = [bool]$mp.FullScanOverdue
} catch {
    $errors += "defender_status"
}

try {
    $threats = @(Get-MpThreat | Where-Object { $_.IsActive })
    $result.av_active_detections_count = $threats.Count
    $result.av_active_detection_names = @($threats | ForEach-Object { $_.ThreatName })
} catch {
    $errors += "defender_detections"
}

try {
    $isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isElevated) {
        # Get-MpPreference bez admina nespadne, jen v ExclusionPath vrátí
        # hlášku "must be an administrator" místo cest. Kontrola práv je
        # spolehlivější než hledat tu hlášku (text i jazyk se můžou změnit).
        throw "not running elevated, cannot read AV exclusions"
    }
    $rawExclusionPaths = (Get-MpPreference).ExclusionPath
    # @($null) je pole s jedním prvkem null, ne prázdné pole. U vlastnosti,
    # která může být $null (výstup pipeline tenhle problém nemá), je potřeba
    # nejdřív kontrola na null.
    if ($null -eq $rawExclusionPaths) {
        $paths = @()
    } else {
        $paths = @($rawExclusionPaths)
    }
    $result.av_exclusions_count = $paths.Count
    $result.av_exclusion_paths = $paths
} catch {
    $errors += "defender_exclusions"
}

try {
    $profiles = Get-NetFirewallProfile -Profile Domain, Private, Public
    foreach ($p in $profiles) {
        $result["firewall_" + $p.Name.ToLower() + "_enabled"] = [bool]$p.Enabled
    }
} catch {
    $errors += "firewall"
}

try {
    # productState Microsoft nedokumentuje - bit 0x1000 = zapnuto a bit 0x10 =
    # zastaralé signatury je běžně používané čtení.
    $result.antivirus_products = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction Stop | ForEach-Object {
        [PSCustomObject]@{
            name = [string]$_.displayName
            enabled = (([int]$_.productState -band 0x1000) -ne 0)
            up_to_date = (([int]$_.productState -band 0x10) -eq 0)
        }
    })
} catch {
    $errors += "security_center"
}

$result._errors = $errors
[PSCustomObject]$result | ConvertTo-Json -Compress -Depth 5
"""

# Ke každé try/catch skupině výše její pole, aby se selhání skupiny dalo
# převést na správné položky v collection_errors.
_PROTECTION_STATUS_GROUPS = {
    "defender_status": (
        "av_enabled",
        "av_realtime_protection_enabled",
        "av_running_mode",
        "av_signature_age_days",
        "tamper_protection_enabled",
        "av_reboot_required",
        "av_quick_scan_overdue",
        "av_full_scan_overdue",
    ),
    "defender_detections": (
        "av_active_detections_count",
        "av_active_detection_names",
    ),
    "defender_exclusions": (
        "av_exclusions_count",
        "av_exclusion_paths",
    ),
    "firewall": (
        "firewall_domain_enabled",
        "firewall_private_enabled",
        "firewall_public_enabled",
    ),
    "security_center": ("antivirus_products",),
}

# Jeden dotaz na patch/account/exposure hygiene, každá skupina má vlastní
# try/catch jako u protection status. outdated_apps (winget) se záměrně
# nesbírá - viz komentář v _collect_hygiene.
_HYGIENE_SCRIPT = r"""
$result = @{}
$errors = @()

try {
    $hotfix = Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 1
    if ($null -eq $hotfix -or $null -eq $hotfix.InstalledOn) {
        throw "no hotfix install date available"
    }
    $result.days_since_last_update = [int]((Get-Date) - $hotfix.InstalledOn).Days
} catch {
    $errors += "patch_days_since_update"
}

try {
    $cbsPending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
    $wuPending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    # Není to av_reboot_required (protection_status): tady jde o nainstalovaný
    # update, který čeká na restart, ne o Defender, který dokončuje čištění.
    $result.windows_update_reboot_pending = [bool]($cbsPending -or $wuPending)
} catch {
    $errors += "patch_reboot_pending"
}

try {
    # ADSI, ne Get-LocalGroupMember: ten spadne ("Failed to compare two
    # elements in the array"), když je ve skupině Administrators účet
    # propojený s Microsoft účtem. WinNT://./Administrators,group vrátí stejné
    # členy bez porovnání .NET typů, které na smíšených členech padá.
    $adminsGroup = [ADSI]"WinNT://./Administrators,group"
    # .Split, ne -replace/-split: ty berou argument jako regex a samotné "\"
    # je neplatný vzor.
    $admins = @($adminsGroup.Invoke("Members") | ForEach-Object {
        $name = $_.GetType().InvokeMember("Name", "GetProperty", $null, $_, $null)
        $name.Split('\')[-1]
    })
    $result.local_admin_count = $admins.Count
    $result.local_admin_usernames = $admins
} catch {
    $errors += "account_local_admins"
}

try {
    # Hledá se podle známého konce SID, ne podle jména - jména vestavěných
    # účtů Administrator/Guest jsou lokalizovaná (na české verzi
    # "Administrátor"), podle jména by se na neanglických Windows nenašly.
    $adminAccount = Get-LocalUser | Where-Object { $_.SID.Value -like '*-500' } | Select-Object -First 1
    if ($null -eq $adminAccount) { throw "builtin Administrator account (SID -500) not found" }
    $result.builtin_administrator_enabled = [bool]$adminAccount.Enabled
} catch {
    $errors += "account_builtin_administrator"
}

try {
    $guestAccount = Get-LocalUser | Where-Object { $_.SID.Value -like '*-501' } | Select-Object -First 1
    if ($null -eq $guestAccount) { throw "builtin Guest account (SID -501) not found" }
    $result.guest_account_enabled = [bool]$guestAccount.Enabled
} catch {
    $errors += "account_guest_account"
}

try {
    $rdpValue = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -ErrorAction Stop).fDenyTSConnections
    # fDenyTSConnections je obráceně, než říká název:
    # 0 = RDP zapnuté, 1 = RDP vypnuté.
    $result.rdp_enabled = ($rdpValue -eq 0)
} catch {
    $errors += "exposure_rdp"
}

try {
    $autorunValue = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer' -Name NoDriveTypeAutoRun -ErrorAction SilentlyContinue).NoDriveTypeAutoRun
    if ($null -eq $autorunValue) {
        # Policy není nastavená - tento klíč autorun pro výměnná média
        # neomezuje, takže je zapnutý.
        $result.autorun_removable_media_enabled = $true
    } else {
        # Bit 0x4 v masce NoDriveTypeAutoRun odpovídá DRIVE_REMOVABLE.
        $result.autorun_removable_media_enabled = (([int]$autorunValue -band 0x4) -eq 0)
    }
} catch {
    $errors += "exposure_autorun"
}

try {
    # Na Windows Home vůbec není (chybí modul BitLocker, příkaz neexistuje
    # a chytí se jako každá jiná chyba) a může selhat i tam, kde je (bez TPM,
    # nespravovaný svazek apod.).
    $bitlockerStatus = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop
    $result.bitlocker_protection_status = [string]$bitlockerStatus.ProtectionStatus
} catch {
    $errors += "exposure_bitlocker"
}

try {
    $uacValue = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -Name EnableLUA -ErrorAction Stop).EnableLUA
    $result.uac_enabled = ([int]$uacValue -ne 0)
} catch {
    $errors += "exposure_uac"
}

try {
    $smb1 = Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -ErrorAction Stop
    $result.smbv1_enabled = ($smb1.State -eq "Enabled")
} catch {
    $errors += "exposure_smbv1"
}

$result._errors = $errors
[PSCustomObject]$result | ConvertTo-Json -Compress -Depth 5
"""

_HYGIENE_GROUPS = {
    "patch_days_since_update": ("days_since_last_update",),
    "patch_reboot_pending": ("windows_update_reboot_pending",),
    "account_local_admins": ("local_admin_count", "local_admin_usernames"),
    "account_builtin_administrator": ("builtin_administrator_enabled",),
    "account_guest_account": ("guest_account_enabled",),
    "exposure_rdp": ("rdp_enabled",),
    "exposure_autorun": ("autorun_removable_media_enabled",),
    "exposure_bitlocker": ("bitlocker_protection_status",),
    "exposure_uac": ("uac_enabled",),
    "exposure_smbv1": ("smbv1_enabled",),
}

# Do které sekce výstupu patří každé pole hygiene.
_HYGIENE_FIELD_SECTIONS = {
    "days_since_last_update": "patch_hygiene",
    "windows_update_reboot_pending": "patch_hygiene",
    "local_admin_count": "account_hygiene",
    "local_admin_usernames": "account_hygiene",
    "builtin_administrator_enabled": "account_hygiene",
    "guest_account_enabled": "account_hygiene",
    "rdp_enabled": "exposure_hardening",
    "autorun_removable_media_enabled": "exposure_hardening",
    "bitlocker_protection_status": "exposure_hardening",
    "uac_enabled": "exposure_hardening",
    "smbv1_enabled": "exposure_hardening",
}

# General health - jen informace navíc, ne riziko, do state/points se
# nezapočítává. uptime_seconds se tady nezjišťuje: počítá se v Pythonu
# z os_last_boot_time, který už načetl _CIM_SCRIPT pro identitu, ať není
# druhý dotaz na Win32_OperatingSystem.
_GENERAL_HEALTH_SCRIPT = r"""
$result = @{}
$errors = @()

try {
    $metric = Get-CimInstance -ClassName Win32_ReliabilityStabilityMetrics -ErrorAction Stop |
        Sort-Object TimeGenerated -Descending | Select-Object -First 1
    if ($null -eq $metric) {
        # Na některých strojích data prostě nejsou (čerstvá instalace, funkce
        # ještě nic nenasbírala) - nic k hlášení. Žádná vymyšlená 0, vypadala
        # by jako skutečné špatné skóre.
        throw "no reliability stability metrics available"
    }
    $result.stability_index = $metric.SystemStabilityIndex
} catch {
    $errors += "general_health_stability"
}

try {
    $bootDrive = $env:SystemDrive
    $disk = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='$bootDrive'" -ErrorAction Stop
    if ($null -eq $disk) {
        throw "no Win32_LogicalDisk entry for $bootDrive"
    }
    $result.disk_free_bytes = $disk.FreeSpace
    $result.disk_total_bytes = $disk.Size
} catch {
    $errors += "general_health_disk"
}

$result._errors = $errors
[PSCustomObject]$result | ConvertTo-Json -Compress -Depth 5
"""

_GENERAL_HEALTH_GROUPS = {
    "general_health_stability": ("stability_index",),
    "general_health_disk": ("disk_free_bytes", "disk_total_bytes"),
}

# Seznam nainstalovaných aplikací z registru. Jen HKLM: agent běží jako SYSTEM
# a aplikace v HKCU by viděl jen u přihlášených uživatelů, takže by se
# objevovaly a mizely podle přihlášení. Nikdy Win32_Product - dotaz na něj
# může spustit opravy MSI balíčků. Obal @{apps = ...}, aby 0 nebo 1 aplikace
# byla v JSON pořád seznam.
_INSTALLED_SOFTWARE_SCRIPT = r"""
$keys = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$apps = @()
foreach ($key in $keys) {
    # SilentlyContinue: klíč WOW6432Node na 32bit Windows neexistuje.
    foreach ($entry in @(Get-ItemProperty -Path $key -ErrorAction SilentlyContinue)) {
        $name = ([string]$entry.DisplayName).Trim()
        if ($name -eq "") { continue }
        if ($entry.SystemComponent -eq 1) { continue }
        if ($entry.ParentKeyName) { continue }
        if (@("Update", "Hotfix", "Security Update") -contains $entry.ReleaseType) { continue }
        $version = ([string]$entry.DisplayVersion).Trim()
        $publisher = ([string]$entry.Publisher).Trim()
        if ($version -eq "") { $version = $null }
        if ($publisher -eq "") { $publisher = $null }
        $apps += [PSCustomObject]@{ name = $name; version = $version; publisher = $publisher }
    }
}
[PSCustomObject]@{ apps = $apps } | ConvertTo-Json -Compress -Depth 5
"""

_DOTNET_JSON_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


def _parse_dotnet_json_date_ms(value):
    """Returns the milliseconds from a `/Date(<ms>)/` value, or None."""
    # ConvertTo-Json posílá DateTime jako /Date(ms)/, vždy UTC milisekundy od
    # epochy bez ohledu na jazyk a časové pásmo stroje.
    if not isinstance(value, str):
        return None
    match = _DOTNET_JSON_DATE_RE.fullmatch(value)
    if not match:
        return None
    return int(match.group(1))


def _run_powershell(script):
    """Runs a PowerShell script and returns its JSON output."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Bez UTF8 píše PowerShell výstup v kódové stránce konzole a znaky
    # s diakritikou (třeba "Správce") by se rozbily.
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"powershell exited with {result.returncode}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def _get_ip_addresses():
    """Returns the sorted IP addresses of this machine."""
    hostname = socket.gethostname()
    addr_infos = socket.getaddrinfo(hostname, None)
    return sorted({addr[4][0] for addr in addr_infos})


def _device_type(product_type, pc_system_type):
    """Turns ProductType and PCSystemType into one device type word, or None."""
    # ProductType má přednost, servery často hlásí PCSystemType 1 (Desktop).
    # Virtuální stroje se nepoznají, hlásí Desktop.
    if product_type in (2, 3):
        return "Server"
    if pc_system_type == 2:
        return "Laptop"
    if pc_system_type == 8:
        return "Tablet"
    if pc_system_type in (1, 3):
        return "Desktop"
    if pc_system_type is None:
        return None
    return "Other"


def _collect_identity(collection_errors):
    """Collects the identity fields, returns (identity, os_last_boot_time_raw)."""
    # os_last_boot_time_raw není pole identity, dostane ho
    # _collect_general_health, aby uptime_seconds nepotřeboval druhý dotaz na
    # Win32_OperatingSystem.
    identity = {}
    os_last_boot_time_raw = None

    try:
        identity["hostname"] = socket.gethostname()
    except Exception:
        logger.exception("Couldn't read hostname")
        collection_errors.append("hostname")

    try:
        identity["os"] = platform.system()
    except Exception:
        logger.exception("Couldn't read os")
        collection_errors.append("os")

    try:
        identity["architecture"] = platform.machine()
    except Exception:
        logger.exception("Couldn't read architecture")
        collection_errors.append("architecture")

    identity["agent_version"] = AGENT_VERSION

    try:
        identity["ip_addresses"] = _get_ip_addresses()
    except Exception:
        logger.exception("Couldn't read ip_addresses")
        collection_errors.append("ip_addresses")

    try:
        cim_identity = _run_powershell(_CIM_SCRIPT)
        for field in _CIM_FIELDS:
            value = cim_identity.get(field)
            if value in (None, ""):
                collection_errors.append(field)
            else:
                identity[field] = value
        os_last_boot_time_raw = cim_identity.get("os_last_boot_time")
        device_type = _device_type(
            cim_identity.get("product_type"), cim_identity.get("pc_system_type")
        )
        if device_type is None:
            collection_errors.append("device_type")
        else:
            identity["device_type"] = device_type
    except Exception:
        logger.exception("Couldn't read the CIM/WMI info")
        collection_errors.extend(_CIM_FIELDS)
        collection_errors.append("device_type")

    return identity, os_last_boot_time_raw


def _collect_protection_status(collection_errors):
    """Collects the Defender, firewall and antivirus product status."""
    protection_status = {}

    try:
        raw = _run_powershell(_PROTECTION_STATUS_SCRIPT)
    except Exception:
        logger.exception("Couldn't read protection status")
        for fields in _PROTECTION_STATUS_GROUPS.values():
            collection_errors.extend(fields)
        return protection_status

    failed_groups = set(raw.get("_errors") or [])
    for group, fields in _PROTECTION_STATUS_GROUPS.items():
        if group in failed_groups:
            collection_errors.extend(fields)
            continue
        for field in fields:
            if field not in raw or raw[field] is None:
                collection_errors.append(field)
            else:
                protection_status[field] = raw[field]

    return protection_status


def _collect_hygiene(collection_errors):
    """Collects the patch, account and exposure hygiene."""
    # outdated_apps (winget) se záměrně nesbírá: jako jediné potřebuje při
    # sběru síť a winget se pod účtem SYSTEM chová nespolehlivě. Chybí úplně,
    # ani v collection_errors není, protože to není chyba, ale rozhodnutí.
    sections = {
        "patch_hygiene": {},
        "account_hygiene": {},
        "exposure_hardening": {},
    }

    try:
        raw = _run_powershell(_HYGIENE_SCRIPT)
    except Exception:
        logger.exception("Couldn't read patch/account/exposure hygiene")
        for fields in _HYGIENE_GROUPS.values():
            collection_errors.extend(fields)
        return sections

    failed_groups = set(raw.get("_errors") or [])
    for group, fields in _HYGIENE_GROUPS.items():
        if group in failed_groups:
            collection_errors.extend(fields)
            continue
        for field in fields:
            if field not in raw or raw[field] is None:
                collection_errors.append(field)
            else:
                sections[_HYGIENE_FIELD_SECTIONS[field]][field] = raw[field]

    return sections


def _collect_general_health(os_last_boot_time_raw, collection_errors):
    """Collects the general health info (uptime, stability, disk)."""
    # Jen informace navíc, ne riziko - do state/points se nikdy nezapočítává.
    general_health = {}

    boot_time_ms = _parse_dotnet_json_date_ms(os_last_boot_time_raw)
    if boot_time_ms is None:
        collection_errors.append("uptime_seconds")
    else:
        general_health["uptime_seconds"] = max(
            0, int(time.time() - boot_time_ms / 1000)
        )

    try:
        raw = _run_powershell(_GENERAL_HEALTH_SCRIPT)
    except Exception:
        logger.exception("Couldn't read general health")
        for fields in _GENERAL_HEALTH_GROUPS.values():
            collection_errors.extend(fields)
        return general_health

    failed_groups = set(raw.get("_errors") or [])
    for group, fields in _GENERAL_HEALTH_GROUPS.items():
        if group in failed_groups:
            collection_errors.extend(fields)
            continue
        for field in fields:
            if field not in raw or raw[field] is None:
                collection_errors.append(field)
            else:
                general_health[field] = raw[field]

    return general_health


def _collect_installed_software(collection_errors):
    """Returns the installed apps without duplicates, or None if the read failed."""
    try:
        raw = _run_powershell(_INSTALLED_SOFTWARE_SCRIPT)
    except Exception:
        logger.exception("Couldn't read installed software")
        collection_errors.append("installed_software")
        return None

    # Stejná aplikace může být v obou klíčích, nechá se první výskyt.
    apps = []
    seen = set()
    for app in raw.get("apps") or []:
        key = (app.get("name"), app.get("version"))
        if key in seen:
            continue
        seen.add(key)
        apps.append(
            {
                "name": app.get("name"),
                "version": app.get("version"),
                "publisher": app.get("publisher"),
            }
        )

    return apps


def get_system_info():
    """Collects all system info sections for the backend."""
    # Best-effort: pole, které se nepodaří zjistit, ve své sekci chybí a jeho
    # název je v collection_errors, místo aby selhal celý check-in.
    collection_errors = []

    identity, os_last_boot_time_raw = _collect_identity(collection_errors)
    protection_status = _collect_protection_status(collection_errors)
    hygiene_sections = _collect_hygiene(collection_errors)
    general_health = _collect_general_health(os_last_boot_time_raw, collection_errors)
    installed_software = _collect_installed_software(collection_errors)

    result = {
        "identity": identity,
        "protection_status": protection_status,
        **hygiene_sections,
        "general_health": general_health,
    }
    if installed_software is not None:
        result["installed_software"] = installed_software
    if collection_errors:
        result["collection_errors"] = collection_errors
    return result
