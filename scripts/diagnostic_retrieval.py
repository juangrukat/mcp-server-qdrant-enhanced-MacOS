#!/usr/bin/env python3
"""
Retrieval quality diagnostic.

Runs the same query through multiple pipeline configurations and checks
which gold chunks survive each stage.

Usage:
    uv run --locked python scripts/diagnostic_retrieval.py \
        --collection socratic_circles_qwen3_4b \
        --out test-1

Requirements:
    - Embedded Qdrant storage OR QDRANT_MODE=server with running Qdrant
    - Qwen3 sidecar running (QWEN3_SIDECAR_URL) OR sidecar binary in rust/
    - Do NOT run this while the REST server is using the same embedded storage
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Gold phrases ──────────────────────────────────────────────────────────────
GOLD_PHRASES: dict[str, str] = {
    # G1: present in chunk 21 — normalized ingest collapses PDF double-spaces
    "G1_benefits_list": "Critical reading, critical thinking",
    # G2: actual phrase in chunk 679 is "expand their learning"
    "G2_expanded_learning": "expand their learning",
    "G3_adler_definition": "analyze their own minds",
    # G4: Adler quote present on pages 18+122 of Copeland PDF.
    # NOTE: "not the possession of knowledge" is from Adler (1982) directly,
    # NOT quoted in Copeland's book. That phrase was replaced with the actual
    # Adler quote Copeland uses: "raise their minds up from a state of understanding".
    "G4_raise_their_minds": "raise their minds up from a state of understanding",
    "G5_enlargement": "Enlargement of the Understanding",
    "G6_maieutic": "maieutic",
    "G7_three_columns": "Three Columns",
    # G8: "desire and capacity to learn" is also from Adler (1982) directly, not in Copeland.
    # Replaced with Adler's "Wednesday Revolution" concept which IS in Copeland pp.124, 167.
    "G8_wednesday_revolution": "Wednesday Revolution",
    "G9_draw_out": "draw out ideas",
    "G10_ownership": "ownership",
}

# ── Primary query and additional subqueries ───────────────────────────────────
PRIMARY_QUERY = (
    "Does Copeland say students gain more knowledge or understanding through "
    "Socratic circles? What does Adler contribute?"
)

ADDITIONAL_QUERIES = [
    "Adler Three Columns Enlargement of the Understanding maieutic teaching",
    "critical reading critical thinking vocabulary student ownership empowerment",
    "Socratic circles expand students learning idea theme subject",
    "Adler raise minds understanding Wednesday Revolution Paideia Proposal",
]

# ── Retrieval configurations to test ─────────────────────────────────────────
# NOTE: chunks_per_document is set high (80) for diagnostics because the
# Socratic Circles collection is a single-document collection — all 878 chunks
# share one document_id.  In production use 4–6.
_DIAG_CPD = 80

CONFIGURATIONS: list[dict[str, Any]] = [
    {
        "name": "A_dense_only",
        "label": "Dense only (Qwen3-Embedding-4B)",
        "mode": "dense",
        "limit": 10,
        "chunks_per_document": _DIAG_CPD,
        "additional_queries": None,
        "reranker_model": None,
        "prefetch_limit": 80,
        "description": "Pure dense vector retrieval, no sparse, no reranking.",
    },
    {
        "name": "B_hybrid_no_rerank",
        "label": "Hybrid RRF (dense + BM25), no reranker",
        "mode": "hybrid",
        "limit": 10,
        "chunks_per_document": _DIAG_CPD,
        "additional_queries": None,
        "reranker_model": None,
        "prefetch_limit": 80,
        "description": "Dense + BM25 fused with RRF. Falls back to dense if no sparse slot.",
    },
    {
        "name": "C_hybrid_minilm_rerank",
        "label": "Hybrid + MiniLM reranker",
        "mode": "rerank",
        "limit": 10,
        "chunks_per_document": _DIAG_CPD,
        "additional_queries": None,
        "reranker_model": "Xenova/ms-marco-MiniLM-L-6-v2",
        "prefetch_limit": 100,
        "description": "Hybrid RRF candidate pool reranked by MiniLM cross-encoder.",
    },
    {
        "name": "D_hybrid_multiquery_no_rerank",
        "label": "Hybrid RRF + multi-query expansion, no reranker",
        "mode": "hybrid",
        "limit": 10,
        "chunks_per_document": _DIAG_CPD,
        "additional_queries": ADDITIONAL_QUERIES,
        "reranker_model": None,
        "prefetch_limit": 80,
        "description": "Multi-query: 4 subqueries merged before grouping. Preserves rare terms.",
    },
    {
        "name": "E_hybrid_multiquery_minilm",
        "label": "Hybrid + multi-query + MiniLM reranker",
        "mode": "rerank",
        "limit": 10,
        "chunks_per_document": _DIAG_CPD,
        "additional_queries": ADDITIONAL_QUERIES,
        "reranker_model": "Xenova/ms-marco-MiniLM-L-6-v2",
        "prefetch_limit": 120,
        "description": "Best-effort config: multi-query recall + MiniLM reranking.",
    },
]

# Try Qwen3 reranker if torch + transformers are available
try:
    import torch  # noqa: F401
    import transformers  # noqa: F401
    CONFIGURATIONS.append({
        "name": "F_hybrid_multiquery_qwen3",
        "label": "Hybrid + multi-query + Qwen3-Reranker-4B",
        "mode": "rerank",
        "limit": 20,
        "chunks_per_document": 4,
        "additional_queries": ADDITIONAL_QUERIES,
        "reranker_model": "Qwen/Qwen3-Reranker-4B",
        "prefetch_limit": 120,
        "description": "Full pipeline: multi-query recall + Qwen3 CausalLM reranker.",
    })
except ImportError:
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_gold(content: str) -> list[str]:
    """Return list of gold phrase keys found in content (case-insensitive, space-insensitive).

    Normalizes runs of whitespace before matching so that PDF double-space artifacts
    (e.g. 'Critical  reading,  critical  thinking') match the single-space gold phrase.
    """
    content_norm = re.sub(r"\s+", " ", content).lower()
    return [
        k for k, phrase in GOLD_PHRASES.items()
        if re.sub(r"\s+", " ", phrase).lower() in content_norm
    ]


def _rank_gold_in_chunks(all_chunks: list[dict]) -> dict[str, int | None]:
    """
    Given a flat list of chunks (each with 'content'), find the first rank
    (1-based) at which each gold phrase appears.

    Uses whitespace-insensitive matching (collapses runs of spaces/newlines)
    so PDF double-space artifacts don't cause false misses.
    """
    ranks: dict[str, int | None] = {k: None for k in GOLD_PHRASES}
    for idx, chunk in enumerate(all_chunks, start=1):
        content_norm = re.sub(r"\s+", " ", chunk.get("content", "")).lower()
        for key, phrase in GOLD_PHRASES.items():
            if ranks[key] is None:
                phrase_norm = re.sub(r"\s+", " ", phrase).lower()
                if phrase_norm in content_norm:
                    ranks[key] = idx
    return ranks


def _flatten_chunks(docs: list[dict]) -> list[dict]:
    """Flatten document groups into a single ordered chunk list."""
    flat: list[dict] = []
    for doc in docs:
        for chunk in doc.get("chunks", []):
            flat.append({
                "content": chunk.get("content", ""),
                "score": chunk.get("score"),
                "chunk_index": chunk.get("chunk_index"),
                "document_id": doc.get("document_id"),
                "filename": doc.get("filename"),
                "doc_score": doc.get("score"),
                "gold_hits": _check_gold(chunk.get("content", "")),
            })
    return flat


async def run_configuration(
    connector,
    sparse_provider_cls,
    embedding_provider,
    cfg: dict,
    collection_name: str,
) -> dict:
    """Run one retrieval configuration and return structured results."""
    from mcp_server_qdrant.search.document_search import search_documents_grouped
    from mcp_server_qdrant.search.retrieval_mode import RetrievalMode
    from mcp_server_qdrant.search.reranker import build_default_reranker
    from mcp_server_qdrant.qdrant import _retrieval_warnings

    rmode = RetrievalMode.parse(cfg["mode"])
    use_sparse = rmode in (RetrievalMode.HYBRID, RetrievalMode.RERANK)
    sparse_provider = sparse_provider_cls() if use_sparse else None

    reranker = None
    if rmode == RetrievalMode.RERANK and cfg.get("reranker_model"):
        reranker = build_default_reranker(cfg["reranker_model"])

    warnings_sink: list[str] = []
    _retrieval_warnings.set(warnings_sink)

    start = asyncio.get_event_loop().time()
    docs = await search_documents_grouped(
        connector,
        query=PRIMARY_QUERY,
        collection_name=collection_name,
        limit=cfg["limit"],
        chunks_per_document=cfg["chunks_per_document"],
        sparse_provider=sparse_provider,
        reranker=reranker,
        embedding_provider=embedding_provider,
        prefetch_limit=cfg.get("prefetch_limit"),
        additional_queries=cfg.get("additional_queries"),
    )
    elapsed_ms = round((asyncio.get_event_loop().time() - start) * 1000)

    flat = _flatten_chunks(docs)
    gold_ranks = _rank_gold_in_chunks(flat)

    return {
        "config": cfg["name"],
        "label": cfg["label"],
        "description": cfg["description"],
        "elapsed_ms": elapsed_ms,
        "documents_returned": len(docs),
        "chunks_total": len(flat),
        "warnings": warnings_sink or [],
        "gold_ranks": gold_ranks,
        "chunks": flat[:80],   # top 80 for inspection
        "documents": docs,
    }


def _rank_table(all_results: list[dict]) -> str:
    """Render a markdown table comparing gold rank across configs."""
    header_cols = ["Gold Phrase", "Phrase"] + [r["config"] for r in all_results]
    rows = []
    for key, phrase in GOLD_PHRASES.items():
        cells = [f"**{key}**", phrase]
        for r in all_results:
            rank = r["gold_ranks"].get(key)
            cells.append(str(rank) if rank is not None else "—")
        rows.append(cells)

    def fmt_row(cells):
        return "| " + " | ".join(cells) + " |"

    separator = "| " + " | ".join(["---"] * len(header_cols)) + " |"
    lines = [fmt_row(header_cols), separator] + [fmt_row(r) for r in rows]
    return "\n".join(lines)


def _score_table_for_config(result: dict) -> str:
    """Render a table of top chunks with scores and gold hits for one config."""
    header = "| Rank | Score | Doc Score | Filename | chunk_idx | Gold hits | Preview |"
    sep    = "| ---: | ----: | --------: | -------- | --------: | --------- | ------- |"
    rows = [header, sep]
    for i, c in enumerate(result["chunks"][:30], start=1):
        preview = (c["content"][:80]).replace("\n", " ").replace("|", "\\|")
        gold = ", ".join(c["gold_hits"]) if c["gold_hits"] else ""
        score = f"{c['score']:.4f}" if c["score"] is not None else "n/a"
        doc_score = f"{c['doc_score']:.4f}" if c["doc_score"] is not None else "n/a"
        fname = (c.get("filename") or "")[:25]
        rows.append(
            f"| {i} | {score} | {doc_score} | {fname} | {c['chunk_index']} | {gold} | {preview} |"
        )
    return "\n".join(rows)


def _write_summary(all_results: list[dict], out_dir: Path, collection: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        f"# Retrieval Diagnostic — {collection}",
        f"",
        f"**Run at:** {now}",
        f"**Primary query:** {PRIMARY_QUERY}",
        f"",
        f"## Additional queries (multi-query configs)",
        "",
    ]
    for i, q in enumerate(ADDITIONAL_QUERIES, 1):
        lines.append(f"{i}. {q}")

    lines += [
        "",
        "## Gold Phrase Rank Table",
        "",
        "First rank (1-based chunk position across all returned docs) at which each gold phrase appears.",
        "'—' means not found in returned results.",
        "",
        _rank_table(all_results),
        "",
        "## Per-Configuration Summary",
        "",
    ]

    for r in all_results:
        lines += [
            f"### {r['config']}: {r['label']}",
            f"",
            f"**Description:** {r['description']}",
            f"**Elapsed:** {r['elapsed_ms']} ms | "
            f"**Docs returned:** {r['documents_returned']} | "
            f"**Total chunks:** {r['chunks_total']}",
        ]
        if r["warnings"]:
            lines.append("")
            for w in r["warnings"]:
                lines.append(f"> ⚠️ {w}")
        found = [k for k, v in r["gold_ranks"].items() if v is not None]
        missing = [k for k, v in r["gold_ranks"].items() if v is None]
        lines += [
            f"",
            f"**Gold found ({len(found)}/{len(GOLD_PHRASES)}):** {', '.join(found) or '—'}",
            f"**Gold missing:** {', '.join(missing) or '—'}",
            "",
        ]

    summary_path = out_dir / "summary.md"
    summary_path.write_text("\n".join(lines))
    print(f"  ✓ {summary_path}")


def _write_chunk_tables(all_results: list[dict], out_dir: Path) -> None:
    for r in all_results:
        path = out_dir / f"{r['config']}_chunks.md"
        lines = [
            f"# {r['config']}: {r['label']}",
            "",
            f"**Description:** {r['description']}",
            f"**Elapsed:** {r['elapsed_ms']} ms",
            f"**Gold ranks:** {r['gold_ranks']}",
            "",
            "## Top 30 chunks",
            "",
            _score_table_for_config(r),
            "",
            "## Gold phrase details",
            "",
        ]
        for key, phrase in GOLD_PHRASES.items():
            rank = r["gold_ranks"].get(key)
            lines.append(f"- **{key}** (`{phrase}`): rank **{rank if rank is not None else '—'}**")

        path.write_text("\n".join(lines))
        print(f"  ✓ {path}")


def _write_json(all_results: list[dict], out_dir: Path) -> None:
    for r in all_results:
        path = out_dir / f"{r['config']}.json"
        # Strip full chunk text to keep files manageable; keep first 300 chars
        result_copy = dict(r)
        result_copy["chunks"] = [
            {**c, "content": c["content"][:300]} for c in r["chunks"]
        ]
        result_copy["documents"] = []  # raw docs omitted in JSON (chunks table is enough)
        path.write_text(json.dumps(result_copy, indent=2, default=str))
        print(f"  ✓ {path}")


async def main(collection: str, out: str, configs: list[str] | None = None) -> None:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Bootstrap connector ────────────────────────────────────────────────
    # Respect the same env vars as the main app.
    os.environ.setdefault("QDRANT_MODE", "embedded")
    os.environ.setdefault("QDRANT_LOCAL_PATH", ".local/qdrant-storage")
    # Default to 4B — matches the socratic_circles_qwen3_4b collection.
    # Override with EMBEDDING_MODEL env var if your collection uses a different model.
    os.environ.setdefault("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B")

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    from mcp_server_qdrant.settings import QdrantSettings, EmbeddingProviderSettings
    from mcp_server_qdrant.embedding_manager import EnhancedEmbeddingModelManager
    from mcp_server_qdrant.qdrant import QdrantConnector
    from mcp_server_qdrant.embeddings.sparse import SparseEmbeddingProvider

    qdrant_settings = QdrantSettings()
    emb_settings = EmbeddingProviderSettings()
    emb_manager = EnhancedEmbeddingModelManager(emb_settings)
    emb_provider = emb_manager.get_default_provider()

    connector = QdrantConnector(
        qdrant_url=qdrant_settings.location,
        qdrant_api_key=qdrant_settings.api_key,
        collection_name=qdrant_settings.collection_name,
        embedding_provider=emb_provider,
        qdrant_local_path=qdrant_settings.local_path,
    )

    sparse_model = qdrant_settings.sparse_model
    def make_sparse():
        return SparseEmbeddingProvider(sparse_model)

    # ── Verify collection exists ───────────────────────────────────────────
    collections = await connector.get_collection_names()
    if collection not in collections:
        print(f"ERROR: Collection '{collection}' not found. Available: {collections}")
        return

    print(f"\n{'='*60}")
    print(f"Diagnostic: {collection}")
    print(f"Query: {PRIMARY_QUERY[:70]}...")
    print(f"Gold phrases: {len(GOLD_PHRASES)}")
    print(f"Output: {out_dir.resolve()}")
    print(f"{'='*60}\n")

    # ── Run configurations ─────────────────────────────────────────────────
    active_cfgs = [
        c for c in CONFIGURATIONS
        if configs is None or c["name"] in configs
    ]

    all_results = []
    for cfg in active_cfgs:
        print(f"▶ Running {cfg['name']}: {cfg['label']} ...")
        try:
            result = await run_configuration(
                connector, make_sparse, emb_provider, cfg, collection
            )
            found = sum(1 for v in result["gold_ranks"].values() if v is not None)
            print(f"  → {result['elapsed_ms']} ms | "
                  f"{result['documents_returned']} docs | "
                  f"gold found: {found}/{len(GOLD_PHRASES)}")
            if result["warnings"]:
                for w in result["warnings"]:
                    print(f"  ⚠ {w[:100]}")
            all_results.append(result)
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()

    if not all_results:
        print("No results — nothing to save.")
        return

    # ── Write outputs ──────────────────────────────────────────────────────
    print(f"\nWriting results to {out_dir.resolve()} ...")
    _write_summary(all_results, out_dir, collection)
    _write_chunk_tables(all_results, out_dir)
    _write_json(all_results, out_dir)

    # Print rank table to stdout
    print(f"\n{'='*60}")
    print("GOLD PHRASE RANK TABLE")
    print(f"{'='*60}")
    print(_rank_table(all_results))
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieval quality diagnostic")
    parser.add_argument(
        "--collection",
        default="socratic_circles_qwen3_4b",
        help="Qdrant collection name",
    )
    parser.add_argument(
        "--out",
        default="test-1",
        help="Output directory",
    )
    parser.add_argument(
        "--configs",
        nargs="*",
        help="Run only specific config names (e.g. A_dense_only B_hybrid_no_rerank)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.collection, args.out, args.configs))
