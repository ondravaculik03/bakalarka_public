agent-windows:

install: 

powershell -ExecutionPolicy Bypass -Command "Invoke-Expression (Invoke-RestMethod 'https://raw.githubusercontent.com/ondravaculik03/bakalarka_public/main/agent_windows/scripts/install.ps1')"


uninstall: 

powershell -ExecutionPolicy Bypass -Command "Invoke-Expression (Invoke-RestMethod 'https://raw.githubusercontent.com/ondravaculik03/bakalarka_public/main/agent_windows/scripts/uninstall.ps1')"
