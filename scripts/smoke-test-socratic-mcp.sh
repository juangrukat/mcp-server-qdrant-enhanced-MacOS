#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

export QDRANT_MODE=server
export QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
export EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
export COLLECTION="${SOCRATIC_COLLECTION:-socratic_circles_hybrid_v2}"
export MCP_SEARCH_TIMEOUT_SECONDS="${MCP_SEARCH_TIMEOUT_SECONDS:-120}"

curl -fsS "${QDRANT_URL}/readyz" >/dev/null
echo "ok    Qdrant server is reachable at ${QDRANT_URL}"

uv run python - <<'PY'
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from qdrant_client import QdrantClient

project_root = os.getcwd()
url = os.environ["QDRANT_URL"]
collection = os.environ["COLLECTION"]
expected_terms = ("Three Columns", "Enlargement of the Understanding", "maieutic")


def check_collection() -> None:
    client = QdrantClient(url=url)
    try:
        names = {item.name for item in client.get_collections().collections}
        if collection not in names:
            raise SystemExit(f"missing collection: {collection}")

        info = client.get_collection(collection)
        params = info.config.params
        vectors = params.vectors or {}
        sparse_vectors = params.sparse_vectors or {}
        points = info.points_count or 0

        dense_ok = False
        if isinstance(vectors, dict):
            dense_ok = any(
                "qwen3-embedding-4b" in name.lower() and getattr(vector, "size", None) == 2560
                for name, vector in vectors.items()
            )
        else:
            dense_ok = getattr(vectors, "size", None) == 2560

        sparse_ok = isinstance(sparse_vectors, dict) and "sparse-bm25" in sparse_vectors

        if not dense_ok:
            raise SystemExit("missing dense Qwen3-Embedding-4B vector of size 2560")
        if not sparse_ok:
            raise SystemExit("missing sparse-bm25 vector")
        if points <= 0:
            raise SystemExit(f"collection is empty: {collection}")

        print(f"ok    {collection} exists with {points} points, dense Qwen3-4B, and sparse-bm25")
    finally:
        client.close()


async def check_mcp_search() -> None:
    params = StdioServerParameters(
        command=os.path.join(project_root, "scripts", "run-server-mcp.sh"),
        args=[],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await asyncio.wait_for(
                session.call_tool(
                    "search_documents",
                    {
                        "collection_name": collection,
                        "query": "Adler Three Columns",
                        "mode": "hybrid",
                        "limit": 3,
                    },
                ),
                timeout=float(os.environ["MCP_SEARCH_TIMEOUT_SECONDS"]),
            )
            text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
            if not any(term in text for term in expected_terms):
                preview = text[:1000].replace("\n", " ")
                raise SystemExit(f"search returned no expected Socratic evidence. Preview: {preview}")
            print("ok    MCP hybrid search returned expected Three Columns evidence")


check_collection()
asyncio.run(check_mcp_search())
PY
