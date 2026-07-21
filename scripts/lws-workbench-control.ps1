param(
  [ValidateSet("start", "restart", "status", "stop", "monitor", "monitor-status", "monitor-stop", "install-shortcut", "install-autostart", "uninstall-autostart")]
  [string]$Action = "start"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StartScript = Join-Path $RepoRoot "scripts\start-workbench.ps1"
$StopScript = Join-Path $RepoRoot "scripts\stop-workbench.ps1"
$RuntimeDir = Join-Path $RepoRoot ".tmp\runtime"
$MonitorPidFile = Join-Path $RuntimeDir "desktop-port-monitor.pid"
$MonitorLog = Join-Path $RuntimeDir "desktop-port-monitor.log"
$ControlScript = $PSCommandPath

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Write-MonitorLog([string]$Message) {
  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -Path $MonitorLog -Value $line -Encoding UTF8
}

function Test-ApiHealth([string]$Url) {
  try {
    $response = Invoke-RestMethod -Uri $Url -TimeoutSec 5
    return ($null -ne $response -and $response.ok -eq $true)
  } catch {
    return $false
  }
}

function Get-LanIps {
  @(Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address.IPAddress -notlike "169.254*" } |
    ForEach-Object { $_.IPv4Address.IPAddress })
}

function Get-WorkbenchTopology {
  $sourceMarker = Join-Path $RepoRoot "frontend\package.json"
  $packageMarker = Join-Path $RepoRoot "frontend\dist\index.html"
  if (Test-Path $sourceMarker -PathType Leaf) {
    return [pscustomobject]@{
      Mode = "source"
      Ports = @(8000, 5173, 5174)
      Rows = @(
        [pscustomobject]@{ Port = 8000; HealthUrl = "http://127.0.0.1:8000/api/health" },
        [pscustomobject]@{ Port = 5173; HealthUrl = "http://127.0.0.1:5173/api/health" },
        [pscustomobject]@{ Port = 5174; HealthUrl = "http://127.0.0.1:5174/api/health" }
      )
      HealthUrls = @(
        "http://127.0.0.1:8000/api/health",
        "http://127.0.0.1:5173/api/health",
        "http://127.0.0.1:5174/api/health"
      )
      LocalUrl = "http://127.0.0.1:5173/"
      LanPort = 5174
    }
  }
  if (Test-Path $packageMarker -PathType Leaf) {
    return [pscustomobject]@{
      Mode = "package"
      Ports = @(5173)
      Rows = @(
        [pscustomobject]@{ Port = 5173; HealthUrl = "http://127.0.0.1:5173/api/health" }
      )
      HealthUrls = @("http://127.0.0.1:5173/api/health")
      LocalUrl = "http://127.0.0.1:5173/"
      LanPort = 5173
    }
  }
  throw "Invalid workbench tree: expected frontend/package.json or frontend/dist/index.html."
}

function Ensure-LanFirewall([int]$Port) {
  $ruleName = if ($Port -eq 5174) { "LWS Frontend LAN 5174" } else { "LWS Packaged LAN 5173" }
  $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($existing -and $existing.Enabled -eq "True") {
    return
  }
  if ($existing) {
    Enable-NetFirewallRule -DisplayName $ruleName | Out-Null
    Write-Host "Firewall rule enabled: $ruleName"
    return
  }
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
  Write-Host "Firewall rule created: $ruleName"
}

function Get-WorkbenchPortRows {
  $topology = Get-WorkbenchTopology
  foreach ($row in $topology.Rows) {
    $port = [int]$row.Port
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
      [pscustomobject]@{ Port = $port; Pid = ""; Process = "not listening"; Url = ""; Health = "down" }
      continue
    }
    foreach ($connection in $connections) {
      $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
      $url = [string]$row.HealthUrl
      [pscustomobject]@{
        Port = $port
        Pid = $connection.OwningProcess
        Process = if ($process) { $process.ProcessName } else { "unknown" }
        Url = $url
        Health = if (Test-ApiHealth $url) { "ok" } else { "unhealthy" }
      }
    }
  }
}

function Invoke-StartScriptWithRecovery([string[]]$Arguments, [string]$HealthUrl, [string]$Label) {
  $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $StartScript @Arguments 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -eq 0 -and (Test-ApiHealth $HealthUrl)) {
    $output | ForEach-Object { Write-Host $_ }
    return
  }
  Start-Sleep -Seconds 3
  if (Test-ApiHealth $HealthUrl) {
    Write-Host "$Label is healthy after retry: $HealthUrl"
    return
  }
  $output | ForEach-Object { Write-Host $_ }
  throw "$Label failed to start. Health check failed: $HealthUrl"
}

