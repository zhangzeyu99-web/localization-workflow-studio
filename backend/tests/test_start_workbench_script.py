from __future__ import annotations

from pathlib import Path
import re


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "start-workbench.ps1"
CONTROL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "lws-workbench-control.ps1"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _control_script_text() -> str:
    return CONTROL_SCRIPT_PATH.read_text(encoding="utf-8")


def test_start_workbench_prefers_repository_virtualenv_for_backend() -> None:
    script = _script_text()

    assert '.venv\\Scripts\\python.exe' in script
    assert '& "$backendPython" -m uvicorn' in script
    assert "\npython -m uvicorn" not in script


def test_start_workbench_requires_real_api_health_payload() -> None:
    script = _script_text()

    assert "function Test-ApiHealth" in script
    assert '.ok -eq $true' in script
    assert "Wait-ApiHealth $backendHealth" in script
    assert "Wait-ApiHealth $url" in script
    assert "$response.StatusCode -lt 400" in script
    assert "$response.StatusCode -lt 500" not in script


def test_workbench_control_requires_real_api_health_payload() -> None:
    script = _control_script_text()

    assert "function Test-ApiHealth" in script
    assert '.ok -eq $true' in script
    assert "Test-HttpOk" not in script
    assert "$response.StatusCode -lt 500" not in script


def _function_body(script: str, name: str, next_name: str) -> str:
    return script.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def test_start_workbench_declares_and_restricts_explicit_local_profile() -> None:
    script = _script_text()

    assert re.search(
        r'\[ValidateSet\("local", "cloud"\)\]\s*\[string\]\$DeploymentMode = "local"',
        script,
    )
    assert re.search(
        r'\[ValidateSet\("off", "required"\)\]\s*\[string\]\$AuthMode = "off"',
        script,
    )
    assert '$DeploymentMode -ne "local" -or $AuthMode -ne "off"' in script
    assert script.count('`$env:LWS_DEPLOYMENT_MODE = "$DeploymentMode"') >= 2
    assert script.count('`$env:LWS_AUTH_MODE = "$AuthMode"') >= 2


def test_start_workbench_selects_source_or_dist_only_topology() -> None:
    script = _script_text()
    package_body = _function_body(script, "Start-PackageWorkbench", "Start-SourceBackend")
    source_backend = _function_body(script, "Start-SourceBackend", "Start-SourceFrontend")
    source_frontend = _function_body(script, "Start-SourceFrontend", "Test-ApiThroughFrontend")

    assert 'Join-Path $frontendRoot "package.json"' in script
    assert 'Join-Path $frontendRoot "dist\\index.html"' in script
    assert "Invalid workbench tree" in script

    assert '`$env:LWS_SERVE_FRONTEND = "1"' in package_body
    assert '-m uvicorn app.main:app --app-dir "$backendRoot" --host $HostName --port $FrontendPort' in package_body
    assert package_body.count("Start-HiddenPowerShell") == 1
    assert "npx" not in package_body.lower()
    assert "npm" not in package_body.lower()
    assert "vite" not in package_body.lower()

    for child_command in (package_body, source_backend, source_frontend):
        assert '`$env:LWS_DEPLOYMENT_MODE = "$DeploymentMode"' in child_command
        assert '`$env:LWS_AUTH_MODE = "$AuthMode"' in child_command

    assert 'npx vite --host $HostName --port $FrontendPort' in source_frontend
    assert '`$env:LWS_API_TARGET = "$apiTarget"' in source_frontend
    assert 'if ($TreeMode -eq "package")' in script
    assert "Start-PackageWorkbench" in script.split('if ($TreeMode -eq "package")', 1)[1]


def test_start_workbench_uses_nonempty_manifest_sha_when_present() -> None:
    script = _script_text()

    assert 'Join-Path $repoRoot "PACKAGE_MANIFEST.json"' in script
    assert "ConvertFrom-Json" in script
    assert ".git_sha" in script
    assert "PACKAGE_MANIFEST.json must contain a non-empty git_sha" in script
    assert '`$env:LWS_GIT_SHA = "$GitSha"' in script


