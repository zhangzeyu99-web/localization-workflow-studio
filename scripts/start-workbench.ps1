param(
  [string]$HostName = "127.0.0.1",
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173,
  [string]$DataRoot = "",
  [ValidateSet("local", "cloud")]
  [string]$DeploymentMode = "local",
  [ValidateSet("off", "required")]
  [string]$AuthMode = "off",
  [switch]$CheckOnly,
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

if ($DeploymentMode -ne "local" -or $AuthMode -ne "off") {
  throw "Windows workbench launcher supports only DeploymentMode=local and AuthMode=off."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $repoRoot "frontend"
$sourceMarker = Join-Path $frontendRoot "package.json"
$packageMarker = Join-Path $frontendRoot "dist\index.html"
if (Test-Path $sourceMarker -PathType Leaf) {
  $TreeMode = "source"
} elseif (Test-Path $packageMarker -PathType Leaf) {
  $TreeMode = "package"
} else {
  throw "Invalid workbench tree: expected frontend/package.json (source) or frontend/dist/index.html (package)."
}

$manifestPath = Join-Path $repoRoot "PACKAGE_MANIFEST.json"
$GitSha = ""
if (Test-Path $manifestPath -PathType Leaf) {
  try {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  } catch {
    throw "PACKAGE_MANIFEST.json is not valid JSON: $($_.Exception.Message)"
  }
  if ($manifest.git_sha -is [string]) {
    $GitSha = $manifest.git_sha.Trim()
  }
  if (-not $GitSha) {
    throw "PACKAGE_MANIFEST.json must contain a non-empty git_sha"
  }
} else {
  $GitSha = (& git -C $repoRoot rev-parse --short=12 HEAD 2>$null).Trim()
  if (-not $GitSha) {
    throw "Could not resolve the source tree Git SHA."
  }
}

$runtimeDir = Join-Path $repoRoot ".tmp\runtime"
$backendPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
  $backendPython = (Get-Command python -ErrorAction Stop).Source
}
$backendPython = (Resolve-Path $backendPython).Path
$backendProcessExecutable = (& $backendPython -c "import os, sys; print(os.path.realpath(os.path.join(sys.base_prefix, 'python.exe')))" 2>$null).Trim()
if (-not $backendProcessExecutable) {
  $backendProcessExecutable = $backendPython
}
$backendProcessExecutable = [IO.Path]::GetFullPath($backendProcessExecutable)
$backendRoot = (Resolve-Path (Join-Path $repoRoot "backend")).Path
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$fullPath = if ($userPath) { "$machinePath;$userPath" } else { $machinePath }
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (-not $DataRoot) {
  $DataRoot = $env:LWS_DATA_ROOT
}
if (-not $DataRoot) {
  if ($TreeMode -eq "package") {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not $localAppData) {
      throw "Could not resolve the current user's LocalApplicationData directory. Pass -DataRoot explicitly."
    }
    $DataRoot = Join-Path $localAppData "LocalizationWorkflowStudio\data"
  } else {
    $DataRoot = "D:\codex\localization-workflow-studio-data"
  }
}
$DataRoot = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($DataRoot))

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

function Test-ExpectedDataRoot([string]$ActualDataRoot) {
  if (-not $ActualDataRoot) { return $false }
  try {
    $actual = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($ActualDataRoot)).TrimEnd('\', '/')
    $expected = $DataRoot.TrimEnd('\', '/')
    return $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase)
  } catch {
    return $false
  }
}

function Test-ExpectedApiIdentity([string]$Url) {
  try {
    $health = Invoke-RestMethod -Uri $Url -TimeoutSec 2
    $versionUrl = $Url.Replace("/api/health", "/api/version")
    $version = Invoke-RestMethod -Uri $versionUrl -TimeoutSec 2
    return (
      $null -ne $health -and
      $health.ok -eq $true -and
      $health.deployment_mode -eq "local" -and
      $health.auth_mode -eq "off" -and
      $health.runtime_profile -eq "local-off" -and
      (Test-ExpectedDataRoot ([string]$health.data_root)) -and
      $null -ne $version -and
      $version.deployment_mode -eq "local" -and
      $version.auth_mode -eq "off" -and
      $version.runtime_profile -eq "local-off" -and
      (Test-ExpectedDataRoot ([string]$version.data_root)) -and
      $version.git_sha -eq $GitSha
    )
  } catch {
    return $false
  }
}

