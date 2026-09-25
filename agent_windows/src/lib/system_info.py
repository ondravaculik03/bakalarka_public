import json
import logging
import platform
import re
import socket
import subprocess
import time
from datetime import date

from src import __version__ as AGENT_VERSION

logger = logging.getLogger(__name__)

# Single Get-CimInstance query for the fields that must reflect the real,
# interactively logged-in console session rather than the identity of the
# process running the query. The agent runs as SYSTEM via a scheduled task,
# so something like getpass.getuser() would just report "SYSTEM" here -
# Win32_ComputerSystem.UserName correctly reports who's logged into the
# console regardless of who/what is asking.
_CIM_SCRIPT = (
    "$cs = Get-CimInstance -ClassName Win32_ComputerSystem; "
    "$os = Get-CimInstance -ClassName Win32_OperatingSystem; "
    "$bios = Get-CimInstance -ClassName Win32_BIOS; "
    "[PSCustomObject]@{ "
    "current_user = $cs.UserName; "
    "os_version = $os.Version; "
    "os_build = $os.BuildNumber; "
    "serial_number = $bios.SerialNumber; "
    # Reused by general-health's uptime_seconds instead of a second
    # Win32_OperatingSystem query - not itself an identity field, so it's
    # deliberately left out of _CIM_FIELDS below.
    "os_last_boot_time = $os.LastBootUpTime "
    "} | ConvertTo-Json -Compress"
)

_CIM_FIELDS = ("current_user", "os_version", "os_build", "serial_number")

# One consolidated Defender/firewall query, grouped into independent
# try/catch blocks per source cmdlet so one failing group (e.g. Defender
# not installed) doesn't take out unrelated groups (e.g. firewall state).
# Each group reports its own name into `_errors` on failure instead of
# leaving partial/inconsistent data in the group's fields.
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
        # Get-MpPreference doesn't throw when unprivileged - ExclusionPath
        # just comes back as a one-element array holding a "must be an
        # administrator" message instead of real paths. Checking elevation
        # directly is more reliable than pattern-matching that message
        # (wording/locale could change it).
        throw "not running elevated, cannot read AV exclusions"
    }
    $rawExclusionPaths = (Get-MpPreference).ExclusionPath
    # @($null) is a one-element array containing null, not an empty array -
    # wrapping a possibly-$null property (as opposed to pipeline output,
    # which doesn't have this problem) needs an explicit null check first.
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

$result._errors = $errors
[PSCustomObject]$result | ConvertTo-Json -Compress -Depth 5
"""

# Maps each try/catch group above to the payload field names it owns, so a
# group failure can be turned into the right collection_errors entries.
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
}

# One consolidated call for patch/account/exposure hygiene, same
# independent-try/catch-per-group shape as protection status above.
# `outdated_apps` (winget) is deliberately not collected here - see
# `_collect_hygiene`'s docstring.
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
    # Distinct from av_reboot_required (protection_status): this is "an
    # update installed but not yet rebooted into", not Defender finishing
    # malware remediation.
    $result.windows_update_reboot_pending = [bool]($cbsPending -or $wuPending)
} catch {
    $errors += "patch_reboot_pending"
}

try {
    # ADSI, not Get-LocalGroupMember: that cmdlet throws ("Failed to
    # compare two elements in the array") when the Administrators group
    # contains a Microsoft-Account-linked sign-in, which is a common
    # real-world setup, not an edge case. WinNT://./Administrators,group
    # enumerates the same membership without going through the .NET type
    # comparison that breaks on mixed local/MSA members.
    $adminsGroup = [ADSI]"WinNT://./Administrators,group"
    # .Split, not -replace/-split: those treat their argument as a regex,
    # and a bare "\" is an invalid/trailing-escape pattern.
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
    # Match by well-known SID suffix, not by account name - the built-in
    # Administrator/Guest account names are localized (e.g. "Administrator"
    # -> "Administrátor" on Czech Windows), so name matching would
    # silently fail on non-English installs.
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
    # fDenyTSConnections is inverted from what the name suggests:
    # 0 = RDP enabled, 1 = RDP disabled.
    $result.rdp_enabled = ($rdpValue -eq 0)
} catch {
    $errors += "exposure_rdp"
}

try {
    $autorunValue = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer' -Name NoDriveTypeAutoRun -ErrorAction SilentlyContinue).NoDriveTypeAutoRun
    if ($null -eq $autorunValue) {
        # No explicit policy set - autorun for removable media isn't
        # restricted by this key, i.e. enabled.
        $result.autorun_removable_media_enabled = $true
    } else {
        # Bit 0x4 in the NoDriveTypeAutoRun bitmask corresponds to
        # DRIVE_REMOVABLE.
        $result.autorun_removable_media_enabled = (([int]$autorunValue -band 0x4) -eq 0)
    }
} catch {
    $errors += "exposure_autorun"
}

try {
    # Not available at all on Windows Home editions (no BitLocker module -
    # this throws a command-not-found error there, caught same as any
    # other failure), and can legitimately fail even when present (no
    # TPM, unmanaged volume, etc).
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

# Which output section each hygiene field belongs to.
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

# General health (Section 3) - explicitly not a risk signal, doesn't feed
# state/points scoring. `uptime_seconds` isn't queried here at all: it's
# computed in Python from `os_last_boot_time`, already fetched by
# _CIM_SCRIPT for identity, instead of a second Win32_OperatingSystem call.
_GENERAL_HEALTH_SCRIPT = r"""
$result = @{}
$errors = @()

