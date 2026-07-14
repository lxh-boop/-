param(
    [string]$TaskName = "StockDailyApp-AutoUpdate"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    [pscustomobject]@{
        TaskName = $TaskName
        Removed = $false
        Message = "Task not found"
    }
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
[pscustomobject]@{
    TaskName = $TaskName
    Removed = $true
}
