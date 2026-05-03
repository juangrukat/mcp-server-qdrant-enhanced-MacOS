#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

LOCAL_ROOT="${PROJECT_ROOT}/.local"
SERVER_STORAGE="${QDRANT_DOCKER_STORAGE_PATH:-${LOCAL_ROOT}/qdrant-server-storage}"
EMBEDDED_STORAGE="${QDRANT_LOCAL_PATH:-${LOCAL_ROOT}/qdrant-storage}"
CONTAINER_NAME="${QDRANT_CONTAINER_NAME:-qdrant_mcp_server}"

STOP_DOCKER=false
REMOVE_DOCKER=false
WIPE=false
WIPE_EMBEDDED=false

usage() {
  cat <<EOF
Usage: ./scripts/reset-server-qdrant.sh [options]

Stops local MCP/REST/embedder processes. Docker and data are preserved unless
explicit flags are supplied.

Options:
  --stop-docker      Stop the ${CONTAINER_NAME} container.
  --remove-docker    Stop and remove the ${CONTAINER_NAME} container.
  --wipe             Delete ${SERVER_STORAGE}.
  --wipe-embedded    Delete ${EMBEDDED_STORAGE}.
  -h, --help         Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop-docker)
      STOP_DOCKER=true
      shift
      ;;
    --remove-docker)
      STOP_DOCKER=true
      REMOVE_DOCKER=true
      shift
      ;;
    --wipe)
      WIPE=true
      shift
      ;;
    --wipe-embedded)
      WIPE_EMBEDDED=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

stop_matching() {
  local pattern="$1"
  local label="$2"
  local pids
  pids="$(pgrep -f "${pattern}" || true)"
  if [[ -z "${pids}" ]]; then
    echo "ok    No ${label} processes found."
    return
  fi

  echo "Stopping ${label} processes: ${pids//$'\n'/ }"
  kill ${pids} 2>/dev/null || true
  sleep 2

  pids="$(pgrep -f "${pattern}" || true)"
  if [[ -n "${pids}" ]]; then
    echo "Force stopping ${label} processes: ${pids//$'\n'/ }"
    kill -9 ${pids} 2>/dev/null || true
  fi
}

stop_matching "${PROJECT_ROOT}.*/(local-run-mcp.sh|run-server-mcp.sh|\\.venv/bin/mcp-server-qdrant)( |$)|uv run --locked mcp-server-qdrant( |$)" "MCP"
stop_matching "${PROJECT_ROOT}.*/local-run-webui.sh|uvicorn .*mcp_server_qdrant.webui|mcp_server_qdrant.webui|mcp-server-qdrant-webui" "REST"
stop_matching "${PROJECT_ROOT}.*/qwen3-embedder" "Qwen3 embedder"

if [[ "${STOP_DOCKER}" == "true" ]]; then
  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    if [[ "${REMOVE_DOCKER}" == "true" ]]; then
      docker rm -f "${CONTAINER_NAME}" >/dev/null
      echo "ok    Removed Docker Qdrant container ${CONTAINER_NAME}."
    else
      docker stop "${CONTAINER_NAME}" >/dev/null
      echo "ok    Stopped Docker Qdrant container ${CONTAINER_NAME}."
    fi
  else
    echo "ok    Docker Qdrant container ${CONTAINER_NAME} does not exist."
  fi
else
  echo "ok    Docker Qdrant container left unchanged."
fi

if [[ "${WIPE}" == "true" ]]; then
  rm -rf "${SERVER_STORAGE}"
  echo "ok    Deleted server storage: ${SERVER_STORAGE}"
else
  echo "ok    Server storage left unchanged: ${SERVER_STORAGE}"
fi

if [[ "${WIPE_EMBEDDED}" == "true" ]]; then
  rm -rf "${EMBEDDED_STORAGE}"
  echo "ok    Deleted embedded storage: ${EMBEDDED_STORAGE}"
else
  echo "ok    Embedded storage left unchanged: ${EMBEDDED_STORAGE}"
fi
