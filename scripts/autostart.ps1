param([Parameter(Mandatory)][ValidateSet('enable', 'disable')][string]$Action)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $projectRoot 'run.py'
$silentPython = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$startupShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'TASQUE.lnk'

function Get-TasqueProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($runScript) }
}

if ($Action -eq 'enable') {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($startupShortcut)
    $shortcut.TargetPath = $silentPython
    $shortcut.Arguments = "`"$runScript`""
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'TASQUE Discord bot (runs silently)'
    $shortcut.Save()
    'TASQUE will now start silently every time you log in.'

    if (Get-TasqueProcesses) {
        'It is already running.'
    } else {
        Start-Process -FilePath $silentPython -ArgumentList "`"$runScript`"" -WorkingDirectory $projectRoot
        'Started it in the background.'
    }
    "Logs: $(Join-Path $projectRoot 'data\tasque.log')"
} else {
    if (Test-Path $startupShortcut) {
        Remove-Item $startupShortcut
        'Removed TASQUE from startup.'
    } else {
        'TASQUE was not set to start at login.'
    }

    $tasqueProcesses = @(Get-TasqueProcesses)
    if ($tasqueProcesses.Count -gt 0) {
        $tasqueProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        'Stopped TASQUE.'
    } else {
        'TASQUE was not running.'
    }
}
