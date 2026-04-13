#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_SCRIPT="${SCRIPT_DIR}/start-sample-api.sh"
UI_SCRIPT="${SCRIPT_DIR}/start-sample-react.sh"
HOST="${HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"
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
WORKSPACE_ROOT="$(cd "${RAW_WORKSPACE_ROOT}" && pwd -P)"

if [[ ! -x "${API_SCRIPT}" ]]; then
  echo "API script is not executable: ${API_SCRIPT}" >&2
  exit 1
fi

if [[ ! -x "${UI_SCRIPT}" ]]; then
  echo "React script is not executable: ${UI_SCRIPT}" >&2
  exit 1
fi

api_pid=""
ui_pid=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "${ui_pid}" ]] && kill -0 "${ui_pid}" >/dev/null 2>&1; then
    kill "${ui_pid}" >/dev/null 2>&1 || true
    wait "${ui_pid}" 2>/dev/null || true
  fi
  if [[ -n "${api_pid}" ]] && kill -0 "${api_pid}" >/dev/null 2>&1; then
    kill "${api_pid}" >/dev/null 2>&1 || true
    wait "${api_pid}" 2>/dev/null || true
  fi
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

echo "Starting ai-platform-poc sample stack"
echo "  workspace root: ${WORKSPACE_ROOT}"
echo "  api: http://${HOST}:${API_PORT}"
echo "  ui:  http://${HOST}:${UI_PORT}"

HOST="${HOST}" PORT="${API_PORT}" MCP_MANIFEST_PATH="${MCP_MANIFEST_PATH:-}" SUPPORT_OPE_SAMPLE_WORKSPACE_ROOT="${WORKSPACE_ROOT}" "${API_SCRIPT}" &
api_pid=$!

HOST="${HOST}" PORT="${UI_PORT}" API_PORT="${API_PORT}" "${UI_SCRIPT}" &
ui_pid=$!

wait -n "${api_pid}" "${ui_pid}"