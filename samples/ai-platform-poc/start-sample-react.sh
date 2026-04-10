#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5173}"
API_PORT="${API_PORT:-8000}"
NPM_BIN="${NPM_BIN:-$(command -v npm || true)}"

if [[ -z "${NPM_BIN}" ]]; then
  echo "npm が見つかりません。NPM_BIN で npm 実行ファイルを指定してください。" >&2
  exit 1
fi

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "frontend dependencies are missing. Running npm install..."
  (
    cd "${FRONTEND_DIR}"
    "${NPM_BIN}" install
  )
fi

echo "Starting sample React frontend"
echo "  frontend: ${FRONTEND_DIR}"
echo "  url:      http://${HOST}:${PORT}"
echo "  api:      http://${HOST}:${API_PORT}"

cd "${FRONTEND_DIR}"
VITE_API_PROXY_TARGET="http://${HOST}:${API_PORT}" exec "${NPM_BIN}" run dev -- --host "${HOST}" --port "${PORT}"