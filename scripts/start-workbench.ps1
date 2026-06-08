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
    return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
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

function Start-Backend {
  $backendHealth = "http://127.0.0.1:$BackendPort/api/health"
  if (Test-HttpOk $backendHealth) {
    Write-Host "Backend already healthy: $backendHealth"
    return
  }

  $owner = Get-ListeningProcessId $BackendPort
  if ($owner) {
    throw "Backend port $BackendPort is occupied by PID $owner, but health check failed. Stop that process or change -BackendPort."
  }

  $backendLog = Join-Path $runtimeDir "backend-$BackendPort.log"
  $command = @"
Set-Location "$repoRoot"
`$env:LWS_DATA_ROOT = "$DataRoot"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $BackendPort *> "$backendLog"
"@
  Start-Process -FilePath "powershell" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) -WindowStyle Hidden

  if (-not (Wait-HttpOk $backendHealth 45)) {
    $tail = if (Test-Path $backendLog) { Get-Content $backendLog -Tail 80 | Out-String } else { "" }
    throw "Backend failed to start on $backendHealth.`n$tail"
  }
  Write-Host "Backend started: $backendHealth"
}

function Start-Frontend {
  $frontendUrl = "http://${HostName}:$FrontendPort/"
  if (Test-HttpOk "http://127.0.0.1:$FrontendPort/") {
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
Set-Location "$frontendRoot"
`$env:LWS_API_TARGET = "$apiTarget"
npx vite --host $HostName --port $FrontendPort *> "$frontendLog"
"@
  Start-Process -FilePath "powershell" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) -WindowStyle Hidden

  if (-not (Wait-HttpOk "http://127.0.0.1:$FrontendPort/" 45)) {
    $tail = if (Test-Path $frontendLog) { Get-Content $frontendLog -Tail 80 | Out-String } else { "" }
    throw "Frontend failed to start on $frontendUrl.`n$tail"
  }
  Write-Host "Frontend started: $frontendUrl"
}

function Test-ApiThroughFrontend {
  $url = "http://127.0.0.1:$FrontendPort/api/health"
  if (-not (Test-HttpOk $url)) {
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
