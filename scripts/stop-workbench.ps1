param(
  [int[]]$Ports = @(8000, 5173, 5174)
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stopped = 0

foreach ($port in $Ports) {
  $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($connection in $connections) {
    $processId = [int]$connection.OwningProcess
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    $commandLine = [string]($processInfo.CommandLine)
    $isWorkbenchBackend = $commandLine -like "*uvicorn app.main:app --app-dir backend*"
    if ($commandLine -like "*$repoRoot*" -or $isWorkbenchBackend) {
      Stop-Process -Id $processId -Force
      $stopped += 1
      Write-Host "Stopped PID $processId on port $port"
    } else {
      Write-Host "Skipped PID $processId on port $port; command line does not belong to this repo."
    }
  }
}

Write-Host "Stopped $stopped workbench process(es)."