try {
    $metric = Get-CimInstance -ClassName Win32_ReliabilityStabilityMetrics -ErrorAction Stop |
        Sort-Object TimeGenerated -Descending | Select-Object -First 1
    if ($null -eq $metric) {
        # Legitimately no data on some machines (freshly imaged, feature
        # not populated yet) - not a failure, just nothing to report. Don't
        # fabricate a 0 here, that would misleadingly look like a real bad
        # score.
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

_DOTNET_JSON_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


def _parse_dotnet_json_date_ms(value):
    """Parses ConvertTo-Json's `/Date(<ms-since-epoch>)/` wire format for
    DateTime values (always UTC-epoch milliseconds, regardless of the
    machine's locale/timezone)."""
    if not isinstance(value, str):
        return None
    match = _DOTNET_JSON_DATE_RE.fullmatch(value)
    if not match:
        return None
    return int(match.group(1))


# Generalized consumer (Home/Pro) end-of-support dates per major Windows
# release, keyed by build number range. Not exhaustive (doesn't track
# Enterprise/LTSC extended support, or every point release) and needs
# manual updates as new releases ship / EOL dates are announced - accepted
# limitation, not a bug. (min_build, max_build, end_of_support_date).
_WINDOWS_EOL_TABLE = (
    (10240, 19045, date(2025, 10, 14)),  # Windows 10, all editions
    (22000, 22000, date(2023, 10, 10)),  # Windows 11 21H2
    (22621, 22621, date(2024, 10, 8)),  # Windows 11 22H2
    (22631, 22631, date(2025, 11, 11)),  # Windows 11 23H2
    (26100, 26100, date(2026, 10, 13)),  # Windows 11 24H2
)


def _os_support_status(os_build):
    try:
        build_number = int(str(os_build).split(".")[0])
    except (TypeError, ValueError):
        return "unknown"

    for min_build, max_build, end_of_support in _WINDOWS_EOL_TABLE:
        if min_build <= build_number <= max_build:
            return "eol" if date.today() > end_of_support else "supported"

    return "unknown"


def _run_powershell(script):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"powershell exited with {result.returncode}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def _get_ip_addresses():
    hostname = socket.gethostname()
    addr_infos = socket.getaddrinfo(hostname, None)
    return sorted({addr[4][0] for addr in addr_infos})


def _collect_identity(collection_errors):
    """Returns (identity, os_last_boot_time_raw). The second value isn't an
    identity field itself - it's handed to _collect_general_health so
    uptime_seconds can be computed without a second Win32_OperatingSystem
    query."""
    identity = {}
    os_last_boot_time_raw = None

    try:
        identity["hostname"] = socket.gethostname()
    except Exception:
        logger.exception("Nepodařilo se zjistit hostname")
        collection_errors.append("hostname")

    try:
        identity["os"] = platform.system()
    except Exception:
        logger.exception("Nepodařilo se zjistit os")
        collection_errors.append("os")

    try:
        identity["architecture"] = platform.machine()
    except Exception:
        logger.exception("Nepodařilo se zjistit architecture")
        collection_errors.append("architecture")

    identity["agent_version"] = AGENT_VERSION

    try:
        identity["ip_addresses"] = _get_ip_addresses()
    except Exception:
        logger.exception("Nepodařilo se zjistit ip_addresses")
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
    except Exception:
        logger.exception("Nepodařilo se zjistit informace přes CIM/WMI")
        collection_errors.extend(_CIM_FIELDS)

    return identity, os_last_boot_time_raw


def _collect_protection_status(collection_errors):
    protection_status = {}

    try:
        raw = _run_powershell(_PROTECTION_STATUS_SCRIPT)
    except Exception:
        logger.exception("Nepodařilo se zjistit protection status")
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


def _collect_hygiene(identity, collection_errors):
    """Collects patch/account/exposure hygiene (Sections 2b-2d).

    `outdated_apps` (winget-based) is deliberately not collected in this
    pass: unlike everything else here, it needs live network access at
    collection time and winget behaves inconsistently under the SYSTEM
    account this agent runs as. Left as separate future work rather than
    risking the rest of this batch - omitted entirely (not reported via
    collection_errors, since it's a deliberate deferral, not a failure).
    """
    sections = {
        "patch_hygiene": {},
        "account_hygiene": {},
        "exposure_hardening": {},
    }

    os_build = identity.get("os_build")
    if os_build:
        sections["patch_hygiene"]["os_support_status"] = _os_support_status(os_build)
    else:
        collection_errors.append("os_support_status")

    try:
        raw = _run_powershell(_HYGIENE_SCRIPT)
    except Exception:
        logger.exception("Nepodařilo se zjistit patch/account/exposure hygiene")
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
    """Collects Section 3 (General health) - explicitly not a risk signal,
    background info only, never feeds state/points scoring."""
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
        logger.exception("Nepodařilo se zjistit general health")
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


def get_system_info():
    """Collects machine identity, protection-status, patch/account/exposure
    hygiene, and general-health data for the monitoring backend.

    Best-effort: a field that fails to collect is omitted from its section
    and its name is recorded under the shared `collection_errors` list
    instead of failing the whole check-in.
    """
    collection_errors = []

    identity, os_last_boot_time_raw = _collect_identity(collection_errors)
    protection_status = _collect_protection_status(collection_errors)
    hygiene_sections = _collect_hygiene(identity, collection_errors)
    general_health = _collect_general_health(os_last_boot_time_raw, collection_errors)

    result = {
        "identity": identity,
        "protection_status": protection_status,
        **hygiene_sections,
        "general_health": general_health,
    }
    if collection_errors:
        result["collection_errors"] = collection_errors
    return result
