#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_PATH="${SCRIPT_DIR}/config.yml"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
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

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export SUPPORT_OPE_SAMPLE_CONFIG="${CONFIG_PATH}"
export SUPPORT_OPE_SAMPLE_HOST="${HOST}"
export SUPPORT_OPE_SAMPLE_PORT="${PORT}"
export SUPPORT_OPE_SAMPLE_MCP_MANIFEST_PATH="${MCP_MANIFEST_PATH}"
export SUPPORT_OPE_SAMPLE_CASES_ROOT="${CASES_ROOT}"
export SUPPORT_OPE_SKIP_LLM_STARTUP_PROBE="${SUPPORT_OPE_SKIP_LLM_STARTUP_PROBE:-1}"

echo "Starting sample API"
echo "  config: ${CONFIG_PATH}"
echo "  workspace root: ${CASES_ROOT}"
echo "  url:    http://${HOST}:${PORT}"
if [[ "${SUPPORT_OPE_SKIP_LLM_STARTUP_PROBE}" == "1" ]]; then
  echo "Skipping startup LLM probe for sample API. Requests that require the LLM may still fail until the backend becomes reachable."
fi

cd "${REPO_ROOT}"
exec uv run -m support_ope_agents.interfaces.api