function Invoke-PackageWorkbenchEnsure {
  Ensure-LanFirewall -Port 5173
  if (-not (Test-ApiHealth "http://127.0.0.1:5173/api/health")) {
    Write-Host "Starting packaged workbench on port 5173..."
    Invoke-StartScriptWithRecovery @("-HostName", "0.0.0.0", "-FrontendPort", "5173", "-NoOpen") "http://127.0.0.1:5173/api/health" "Packaged workbench"
  } else {
    Write-Host "Packaged workbench already healthy: http://127.0.0.1:5173/"
  }
}

function Invoke-SourceWorkbenchEnsure {
  Ensure-LanFirewall -Port 5174
  if (-not (Test-ApiHealth "http://127.0.0.1:8000/api/health")) {
    Write-Host "Starting backend on port 8000..."
    Invoke-StartScriptWithRecovery @("-NoOpen", "-FrontendPort", "5173") "http://127.0.0.1:8000/api/health" "Backend"
  } else {
    Write-Host "Backend already healthy: http://127.0.0.1:8000/api/health"
  }

  if (-not (Test-ApiHealth "http://127.0.0.1:5173/api/health")) {
    Write-Host "Starting local frontend on port 5173..."
    Invoke-StartScriptWithRecovery @("-NoOpen") "http://127.0.0.1:5173/api/health" "Local frontend"
  } else {
    Write-Host "Local frontend already healthy: http://127.0.0.1:5173/"
  }

  if (-not (Test-ApiHealth "http://127.0.0.1:5174/api/health")) {
    Write-Host "Starting LAN frontend on port 5174..."
    Invoke-StartScriptWithRecovery @("-HostName", "0.0.0.0", "-FrontendPort", "5174", "-NoOpen") "http://127.0.0.1:5174/api/health" "LAN frontend"
  } else {
    Write-Host "LAN frontend already healthy: http://0.0.0.0:5174/"
  }
}

function Invoke-WorkbenchEnsure {
  if (-not (Test-Path $StartScript)) {
    throw "Missing start script: $StartScript"
  }

  $topology = Get-WorkbenchTopology
  if ($topology.Mode -eq "package") {
    Invoke-PackageWorkbenchEnsure
  } else {
    Invoke-SourceWorkbenchEnsure
  }

  if (-not (Test-WorkbenchHealthy)) {
    throw "One or more workbench services are still unhealthy after start."
  }
}

function Invoke-WorkbenchStop {
  if (-not (Test-Path $StopScript)) {
    throw "Missing stop script: $StopScript"
  }
  $topology = Get-WorkbenchTopology
  & $StopScript -Ports $topology.Ports
}

function Test-WorkbenchHealthy {
  $topology = Get-WorkbenchTopology
  foreach ($url in $topology.HealthUrls) {
    if (-not (Test-ApiHealth $url)) {
      return $false
    }
  }
  return $true
}

function Get-MonitorProcess {
  if (-not (Test-Path $MonitorPidFile)) {
    return $null
  }
  $raw = (Get-Content $MonitorPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  $pidValue = 0
  if (-not [int]::TryParse([string]$raw, [ref]$pidValue)) {
    return $null
  }
  $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
  if (-not $process) {
    return $null
  }
  $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
  $scriptName = Split-Path -Leaf $ControlScript
  if ($cim -and ([string]$cim.CommandLine) -like "*$scriptName*" -and ([string]$cim.CommandLine) -like "*monitor*") {
    return $process
  }
  return $null
}

function Start-Monitor {
  $existing = Get-MonitorProcess
  if ($existing) {
    Write-Host "Monitor already running: PID $($existing.Id)"
    return
  }
  $args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $ControlScript,
    "-Action", "monitor"
  )
  $process = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden -PassThru
  Start-Sleep -Milliseconds 500
  if ($process.HasExited) {
    throw "Monitor failed to start. Check log: $MonitorLog"
  }
  Set-Content -Path $MonitorPidFile -Value $process.Id -Encoding ASCII
  Write-Host "Monitor started: PID $($process.Id)"
}

