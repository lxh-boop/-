param(
    [string]$TaskName = "StockDailyApp-AutoUpdate-Fallback",
    [string]$Time = "20:00",
    [ValidateSet("Limited", "Highest")]
    [string]$RunLevel = "Limited"
)

$ErrorActionPreference = "Stop"

$Root = "D:\stock_daily_app"
$ScriptPath = Join-Path $Root "scripts\run_scheduled_daily_update.bat"

if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
    throw "Scheduled update script not found: $ScriptPath"
}

$Action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 991800) `
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
    Note = "FastAPI already hosts the primary scheduler; this Windows task is only an optional fallback."
}