function Test-PackageApiIdentity([string]$Url) {
  return Test-ExpectedApiIdentity $Url
}

function Test-ListenerCoversHost($Listeners, [string]$RequestedHost) {
  foreach ($listener in @($Listeners)) {
    $address = [string]$listener.LocalAddress
    if (
      ($RequestedHost -eq "0.0.0.0" -and $address -eq "0.0.0.0") -or
      ($RequestedHost -eq "::" -and $address -eq "::") -or
      ($RequestedHost -in @("127.0.0.1", "localhost") -and $address -in @("127.0.0.1", "0.0.0.0")) -or
      ($RequestedHost -notin @("0.0.0.0", "::", "127.0.0.1", "localhost") -and $address -in @($RequestedHost, "0.0.0.0", "::"))
    ) {
      return $true
    }
  }
  return $false
}

function Test-PackageListenerIdentity($Connections, [string]$HealthUrl) {
  $listeners = @($Connections)
  if ($listeners.Count -eq 0) { return $false }

  $ownerPids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($ownerPids.Count -ne 1) { return $false }

  if (-not (Test-ListenerCoversHost $listeners $HostName)) { return $false }

  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($ownerPids[0])" -ErrorAction SilentlyContinue
  if (-not $process -or -not $process.ExecutablePath -or -not $process.CommandLine) {
    return $false
  }
  $actualExecutable = [IO.Path]::GetFullPath([string]$process.ExecutablePath)
  if (-not $actualExecutable.Equals($backendProcessExecutable, [StringComparison]::OrdinalIgnoreCase)) {
    return $false
  }
  $normalizedCommandLine = ([string]$process.CommandLine).Replace('"', '')
  $requiredFragments = @(
    "-m uvicorn app.main:app",
    "--app-dir $backendRoot",
    "--host $HostName",
    "--port $FrontendPort"
  )
  foreach ($fragment in $requiredFragments) {
    if ($normalizedCommandLine.IndexOf($fragment, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
      return $false
    }
  }

  return Test-PackageApiIdentity $HealthUrl
}

function Test-SourceBackendListenerIdentity($Connections, [string]$HealthUrl) {
  $listeners = @($Connections)
  if ($listeners.Count -eq 0 -or -not (Test-ListenerCoversHost $listeners "127.0.0.1")) { return $false }
  $ownerPids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($ownerPids.Count -ne 1) { return $false }
  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($ownerPids[0])" -ErrorAction SilentlyContinue
  if (-not $process -or -not $process.ExecutablePath -or -not $process.CommandLine) { return $false }
  $actualExecutable = [IO.Path]::GetFullPath([string]$process.ExecutablePath)
  if (-not $actualExecutable.Equals($backendProcessExecutable, [StringComparison]::OrdinalIgnoreCase)) { return $false }
  $normalizedCommandLine = ([string]$process.CommandLine).Replace('"', '')
  foreach ($fragment in @("-m uvicorn app.main:app", "--app-dir $backendRoot", "--host 127.0.0.1", "--port $BackendPort")) {
    if ($normalizedCommandLine.IndexOf($fragment, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
  }
  return Test-ExpectedApiIdentity $HealthUrl
}

function Test-SourceFrontendListenerIdentity($Connections, [string]$HealthUrl) {
  $listeners = @($Connections)
  if ($listeners.Count -eq 0 -or -not (Test-ListenerCoversHost $listeners $HostName)) { return $false }
  $ownerPids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($ownerPids.Count -ne 1) { return $false }
  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($ownerPids[0])" -ErrorAction SilentlyContinue
  if (-not $process -or -not $process.CommandLine) { return $false }
  $normalizedCommandLine = ([string]$process.CommandLine).Replace('"', '')
  foreach ($fragment in @($frontendRoot, "vite", "--host $HostName", "--port $FrontendPort")) {
    if ($normalizedCommandLine.IndexOf($fragment, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
  }
  return Test-ExpectedApiIdentity $HealthUrl
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

function Start-PackageWorkbench {
  $healthUrl = if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { "http://127.0.0.1:$FrontendPort/api/health" } else { "http://${HostName}:$FrontendPort/api/health" }
  $connections = @(Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)
  if ($connections.Count -gt 0) {
    if (Test-PackageListenerIdentity $connections $healthUrl) {
      Write-Host "Packaged workbench already healthy and belongs to this package: $healthUrl"
      return
    }
    $owners = (($connections | Select-Object -ExpandProperty OwningProcess -Unique) -join ", ")
    throw "Workbench port $FrontendPort is occupied by another or incompatible process (PID: $owners). Stop it before starting this package."
  }

  $backendLog = Join-Path $runtimeDir "workbench-$FrontendPort.log"
  $command = @"
`$env:Path = "$fullPath"
Set-Location "$repoRoot"
`$env:LWS_DATA_ROOT = "$DataRoot"
`$env:LWS_DEPLOYMENT_MODE = "$DeploymentMode"
`$env:LWS_AUTH_MODE = "$AuthMode"
`$env:LWS_SERVE_FRONTEND = "1"
`$env:LWS_GIT_SHA = "$GitSha"
& "$backendPython" -m uvicorn app.main:app --app-dir "$backendRoot" --host $HostName --port $FrontendPort *> "$backendLog"
"@
  Start-HiddenPowerShell $command

  if (-not (Wait-ApiHealth $healthUrl 45)) {
    $tail = if (Test-Path $backendLog) { Get-Content $backendLog -Tail 80 | Out-String } else { "" }
    throw "Packaged workbench failed to start on $healthUrl.`n$tail"
  }
  $startedConnections = @(Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)
  if (-not (Test-PackageListenerIdentity $startedConnections $healthUrl)) {
    throw "Packaged workbench responded, but listener identity did not match this package."
  }
  Write-Host "Packaged workbench started: $healthUrl"
}

function Start-SourceBackend {
  $backendHealth = "http://127.0.0.1:$BackendPort/api/health"
  $connections = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)
  if ($connections.Count -gt 0) {
    if (Test-SourceBackendListenerIdentity $connections $backendHealth) {
      Write-Host "Backend already healthy and belongs to this source tree: $backendHealth"
      return
    }
    $owners = (($connections | Select-Object -ExpandProperty OwningProcess -Unique) -join ", ")
    throw "Backend port $BackendPort is occupied by another or incompatible process (PID: $owners). Stop it or change -BackendPort."
  }

  $backendLog = Join-Path $runtimeDir "backend-$BackendPort.log"
  $command = @"
`$env:Path = "$fullPath"
Set-Location "$repoRoot"
`$env:LWS_DATA_ROOT = "$DataRoot"
`$env:LWS_DEPLOYMENT_MODE = "$DeploymentMode"
`$env:LWS_AUTH_MODE = "$AuthMode"
`$env:LWS_SERVE_FRONTEND = "0"
`$env:LWS_GIT_SHA = "$GitSha"
& "$backendPython" -m uvicorn app.main:app --app-dir "$backendRoot" --host 127.0.0.1 --port $BackendPort *> "$backendLog"
"@
  Start-HiddenPowerShell $command

  if (-not (Wait-ApiHealth $backendHealth 45)) {
    $tail = if (Test-Path $backendLog) { Get-Content $backendLog -Tail 80 | Out-String } else { "" }
    throw "Backend failed to start on $backendHealth.`n$tail"
  }
  $startedConnections = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)
  if (-not (Test-SourceBackendListenerIdentity $startedConnections $backendHealth)) {
    throw "Backend responded, but listener identity did not match this source tree."
  }
  Write-Host "Backend started: $backendHealth"
}

function Start-SourceFrontend {
  $frontendUrl = "http://${HostName}:$FrontendPort/"
  $frontendHealthUrl = if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { "http://127.0.0.1:$FrontendPort/" } else { $frontendUrl }
  $frontendApiHealth = $frontendHealthUrl.TrimEnd('/') + "/api/health"
  $connections = @(Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)
  if ($connections.Count -gt 0) {
    if (Test-SourceFrontendListenerIdentity $connections $frontendApiHealth) {
      Write-Host "Frontend already healthy and belongs to this source tree: $frontendUrl"
      return
    }
    $owners = (($connections | Select-Object -ExpandProperty OwningProcess -Unique) -join ", ")
    throw "Frontend port $FrontendPort is occupied by another or incompatible process (PID: $owners). Stop it or change -FrontendPort."
  }

  $frontendLog = Join-Path $runtimeDir "frontend-$FrontendPort.log"
  $apiTarget = "http://127.0.0.1:$BackendPort"
  $command = @"
`$env:Path = "$fullPath"
Set-Location "$frontendRoot"
`$env:LWS_DEPLOYMENT_MODE = "$DeploymentMode"
`$env:LWS_AUTH_MODE = "$AuthMode"
`$env:LWS_SERVE_FRONTEND = "0"
`$env:LWS_API_TARGET = "$apiTarget"
npx vite --host $HostName --port $FrontendPort *> "$frontendLog"
"@
  Start-HiddenPowerShell $command

  if (-not (Wait-HttpOk $frontendHealthUrl 45)) {
    $tail = if (Test-Path $frontendLog) { Get-Content $frontendLog -Tail 80 | Out-String } else { "" }
    throw "Frontend failed to start on $frontendUrl.`n$tail"
  }
  if (-not (Wait-ApiHealth $frontendApiHealth 15)) {
    throw "Frontend started, but its API proxy is unhealthy: $frontendApiHealth"
  }
  $startedConnections = @(Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)
  if (-not (Test-SourceFrontendListenerIdentity $startedConnections $frontendApiHealth)) {
    throw "Frontend responded, but listener identity did not match this source tree."
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
Write-Host "Tree: $TreeMode"
Write-Host "Runtime profile: $DeploymentMode/$AuthMode"
if ($GitSha) { Write-Host "Git SHA: $GitSha" }

if ($CheckOnly) {
  if ($TreeMode -eq "package") {
    $healthUrl = if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { "http://127.0.0.1:$FrontendPort/api/health" } else { "http://${HostName}:$FrontendPort/api/health" }
    $connections = @(Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)
    if (-not (Test-PackageListenerIdentity $connections $healthUrl)) {
      throw "Packaged workbench identity check failed on port $FrontendPort."
    }
  } else {
    $backendHealth = "http://127.0.0.1:$BackendPort/api/health"
    $backendConnections = @(Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue)
    if (-not (Test-SourceBackendListenerIdentity $backendConnections $backendHealth)) {
      throw "Source backend identity check failed on port $BackendPort."
    }
    $frontendHealth = if ($HostName -eq "0.0.0.0" -or $HostName -eq "::") { "http://127.0.0.1:$FrontendPort/api/health" } else { "http://${HostName}:$FrontendPort/api/health" }
    $frontendConnections = @(Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue)
    if (-not (Test-SourceFrontendListenerIdentity $frontendConnections $frontendHealth)) {
      throw "Source frontend identity check failed on port $FrontendPort."
    }
  }
  Write-Host "Workbench identity check passed."
  return
}

if ($TreeMode -eq "package") {
  Start-PackageWorkbench
} else {
  Start-SourceBackend
  Start-SourceFrontend
  Test-ApiThroughFrontend
}

$openUrl = "http://${HostName}:$FrontendPort/"
Write-Host ""
Write-Host "Workbench ready: $openUrl"
if (-not $NoOpen) {
  Start-Process $openUrl
}
