#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_PATH="${SCRIPT_DIR}/config.yml"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"
MCP_MANIFEST_PATH="${MCP_MANIFEST_PATH:-}"
WORKSPACE_ROOT_ARG=""

usage() {
  echo "Usage: $0 --workspace-root <dir>" >&2
  echo "   or: SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT=<dir> $0" >&2
  echo "   or: WORKSPACE_ROOT=<dir> $0" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace-root)
      if [[ $# -lt 2 ]]; then
        echo "--workspace-root にはディレクトリを指定してください。" >&2
        usage
        exit 1
      fi
      WORKSPACE_ROOT_ARG="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "未対応の引数です: $1" >&2
      usage
      exit 1
      ;;
  esac
done

RAW_WORKSPACE_ROOT="${WORKSPACE_ROOT_ARG:-${SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT:-${WORKSPACE_ROOT:-}}}"
if [[ -z "${RAW_WORKSPACE_ROOT}" ]]; then
  echo "workspace ルートが未指定です。--workspace-root もしくは SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT を指定してください。" >&2
  usage
  exit 1
fi

mkdir -p "${RAW_WORKSPACE_ROOT}"
CASES_ROOT="$(cd "${RAW_WORKSPACE_ROOT}" && pwd -P)"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "python3 が見つかりません。PYTHON_BIN で Python 実行ファイルを指定してください。" >&2
    exit 1
  fi
fi

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export SUPPORT_OPE_SAMPLE_CONFIG="${CONFIG_PATH}"
export SUPPORT_OPE_SAMPLE_HOST="${HOST}"
export SUPPORT_OPE_SAMPLE_PORT="${PORT}"
export SUPPORT_OPE_SAMPLE_MCP_MANIFEST_PATH="${MCP_MANIFEST_PATH}"
export SUPPORT_OPE_SAMPLE_CASES_ROOT="${CASES_ROOT}"

echo "Starting sample API"
echo "  config: ${CONFIG_PATH}"
echo "  workspace root: ${CASES_ROOT}"
echo "  url:    http://${HOST}:${PORT}"

exec "${PYTHON_BIN}" - <<'PY'
import os
import tempfile
from pathlib import Path

import uvicorn
import yaml

from support_ope_agents.interfaces.api import create_app

config_path = Path(os.environ["SUPPORT_OPE_SAMPLE_CONFIG"])
manifest_override = os.environ.get("SUPPORT_OPE_SAMPLE_MCP_MANIFEST_PATH", "").strip()
cases_root = os.environ["SUPPORT_OPE_SAMPLE_CASES_ROOT"]

with config_path.open("r", encoding="utf-8") as handle:
  raw = yaml.safe_load(handle) or {}

section = raw.setdefault("support_ope_agents", {})
tools = section.setdefault("tools", {})
logical_tools = tools.setdefault("logical_tools", {})
manifest_path = manifest_override or tools.get("mcp_manifest_path") or ""

effective_config_path = config_path
if manifest_path:
  tools["mcp_manifest_path"] = manifest_path
else:
  for tool_name in ("external_ticket", "internal_ticket"):
    tool_settings = logical_tools.get(tool_name)
    if isinstance(tool_settings, dict):
      tool_settings["enabled"] = False
  with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yml", delete=False) as temp_handle:
    yaml.safe_dump(raw, temp_handle, allow_unicode=True, sort_keys=False)
    effective_config_path = Path(temp_handle.name)
  print("MCP manifest was not configured. Starting with ticket MCP tools disabled for UI testing.")

app = create_app(str(effective_config_path), cases_root=cases_root)
uvicorn.run(
    app,
    host=os.environ["SUPPORT_OPE_SAMPLE_HOST"],
    port=int(os.environ["SUPPORT_OPE_SAMPLE_PORT"]),
)
PY