#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$GITHUB_REPO = "ondravaculik03/Agent_windows"
$INSTALL_DIR = "$env:ProgramFiles\MonitoringAgent"
$CONFIG_DIR = "$env:ProgramData\MojeAplikace"

# Stáhni z GitHub
$release = Invoke-RestMethod "https://api.github.com/repos/$GITHUB_REPO/releases/latest"
$agentUrl = ($release.assets | Where-Object { $_.name -eq "agent-service.exe" }).browser_download_url
$cliUrl = ($release.assets | Where-Object { $_.name -eq "agent-cli.exe" }).browser_download_url

$temp = "$env:TEMP\monitoring-agent"
New-Item -ItemType Directory -Path $temp -Force | Out-Null
Invoke-WebRequest -Uri $agentUrl -OutFile "$temp\agent-service.exe"
Invoke-WebRequest -Uri $cliUrl -OutFile "$temp\agent-cli.exe"

# Instaluj
New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $CONFIG_DIR -Force | Out-Null
Copy-Item "$temp\agent-service.exe" "$INSTALL_DIR\" -Force
Copy-Item "$temp\agent-cli.exe" "$INSTALL_DIR\" -Force

# Config
if (-not (Test-Path "$CONFIG_DIR\config.json")) {
    '{"server_url":"NOT_CONFIGURED","auth_token":"NOT_CONFIGURED","interval_seconds":60,"log_level":"INFO"}' | Set-Content "$CONFIG_DIR\config.json"
}

# PATH
$path = [Environment]::GetEnvironmentVariable("Path", "Machine")
if ($path -notlike "*$INSTALL_DIR*") {
    [Environment]::SetEnvironmentVariable("Path", "$path;$INSTALL_DIR", "Machine")
}

# Scheduled tasks
schtasks /create /tn "MonitoringAgent" /tr "`"$INSTALL_DIR\agent-service.exe`"" /sc onstart /ru SYSTEM /f | Out-Null
schtasks /create /tn "MonitoringAgentHourly" /tr "`"$INSTALL_DIR\agent-service.exe`"" /sc hourly /ru SYSTEM /f | Out-Null

Remove-Item -Path $temp -Recurse -Force
Write-Host "Hotovo. Nastav: agent-cli set server_url <url>"