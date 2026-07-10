param(
  [string]$CodexDesktopRoot = "$env:LOCALAPPDATA\Programs\OpenAI\CodexDesktop",
  [switch]$Json
)

$ErrorActionPreference = "Stop"

$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [bool]$Passed, [string]$Detail) {
  $checks.Add([pscustomobject]@{
    name = $Name
    passed = $Passed
    detail = $Detail
  })
}

function Add-PathCheck([string]$Name, [string]$Path) {
  $exists = Test-Path -LiteralPath $Path
  Add-Check $Name $exists $(if ($exists) { $Path } else { "Missing: $Path" })
}

$nodeModules = Join-Path $CodexDesktopRoot "resources\cua_node\bin\node_modules"
$skyRoot = Join-Path $nodeModules "@oai\sky"
$skyIndex = Join-Path $skyRoot "dist\project\cua\sky_js\src\index.js"
$statsigGlobal = Join-Path $nodeModules '@statsig\client-core\src\$_StatsigGlobal.js'
$tslib = Join-Path $skyRoot "dist\node_modules\.pnpm\@rollup_plugin-typescript@12.1.2_rollup@4.35.0_tslib@2.8.1_typescript@5.7.3\node_modules\tslib\tslib.es6.js"

Add-PathCheck "Codex Desktop root" $CodexDesktopRoot
Add-PathCheck "Computer Use node_modules" $nodeModules
Add-PathCheck "Standard @oai scope" (Join-Path $nodeModules "@oai")
Add-PathCheck "Sky package" $skyRoot
Add-PathCheck "Sky entrypoint" $skyIndex
Add-PathCheck "Decoded Statsig global" $statsigGlobal
Add-PathCheck "Bundled tslib" $tslib

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
  Add-Check "Node.js" $false "node was not found on PATH"
  Add-Check "Sky module import" $false "Skipped because node was not found"
} else {
  Add-Check "Node.js" $true $nodeCommand.Source
  if (Test-Path -LiteralPath $skyIndex) {
    $skyUri = [System.Uri]::new($skyIndex).AbsoluteUri
    $nodeOutput = & $nodeCommand.Source --input-type=module -e "import('$skyUri').then(() => console.log('sky-import-ok')).catch(error => { console.error(error.message); process.exitCode = 1 })" 2>&1
    $importPassed = $LASTEXITCODE -eq 0 -and ($nodeOutput -join "`n") -match "sky-import-ok"
    Add-Check "Sky module import" $importPassed ($nodeOutput -join "`n")
  } else {
    Add-Check "Sky module import" $false "Skipped because the Sky entrypoint is missing"
  }
}

$passed = -not ($checks | Where-Object { -not $_.passed })
$result = [pscustomobject]@{
  passed = $passed
  codex_desktop_root = $CodexDesktopRoot
  checks = $checks
  note = "This script verifies packaged files only. A direct Codex task must separately provide trusted nativePipe or launchServices access."
}

if ($Json) {
  $result | ConvertTo-Json -Depth 5
} else {
  $checks | Format-Table -AutoSize
  Write-Output ""
  Write-Output $(if ($passed) { "PASS: Computer Use package runtime is intact." } else { "FAIL: Computer Use package runtime is incomplete." })
  Write-Output $result.note
}

if (-not $passed) { exit 1 }