function Stop-Monitor {
  $existing = Get-MonitorProcess
  if ($existing) {
    Stop-Process -Id $existing.Id -Force
    Write-Host "Monitor stopped: PID $($existing.Id)"
  } else {
    Write-Host "Monitor is not running."
  }
  Remove-Item -LiteralPath $MonitorPidFile -Force -ErrorAction SilentlyContinue
}

function Show-Status {
  $topology = Get-WorkbenchTopology
  $rows = Get-WorkbenchPortRows
  $rows | Format-Table -AutoSize
  $lanIps = Get-LanIps
  Write-Host ""
  Write-Host "Local UI: $($topology.LocalUrl)"
  foreach ($ip in $lanIps) {
    Write-Host "LAN UI:   http://${ip}:$($topology.LanPort)/"
  }
  $monitor = Get-MonitorProcess
  if ($monitor) {
    Write-Host "Monitor:  running, PID $($monitor.Id)"
  } else {
    Write-Host "Monitor:  stopped"
  }
  Write-Host "Log:      $MonitorLog"
}

function Invoke-MonitorLoop {
  Set-Content -Path $MonitorPidFile -Value $PID -Encoding ASCII
  Write-MonitorLog "monitor started pid=$PID"
  $lastState = ""
  while ($true) {
    try {
      $healthy = Test-WorkbenchHealthy
      $state = if ($healthy) { "healthy" } else { "unhealthy" }
      if ($state -ne $lastState) {
        Write-MonitorLog "state=$state"
        $lastState = $state
      }
      if (-not $healthy) {
        Write-MonitorLog "attempting start for missing or unhealthy services"
        try {
          Invoke-WorkbenchEnsure *> $null
          Write-MonitorLog "start attempt completed"
        } catch {
          Write-MonitorLog ("start attempt failed: " + $_.Exception.Message)
        }
      }
    } catch {
      Write-MonitorLog ("monitor loop error: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds 20
  }
}

function Install-DesktopShortcut {
  $desktopDir = [Environment]::GetFolderPath("Desktop")
  $shortcutName = "$([char]0x672C)$([char]0x5730)$([char]0x5316)$([char]0x5DE5)$([char]0x4F5C)$([char]0x53F0).lnk"
  $shortcutPath = Join-Path $desktopDir $shortcutName
  $powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $powershellPath
  $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ControlScript`" -Action start"
  $shortcut.WorkingDirectory = $RepoRoot
  $shortcut.WindowStyle = 1
  $shortcut.Description = "Start Localization Workflow Studio (local + LAN)"
  $shortcut.Save()
  Write-Host "Desktop shortcut installed: $shortcutPath"
}

function Install-Autostart {
  $startupDir = [Environment]::GetFolderPath("Startup")
  $shortcutPath = Join-Path $startupDir "Localization Workbench.lnk"
  $powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $powershellPath
  $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ControlScript`" -Action start"
  $shortcut.WorkingDirectory = $RepoRoot
  $shortcut.WindowStyle = 7
  $shortcut.Description = "Start Localization Workflow Studio (local + LAN)"
  $shortcut.Save()
  Write-Host "Autostart installed: $shortcutPath"
}

function Uninstall-Autostart {
  $startupDir = [Environment]::GetFolderPath("Startup")
  $shortcutPath = Join-Path $startupDir "Localization Workbench.lnk"
  if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Host "Autostart removed: $shortcutPath"
  } else {
    Write-Host "Autostart shortcut not found."
  }
}

switch ($Action) {
  "start" {
    Invoke-WorkbenchEnsure
    Start-Monitor
    Show-Status
  }
  "restart" {
    Stop-Monitor
    Invoke-WorkbenchStop
    Start-Sleep -Seconds 2
    Invoke-WorkbenchEnsure
    Start-Monitor
    Show-Status
  }
  "status" {
    Show-Status
  }
  "stop" {
    Stop-Monitor
    Invoke-WorkbenchStop
    Show-Status
  }
  "monitor" {
    Invoke-MonitorLoop
  }
  "monitor-status" {
    $monitor = Get-MonitorProcess
    if ($monitor) {
      Write-Host "Monitor running: PID $($monitor.Id)"
    } else {
      Write-Host "Monitor stopped."
    }
    if (Test-Path $MonitorLog) {
      Write-Host ""
      Get-Content $MonitorLog -Tail 20
    }
  }
  "monitor-stop" {
    Stop-Monitor
  }
  "install-shortcut" {
    Install-DesktopShortcut
  }
  "install-autostart" {
    Install-Autostart
  }
  "uninstall-autostart" {
    Uninstall-Autostart
  }
}
