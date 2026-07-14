param(
    [string]$TaskName = "StockDailyApp-AutoUpdate",
    [string]$Time = "17:30",
    [ValidateSet("Limited", "Highest")]
    [string]$RunLevel = "Limited"
)

$ErrorActionPreference = "Stop"

$Root = "D:\stock_daily_app"
$ScriptPath = Join-Path $Root "scripts\run_scheduled_daily_update.bat"

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Scheduled update script not found: $ScriptPath"
}

$Action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel $RunLevel
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal

Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

[pscustomobject]@{
    TaskName = $TaskName
    TriggerTime = $Time
    Execute = $ScriptPath
    WorkingDirectory = $Root
    RunLevel = $RunLevel
    Created = $true
}
