from __future__ import annotations

from pathlib import Path


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
