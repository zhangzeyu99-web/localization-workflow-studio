param(
  [string]$HostName = "127.0.0.1",
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173,
  [string]$DataRoot = "",
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontendRoot = Join-Path $repoRoot "frontend"
$runtimeDir = Join-Path $repoRoot ".tmp\runtime"
$backendPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
  $backendPython = (Get-Command python -ErrorAction Stop).Source
}
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$fullPath = if ($userPath) { "$machinePath;$userPath" } else { $machinePath }
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (-not $DataRoot) {
  $DataRoot = $env:LWS_DATA_ROOT
}
if (-not $DataRoot) {
  $DataRoot = "D:\codex\localization-workflow-studio-data"
}

function Get-ListeningProcessId([int]$Port) {
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($connection) { return [int]$connection.OwningProcess }
  return $null
}

function Test-HttpOk([string]$Url) {
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
  } catch {
    return $false
  }
}

function Test-ApiHealth([string]$Url) {
  try {
    $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
    return ($null -ne $response -and $response.ok -eq $true)
  } catch {
    return $false
  }
}

function Wait-HttpOk([string]$Url, [int]$Seconds) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk $Url) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Wait-ApiHealth([string]$Url, [int]$Seconds) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-ApiHealth $Url) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Start-HiddenPowerShell([string]$Command) {
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
  Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-EncodedCommand", $encoded
  ) -WindowStyle Hidden
}

function Start-Backend {
  $backendHealth = "http://127.0.0.1:$BackendPort/api/health"
  if (Test-ApiHealth $backendHealth) {
    Write-Host "Backend already healthy: $backendHealth"
    return
  }

  $owner = Get-ListeningProcessId $BackendPort
  if ($owner) {
    throw "Backend port $BackendPort is occupied by PID $owner, but health check failed. Stop that process or change -BackendPort."
  }

  $backendLog = Join-Path $runtimeDir "backend-$BackendPort.log"
  $command = @"
`$env:Path = "$fullPath"
Set-Location "$repoRoot"
`$env:LWS_DATA_ROOT = "$DataRoot"
& "$backendPython" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $BackendPort *> "$backendLog"
"@
  Start-HiddenPowerShell $command

  if (-not (Wait-ApiHealth $backendHealth 45)) {
    $tail = if (Test-Path $backendLog) { Get-Content $backendLog -Tail 80 | Out-String } else { "" }
    throw "Backend failed to start on $backendHealth.`n$tail"
  }
  Write-Host "Backend started: $backendHealth"
}

function Start-Frontend {
  $frontendUrl = "http://${HostName}:$FrontendPort/"
  $frontendHealthUrl = if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { "http://127.0.0.1:$FrontendPort/" } else { $frontendUrl }
  if (Test-HttpOk $frontendHealthUrl) {
    Write-Host "Frontend already healthy: $frontendUrl"
    return
  }

  $owner = Get-ListeningProcessId $FrontendPort
  if ($owner) {
    throw "Frontend port $FrontendPort is occupied by PID $owner, but health check failed. Stop that process or change -FrontendPort."
  }

  $frontendLog = Join-Path $runtimeDir "frontend-$FrontendPort.log"
  $apiTarget = "http://127.0.0.1:$BackendPort"
$command = @"
`$env:Path = "$fullPath"
Set-Location "$frontendRoot"
`$env:LWS_API_TARGET = "$apiTarget"
npx vite --host $HostName --port $FrontendPort *> "$frontendLog"
"@
  Start-HiddenPowerShell $command

  if (-not (Wait-HttpOk $frontendHealthUrl 45)) {
    $tail = if (Test-Path $frontendLog) { Get-Content $frontendLog -Tail 80 | Out-String } else { "" }
    throw "Frontend failed to start on $frontendUrl.`n$tail"
  }
  Write-Host "Frontend started: $frontendUrl"
}

function Test-ApiThroughFrontend {
  $url = if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { "http://127.0.0.1:$FrontendPort/api/health" } else { "http://${HostName}:$FrontendPort/api/health" }
  if (-not (Wait-ApiHealth $url 15)) {
    throw "Frontend API proxy failed: $url. The page may open, but uploads/analyze/import will fail with 'Failed to fetch'."
  }
  Write-Host "API proxy healthy: $url"
}

Write-Host "Localization Workflow Studio"
Write-Host "Repo: $repoRoot"
Write-Host "Data: $DataRoot"

Start-Backend
Start-Frontend
Test-ApiThroughFrontend

$openUrl = "http://${HostName}:$FrontendPort/"
Write-Host ""
Write-Host "Workbench ready: $openUrl"
if (-not $NoOpen) {
  Start-Process $openUrl
}
