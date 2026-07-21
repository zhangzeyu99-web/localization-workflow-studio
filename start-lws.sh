#!/usr/bin/env bash
set -euo pipefail

# Linux production/local-network starter for Localization Workflow Studio.
# It starts only the FastAPI backend. Nginx should serve frontend/dist and proxy /api/ to this backend.

APP_HOME="${APP_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
LWS_HOST="${LWS_HOST:-127.0.0.1}"
LWS_PORT="${LWS_PORT:-8082}"

export LWS_DEPLOYMENT_MODE="${LWS_DEPLOYMENT_MODE:-cloud}"
export LWS_AUTH_MODE="${LWS_AUTH_MODE:-required}"
export LWS_DATA_ROOT="${LWS_DATA_ROOT:-${APP_HOME}/lws-data}"
export LWS_MAX_UPLOAD_MB="${LWS_MAX_UPLOAD_MB:-1024}"
export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

if [[ -z "${LWS_GIT_SHA:-}" && -f "$APP_HOME/PACKAGE_MANIFEST.json" ]]; then
  manifest_git_sha="$("$PYTHON_BIN" -c '
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8")).get("git_sha")
if not (isinstance(value, str) and value.strip()):
    raise SystemExit("PACKAGE_MANIFEST.json must contain a non-empty string git_sha")
print(value.strip())
' "$APP_HOME/PACKAGE_MANIFEST.json")"
  export LWS_GIT_SHA="$manifest_git_sha"
fi

cd "$APP_HOME"
mkdir -p "$LWS_DATA_ROOT"

echo "[start-lws] Python: $($PYTHON_BIN -c 'import sys; print(sys.executable, "v" + sys.version.split()[0])')"
echo "[start-lws] APP_HOME       = $APP_HOME"
echo "[start-lws] LWS_DATA_ROOT  = $LWS_DATA_ROOT"
echo "[start-lws] bind           = $LWS_HOST:$LWS_PORT"
echo "[start-lws] deployment     = $LWS_DEPLOYMENT_MODE"
echo "[start-lws] auth mode      = $LWS_AUTH_MODE"
echo "[start-lws] runtime profile = $LWS_DEPLOYMENT_MODE-$LWS_AUTH_MODE"
echo "[start-lws] git SHA        = ${LWS_GIT_SHA:-<backend-git-fallback>}"
echo "[start-lws] max upload MB  = $LWS_MAX_UPLOAD_MB"

exec "$PYTHON_BIN" -m uvicorn backend.app.main:app \
  --host "$LWS_HOST" \
  --port "$LWS_PORT" \
  --workers 1