def test_dist_only_package_defaults_to_user_local_data_root() -> None:
    script = _script_text()
    data_root_defaults = script.split("if (-not $DataRoot) {", 2)[2].split(
        "function Get-ListeningProcessId", 1
    )[0]

    assert '$TreeMode -eq "package"' in data_root_defaults
    assert '[Environment]::GetFolderPath("LocalApplicationData")' in data_root_defaults
    assert 'LocalizationWorkflowStudio\\data' in data_root_defaults
    assert 'D:\\codex\\localization-workflow-studio-data' in data_root_defaults


def test_controller_uses_mode_aware_ports_health_and_firewall() -> None:
    script = _control_script_text()
    package_start = _function_body(script, "Invoke-PackageWorkbenchEnsure", "Invoke-SourceWorkbenchEnsure")
    source_start = _function_body(script, "Invoke-SourceWorkbenchEnsure", "Invoke-WorkbenchEnsure")

    assert 'Join-Path $RepoRoot "frontend\\package.json"' in script
    assert 'Join-Path $RepoRoot "frontend\\dist\\index.html"' in script
    assert 'New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port' in script

    assert '@("-HostName", "0.0.0.0", "-FrontendPort", "5173", "-NoOpen")' in package_start
    assert "http://127.0.0.1:5173/api/health" in package_start
    assert "8000" not in package_start
    assert "5174" not in package_start

    assert "5173" in source_start
    assert "5174" in source_start
    assert 'Ensure-LanFirewall -Port 5174' in source_start
    assert 'Ensure-LanFirewall -Port 5173' in package_start


def test_packaged_launcher_reuses_only_the_current_lan_bound_uvicorn() -> None:
    start_script = _script_text()
    control_script = _control_script_text()
    package_start = _function_body(
        start_script,
        "Start-PackageWorkbench",
        "Start-SourceBackend",
    )
    package_ensure = _function_body(
        control_script,
        "Invoke-PackageWorkbenchEnsure",
        "Invoke-SourceWorkbenchEnsure",
    )
    recovery = _function_body(
        control_script,
        "Invoke-StartScriptWithRecovery",
        "Invoke-PackageWorkbenchEnsure",
    )

    assert "function Test-PackageListenerIdentity" in start_script
    assert "Get-NetTCPConnection -LocalPort $FrontendPort -State Listen" in package_start
    assert "LocalAddress" in start_script
    assert "Get-CimInstance Win32_Process" in start_script
    assert "ExecutablePath" in start_script
    assert '"-m uvicorn app.main:app"' in start_script
    assert '"--app-dir $backendRoot"' in start_script
    assert '"--host $HostName"' in start_script
    assert '"--port $FrontendPort"' in start_script
    assert "function Test-PackageApiIdentity" in start_script
    assert 'Replace("/api/health", "/api/version")' in start_script
    assert 'runtime_profile -eq "local-off"' in start_script
    assert "$version.git_sha -eq $GitSha" in start_script
    assert "Test-ExpectedDataRoot" in start_script
    assert "$health.data_root" in start_script
    assert "$version.data_root" in start_script
    assert "occupied by another or incompatible process" in package_start

    # The controller must delegate every package reuse decision to the strict
    # launcher instead of treating an arbitrary healthy 5173 service as ours.
    assert "Test-ApiHealth" not in package_ensure
    assert "Invoke-StartScriptWithRecovery" in package_ensure
    assert "$exitCode -eq 0" in recovery
    assert recovery.index("$exitCode -eq 0") < recovery.index("Start-Sleep -Seconds 3")


