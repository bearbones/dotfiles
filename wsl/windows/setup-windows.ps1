# Windows-side setup for the WSL build box. Run from Windows PowerShell (no
# admin needed):  powershell -ExecutionPolicy Bypass -File setup-windows.ps1
#
#  - copies wsl\wslconfig to %USERPROFILE%\.wslconfig
#  - registers a logon task that keeps the distro running, so Tailscale SSH
#    and tmux sessions inside WSL stay reachable from the laptop even when no
#    terminal is open (WSL otherwise stops an idle distro after a few seconds)
#  - -NoSleepOnAC: never sleep while plugged in (a desktop always is)

param(
    [string]$Distro = "Ubuntu-24.04",
    [switch]$NoSleepOnAC
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Copy-Item (Join-Path $repo "wsl\wslconfig") (Join-Path $env:USERPROFILE ".wslconfig") -Force
Write-Host "Wrote $env:USERPROFILE\.wslconfig"

$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro --exec sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
# Interactive logon type with a hidden task keeps wsl.exe's console off-screen.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName "WSL keepalive ($Distro)" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered logon task 'WSL keepalive ($Distro)'"

if ($NoSleepOnAC) {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "Disabled sleep/hibernate on AC power"
}
