#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ROOT="${PROJECT_ROOT}/.local"
STORAGE_PATH="${QDRANT_DOCKER_STORAGE_PATH:-${LOCAL_ROOT}/qdrant-server-storage}"
CONTAINER_NAME="${QDRANT_CONTAINER_NAME:-qdrant_mcp_server}"
IMAGE="${QDRANT_IMAGE:-qdrant/qdrant:v1.17.1}"

mkdir -p "${STORAGE_PATH}"

if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker is installed, but the Docker daemon is not reachable.
Start Docker Desktop or your Docker service, then rerun:

  ./scripts/local-run-qdrant.sh
EOF
  exit 1
fi

if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  if [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}")" == "true" ]]; then
    echo "Qdrant is already running at http://127.0.0.1:6333 (${CONTAINER_NAME})."
    exit 0
  fi
  docker rm "${CONTAINER_NAME}" >/dev/null
fi

docker run -d \
  --name "${CONTAINER_NAME}" \
  -p 6333:6333 \
  -p 6334:6334 \
  -v "${STORAGE_PATH}:/qdrant/storage" \
  "${IMAGE}" >/dev/null

echo "Qdrant server started at http://127.0.0.1:6333."
echo "Server storage: ${STORAGE_PATH}"
