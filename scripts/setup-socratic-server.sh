#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

COLLECTION="${SOCRATIC_COLLECTION:-socratic_circles_hybrid_v2}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
FORCE=false

usage() {
  cat <<EOF
Usage: ./scripts/setup-socratic-server.sh [--force]

Checks the Socratic Circles example/test collection without running ingestion.

Options:
  --force   Allow recreate/re-ingest instructions even when points already exist.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=true
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

print_ingest_commands() {
  cat <<EOF

Collection '${COLLECTION}' is missing or empty.
Start REST in another terminal if you want to create/ingest through the REST API:

  QDRANT_MODE=server QDRANT_URL=${QDRANT_URL} EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-webui.sh

Then create the hybrid collection:

  curl -X POST http://127.0.0.1:8765/collections/hybrid \\
    -H 'Content-Type: application/json' \\
    --data '{"collection_name":"${COLLECTION}","embedding_model":"Qwen/Qwen3-Embedding-4B","distance":"cosine"}'

Then ingest the source PDF:

  curl -X POST http://127.0.0.1:8765/ingest/file \\
    -H 'Content-Type: application/json' \\
    --data '{"file_path":"/absolute/path/to/socratic-circles.pdf","collection_name":"${COLLECTION}"}'

This script does not run long ingestion automatically.
EOF
}

"${PROJECT_ROOT}/scripts/local-run-qdrant.sh"

if ! curl -fsS "${QDRANT_URL}/readyz" >/dev/null; then
  echo "Qdrant server is not reachable at ${QDRANT_URL}." >&2
  exit 1
fi

set +e
CHECK_OUTPUT="$(
  QDRANT_URL="${QDRANT_URL}" COLLECTION="${COLLECTION}" uv run python - <<'PY'
import os
import sys

from qdrant_client import QdrantClient

url = os.environ["QDRANT_URL"]
collection = os.environ["COLLECTION"]
client = QdrantClient(url=url)

try:
    names = {item.name for item in client.get_collections().collections}
    if collection not in names:
        print(f"missing collection: {collection}")
        sys.exit(10)

    info = client.get_collection(collection)
    params = info.config.params
    vectors = params.vectors or {}
    sparse_vectors = params.sparse_vectors or {}
    points = info.points_count or 0

    dense_ok = False
    dense_details = []
    if isinstance(vectors, dict):
        for name, vector in vectors.items():
            size = getattr(vector, "size", None)
            dense_details.append(f"{name}:{size}")
            if "qwen3-embedding-4b" in name.lower() and size == 2560:
                dense_ok = True
    else:
        size = getattr(vectors, "size", None)
        dense_details.append(f"default:{size}")
        dense_ok = size == 2560

    sparse_ok = isinstance(sparse_vectors, dict) and "sparse-bm25" in sparse_vectors

    print(f"collection={collection}")
    print(f"points={points}")
    print(f"dense_vectors={', '.join(dense_details) or 'none'}")
    print(f"sparse_vectors={', '.join(sparse_vectors.keys()) if isinstance(sparse_vectors, dict) else 'none'}")

    if not dense_ok:
        print("invalid dense vector: expected Qwen3-Embedding-4B size 2560")
        sys.exit(11)
    if not sparse_ok:
        print("invalid sparse vector: expected sparse-bm25")
        sys.exit(12)
    if points <= 0:
        print("empty collection")
        sys.exit(13)
finally:
    client.close()
PY
)"
CHECK_STATUS=$?
set -e

printf '%s\n' "${CHECK_OUTPUT}"

case "${CHECK_STATUS}" in
  0)
    echo "Ready: ${COLLECTION} is populated and matches the Socratic example/test schema."
    ;;
  10|13)
    if [[ "${FORCE}" == "false" ]]; then
      print_ingest_commands
      exit 1
    fi
    echo "--force supplied; recreate/re-ingest instructions follow."
    print_ingest_commands
    ;;
  *)
    echo "Collection schema check failed. Fix the collection before using MCP." >&2
    exit "${CHECK_STATUS}"
    ;;
esac
