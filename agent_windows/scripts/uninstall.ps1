#Requires -RunAsAdministrator
$INSTALL_DIR = "$env:ProgramFiles\Mastiff"
$CONFIG_DIR = "$env:ProgramData\Mastiff"

# Odstranění souborů
if (Test-Path $INSTALL_DIR) {
    Remove-Item -Path $INSTALL_DIR -Recurse -Force
    Write-Host "Install folder removed."
}

# Odstranění configu (volitelné)
if (Test-Path $CONFIG_DIR) {
    Remove-Item -Path $CONFIG_DIR -Recurse -Force
    Write-Host "Config folder removed."
}

# Odstranění z PATH
$path = [Environment]::GetEnvironmentVariable("Path", "Machine")
$newPath = ($path -split ";" | Where-Object { $_ -ne $INSTALL_DIR }) -join ";"
[Environment]::SetEnvironmentVariable("Path", $newPath, "Machine")
Write-Host "PATH updated."

# Odstranění Scheduled Tasks
schtasks /delete /tn "MonitoringAgent" /f
schtasks /delete /tn "MonitoringAgentHourly" /f
Write-Host "Scheduled Tasks removed."

Write-Host "Uninstall done."
