"""
Document-grouped search.

Instead of returning raw chunk-level hits (where one long PDF can dominate
the top results with many adjacent chunks), this fetches a wider chunk pool,
groups by `metadata.document_id`, scores each document by its best chunk,
and returns one summary entry per document with its top representative chunk(s).
"""

from __future__ import annotations

from typing import Any

from qdrant_client import models

from mcp_server_qdrant.qdrant import QdrantConnector
from mcp_server_qdrant.search.reranker import RerankCandidate, Reranker


# How many raw chunks to pull before grouping. Higher = better doc coverage, slower.
_OVERFETCH_MULTIPLIER = 8
_MAX_OVERFETCH = 200


async def search_documents_grouped(
    connector: QdrantConnector,
    query: str,
    collection_name: str,
    *,
    limit: int = 10,
    chunks_per_document: int = 1,
    query_filter: models.Filter | None = None,
    min_score: float | None = None,
    sparse_provider: Any = None,
    reranker: Reranker | None = None,
) -> list[dict[str, Any]]:
    """
    Search and return distinct documents, ordered by best-chunk score.

    Each result item:
      {
        "document_id": str,
        "filename": str | None,
        "path": str | None,
        "score": float,       # best chunk score for this document
        "chunks": [           # up to chunks_per_document
          {"content": str, "score": float, "chunk_index": int, "metadata": {...}}
        ]
      }
    """
    overfetch = min(max(limit * _OVERFETCH_MULTIPLIER, limit + chunks_per_document * limit), _MAX_OVERFETCH)

    if sparse_provider is not None:
        raw = await connector.search_hybrid_rrf(
            query=query,
            collection_name=collection_name,
            sparse_provider=sparse_provider,
            limit=overfetch,
            query_filter=query_filter,
        )
    else:
        raw = await connector.hybrid_search(
            query=query,
            collection_name=collection_name,
            limit=overfetch,
            query_filter=query_filter,
            min_score=min_score,
        )

    # Optional reranking pass over the chunk pool before grouping
    if reranker is not None and raw:
        candidates = [
            RerankCandidate(
                content=entry.content,
                metadata=entry.metadata,
                first_stage_score=score,
                payload=entry,
            )
            for entry, score in raw
        ]
        reranked = await reranker.rerank(query, candidates)
        raw = [(c.payload, score) for c, score in reranked]

    # Group by document_id (fall back to path if absent for legacy data)
    groups: dict[str, dict[str, Any]] = {}
    for entry, score in raw:
        meta = entry.metadata or {}
        doc_id = meta.get("document_id") or meta.get("path") or f"_chunk_{id(entry)}"
        bucket = groups.setdefault(doc_id, {
            "document_id": doc_id,
            "filename": meta.get("filename"),
            "path": meta.get("path"),
            "content_type": meta.get("content_type"),
            "tags": meta.get("tags"),
            "modified_at": meta.get("modified_at"),
            "score": score,
            "chunks": [],
        })
        bucket["chunks"].append({
            "content": entry.content,
            "score": score,
            "chunk_index": meta.get("chunk_index"),
            "metadata": meta,
        })
        if score > bucket["score"]:
            bucket["score"] = score

    # Order each document's chunks by score desc, truncate to chunks_per_document
    for bucket in groups.values():
        bucket["chunks"].sort(key=lambda c: c["score"], reverse=True)
        bucket["chunks"] = bucket["chunks"][:chunks_per_document]

    # Order documents by best score
    ordered = sorted(groups.values(), key=lambda g: g["score"], reverse=True)
    return ordered[:limit]
