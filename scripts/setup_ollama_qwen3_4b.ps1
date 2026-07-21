[CmdletBinding()]
param(
    [switch]$OpenOfficialDownload,
    [int]$TimeoutSeconds = 1800
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Modelfile = Join-Path $ProjectRoot 'models\ollama\Modelfile.stock-agent-qwen3-4b'
$BaseModel = 'qwen3:4b'
$ProjectModel = 'stock-agent-qwen3-4b'
$OllamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $OllamaCommand) {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $candidate) {
        $OllamaCommand = @{ Source = $candidate }
    }
}

function Invoke-OllamaCommand {
    param([string[]]$Arguments)
    # ProcessStartInfo avoids a shell; all arguments are project-controlled
    # constants and are quoted before being handed to the native process.
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $OllamaCommand.Source
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Arguments = (($Arguments | ForEach-Object {
        $value = [string]$_
        if ($value -match '[\s"]') { '"' + $value.Replace('"', '\"') + '"' } else { $value }
    }) -join ' ')
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw "Could not start Ollama command: $($Arguments -join ' ')" }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit([int]($TimeoutSeconds * 1000))) {
        try { $process.Kill() } catch {}
        throw "ollama $($Arguments -join ' ') timed out after $TimeoutSeconds seconds"
    }
    $output = @($stdout.GetAwaiter().GetResult(), $stderr.GetAwaiter().GetResult()) | Where-Object { $_ }
    $exit = $process.ExitCode
    $output | ForEach-Object { Write-Host $_ }
    if ($exit -ne 0) { throw "ollama $($Arguments -join ' ') failed with exit code $exit" }
}

if (-not $OllamaCommand) {
    Write-Host 'Ollama is not installed. Download the official Windows installer from:' -ForegroundColor Yellow
    Write-Host 'https://ollama.com/download/windows'
    if ($OpenOfficialDownload) {
        Start-Process 'https://ollama.com/download/windows'
    }
    throw 'Install Ollama from the official site, reopen PowerShell, then run this script again.'
}

Invoke-OllamaCommand @('--version')
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10 | Out-Null
} catch {
    throw "Ollama service is unavailable at http://127.0.0.1:11434. Start Ollama and retry. $($_.Exception.Message)"
}

if (-not (Test-Path -LiteralPath $Modelfile)) { throw "Project Modelfile not found: $Modelfile" }

Write-Host "Pulling official base model $BaseModel ..." -ForegroundColor Cyan
Invoke-OllamaCommand @('pull', $BaseModel)
Write-Host "Creating project model $ProjectModel ..." -ForegroundColor Cyan
Invoke-OllamaCommand @('create', $ProjectModel, '-f', $Modelfile)
Write-Host 'Installed models:' -ForegroundColor Cyan
Invoke-OllamaCommand @('list')

$models = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/v1/models' -TimeoutSec 20
$modelIds = @($models.data | ForEach-Object id)
if (-not (($modelIds -contains $ProjectModel) -or ($modelIds -contains "$ProjectModel`:latest"))) { throw "Project model $ProjectModel is absent from /v1/models." }
$payload = @{ model = $ProjectModel; messages = @(@{ role = 'system'; content = '/no_think' }, @{ role = 'user'; content = '只回复 OK' }); temperature = 0; max_tokens = 200 } | ConvertTo-Json -Depth 6
$reply = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/v1/chat/completions' -Method Post -ContentType 'application/json' -Body $payload -TimeoutSec 120
if (-not [string]$reply.choices[0].message.content) { throw 'Ollama chat/completions returned empty content.' }
Write-Host "Ollama setup succeeded: $ProjectModel" -ForegroundColor Green
