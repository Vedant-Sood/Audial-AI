$taskProject = $PSScriptRoot
$taskShell = New-Object -ComObject WScript.Shell
$taskDesktop = [Environment]::GetFolderPath('Desktop')
$taskPrograms = [Environment]::GetFolderPath('Programs')
foreach ($taskDestination in @($taskDesktop, $taskPrograms)) {
    $taskShortcut = $taskShell.CreateShortcut((Join-Path $taskDestination 'Accessibility AI.lnk'))
    $taskShortcut.TargetPath = Join-Path $taskProject '.venv\Scripts\pythonw.exe'
    $taskShortcut.Arguments = '-m app.main'
    $taskShortcut.WorkingDirectory = $taskProject
    $taskShortcut.IconLocation = Join-Path $taskProject 'assets\icon.ico'
    $taskShortcut.Save()
}
Write-Host 'Desktop and Start menu shortcuts created.'