def test_source_launcher_reuses_only_matching_repo_profile_sha_and_data_root() -> None:
    start_script = _script_text()
    control_script = _control_script_text()
    source_backend = _function_body(start_script, "Start-SourceBackend", "Start-SourceFrontend")
    source_frontend = _function_body(start_script, "Start-SourceFrontend", "Test-ApiThroughFrontend")
    source_ensure = _function_body(
        control_script,
        "Invoke-SourceWorkbenchEnsure",
        "Invoke-WorkbenchEnsure",
    )
    healthy = _function_body(
        control_script,
        "Test-WorkbenchHealthy",
        "Get-MonitorProcess",
    )

    assert 'rev-parse --short=12 HEAD' in start_script
    assert "function Test-ExpectedApiIdentity" in start_script
    assert "function Test-SourceBackendListenerIdentity" in start_script
    assert "function Test-SourceFrontendListenerIdentity" in start_script
    assert "Test-SourceBackendListenerIdentity" in source_backend
    assert "Test-SourceFrontendListenerIdentity" in source_frontend
    assert "occupied by another or incompatible process" in source_backend
    assert "occupied by another or incompatible process" in source_frontend

    # The controller must always delegate reuse decisions to the strict launcher.
    assert "Test-ApiHealth" not in source_ensure
    assert source_ensure.count("Invoke-StartScriptWithRecovery") == 2

    # Status/monitor health must use the same non-mutating strict identity check.
    assert '"-CheckOnly"' in healthy
    assert "Test-ApiHealth" not in healthy


def test_monitor_start_is_safe_when_control_script_path_contains_spaces() -> None:
    script = _control_script_text()
    start_monitor = _function_body(script, "Start-Monitor", "Stop-Monitor")
    get_monitor = _function_body(script, "Get-MonitorProcess", "Start-Monitor")

    assert "function Get-MonitorEncodedCommand" in script
    assert "Get-MonitorEncodedCommand" in start_monitor
    assert "Get-MonitorEncodedCommand" in get_monitor
    assert 'Replace("\'", "\'\'")' in script
    assert "-EncodedCommand" in start_monitor
    assert "expectedEncodedCommand" in get_monitor
    assert '"-File", $ControlScript' not in start_monitor


def test_controller_reuses_topology_for_status_monitor_and_stop() -> None:
    script = _control_script_text()
    port_rows = _function_body(script, "Get-WorkbenchPortRows", "Invoke-StartScriptWithRecovery")
    stop = _function_body(script, "Invoke-WorkbenchStop", "Test-WorkbenchHealthy")
    healthy = _function_body(script, "Test-WorkbenchHealthy", "Get-MonitorProcess")
    status = _function_body(script, "Show-Status", "Invoke-MonitorLoop")

    assert "function Get-WorkbenchTopology" in script
    assert "Get-WorkbenchTopology" in port_rows
    assert "Get-WorkbenchTopology" in stop
    assert "Get-WorkbenchTopology" in healthy
    assert "Get-WorkbenchTopology" in status
    assert "-Ports $topology.Ports" in stop
    assert '"-CheckOnly"' in healthy
    assert "$topology.LocalUrl" in status
    assert "$topology.LanPort" in status


def test_workbench_control_can_install_desktop_shortcut() -> None:
    script = _control_script_text()
    desktop_shortcut = script.split("function Install-DesktopShortcut", 1)[1].split(
        "function Install-Autostart", 1
    )[0]

    assert '"install-shortcut"' in script
    assert "function Install-DesktopShortcut" in script
    assert (
        '$shortcutName = "$([char]0x672C)$([char]0x5730)$([char]0x5316)'
        '$([char]0x5DE5)$([char]0x4F5C)$([char]0x53F0).lnk"'
    ) in script
    assert '"本地化工作台.lnk"' not in script
    assert '"install-shortcut" {' in script
    assert "$desktopCmd" not in desktop_shortcut
    assert "$shortcut.TargetPath = $powershellPath" in desktop_shortcut
    assert '-File `"$ControlScript`" -Action start' in desktop_shortcut


def test_autostart_shortcut_does_not_depend_on_desktop_launcher_file() -> None:
    script = _control_script_text()
    autostart = script.split("function Install-Autostart", 1)[1].split(
        "function Uninstall-Autostart", 1
    )[0]

    assert "$desktopCmd" not in autostart
    assert "$shortcut.TargetPath = $powershellPath" in autostart
    assert '-File `"$ControlScript`" -Action start' in autostart
