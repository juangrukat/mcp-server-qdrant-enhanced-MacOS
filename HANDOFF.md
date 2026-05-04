# Handoff: mcp-server-qdrant-enhanced

Last updated: 2026-05-03

Repo path: `/Users/kat/REPOS/mcp-server-qdrant-enhanced`

## Current State

This repo runs locally with either single-process Qdrant embedded storage or
multi-agent Qdrant server mode, plus a Rust fastembed/Candle sidecar for Qwen3
embeddings on Apple Silicon Metal.

Two-stage hybrid retrieval is now fully operational:
- Dense: Qwen3-Embedding-4B (Rust sidecar, Metal)
- Sparse: BM25 or BM42 (fastembed)
- Reranker: Qwen3-Reranker-4B (transformers, MPS) or MiniLM (fastembed ONNX)
- Multi-query: `additional_queries` parameter merges candidate pools before reranking

The active local REST API was last verified at:

- URL: `http://127.0.0.1:8765`
- Docs: `http://127.0.0.1:8765/docs`
- Active model: `Qwen/Qwen3-Embedding-4B`
- Vector size: `2560`
- Test result: `60 passed, 1 skipped`

The optional skipped test is:

- `tests/test_flagembedding_optional.py`
- Reason: `FlagEmbedding` is optional; it skips a BGE compatibility smoke test.

BGE status for launch:

- FastEmbed-listed BGE v1.5 models are selectable when returned by
  `list_embedding_models`.
- `BAAI/bge-m3` is not currently an implemented provider path.
- Existing local data is Qwen3-embedded; switching to BGE requires a new
  collection and re-ingestion so vector names and dimensions match.

## Important Runtime State

Runtime state is intentionally ignored by Git:

- `.local/`
- `storage/`
- `logs/`
- `.DS_Store`

Useful local files:

- Sidecar binary: `rust/qwen3_embedder/target/release/qwen3-embedder`
- Metrics JSONL: `.local/logs/qwen3-embeddings.jsonl`
- Embedded Qdrant storage: `.local/qdrant-storage` for one-process local mode
- Qdrant server storage: `.local/qdrant-server-storage` when using Docker server mode
- Docker image default: `qdrant/qdrant:v1.17.1`, matching the pinned
  `qdrant-client` minor version.

## Local Scripts

Use these from the repo root:

```bash
./scripts/local-install.sh
./scripts/local-run-qdrant.sh
./scripts/local-configure-hermes.py
./scripts/local-doctor.sh
./scripts/local-run-webui.sh
./scripts/local-run-mcp.sh
```

`scripts/local-env.sh` sets the local defaults:

- `QDRANT_MODE=embedded`
- `QDRANT_LOCAL_PATH=.local/qdrant-storage`
- `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B` unless overridden
- `QWEN3_DEVICE=auto`
- `QWEN3_MAX_LENGTH=1024`
- `QWEN3_DTYPE=auto`
- `QWEN3_RESPONSE_LIMIT_BYTES=67108864`
- `QDRANT_EMBEDDING_BATCH_SIZE=4`
- `QDRANT_INGEST_CHUNK_SIZE=700`
- `QDRANT_INGEST_CHUNK_OVERLAP=70`
- `QDRANT_WRITE_MAX_CONCURRENCY=1`
- `QDRANT_WRITE_QUEUE_SIZE=8`

For local book ingestion, 4B is much more practical:

```bash
EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-webui.sh
```

For launch/multi-agent use, run one Qdrant server and point REST plus MCP at
`QDRANT_URL`:

```bash
./scripts/local-run-qdrant.sh
QDRANT_MODE=server EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-webui.sh
QDRANT_MODE=server EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-mcp.sh --transport streamable-http
```

`local-run-qdrant.sh` needs a reachable Docker daemon.

Hermes should use the direct venv entrypoint, not `uv run`, because Hermes may
not inherit the same `uv` command environment as an interactive shell:

```bash
./scripts/local-configure-hermes.py
hermes mcp test qdrant
```

Do not run REST and stdio MCP against the same embedded `.local/qdrant-storage`
path at the same time. Qdrant local mode locks the path by design. Also do not
mount `.local/qdrant-storage` directly into a Qdrant Docker server; migrate
collections with `scripts/migrate-local-to-server.py` instead.
Server-mode MCP treats Qdrant as external and must not stop the Docker
container when Hermes disconnects.

Launch note: Qdrant server can accept concurrent clients, but local embedding
and ingestion still need backpressure. REST and MCP now use a bounded in-process
write queue for store/ingest operations. Default local launch runs one active
embedding/upsert write at a time with eight queued jobs. Prefer one streamable
HTTP MCP server for multi-agent use so agents share the same queue.

## Qwen3 Sidecar Notes

The Rust sidecar lives in `rust/qwen3_embedder/`.

It uses crates.io `fastembed` with features:

- `hf-hub`
- `metal`
- `ort-download-binaries-rustls-tls`
- `qwen3`

Qwen3 models route through `Qwen3RustProvider`:

- `Qwen/Qwen3-Embedding-0.6B`: 1024 dimensions
- `Qwen/Qwen3-Embedding-4B`: 2560 dimensions
- `Qwen/Qwen3-Embedding-8B`: 4096 dimensions

The Python provider adds `passage: ` to document embeddings and uses the
Qwen-style query instruction prompt in the Rust sidecar.

Important bug fixed:

- Multi-vector JSON responses exceeded Python asyncio subprocess's default
  line-read limit.
- Symptom looked like: `Separator is not found, and chunk exceed the limit`.
- Actual fix: pass a larger `limit` to `asyncio.create_subprocess_exec`.
- Config: `QWEN3_RESPONSE_LIMIT_BYTES`.

## Metrics

Every Qwen3 provider request appends JSONL to:

```text
.local/logs/qwen3-embeddings.jsonl
```

Each record includes:

- timestamp
- operation
- model
- requested device/backend
- dtype
- max length
- vector size
- text count
- char count
- embedding count
- cold start time
- request time
- total time
- success/error

These records are the basis for future ranking/performance reports.

Observed local timings:

- Qwen3 8B on Metal/F16: roughly 55-70 seconds per 4 chunks.
- Qwen3 4B on Metal/F16: roughly 2.5-4 seconds per 4 chunks after warmup.
- 4B is the practical default for local book-scale ingestion.

## Collections Verified

Current known local collections:

- `documents`
- `socratic_circles_qwen3_4b`

Verified Socratic Circles ingest:

- Source file: local Calibre PDF for Matt Copeland's *Socratic Circles*
- Collection: `socratic_circles_qwen3_4b`
- Model: `Qwen/Qwen3-Embedding-4B`
- Vector size: `2560`
- Pages: `173`
- Extracted chars: `437546`
- Chunks stored: `878`

Both endpoints were verified after fixing the query shape:

- `POST /search`
- `POST /search_documents`

## PDF Safeguards

Encrypted/password-protected PDFs are now detected in PDF preflight and fail
before extraction/embedding.

Why this matters:

- A password-protected PDF previously produced garbage-looking text from
  extractors, then wasted time embedding bad chunks.
- Now the extractor returns a clear error:
  `PDF is encrypted/password-protected and cannot be ingested without a password.`

OCR is still not implemented. Probably scanned/image-only PDFs fail early with
an OCR-needed message.

## MCP Communication

### Stdio MCP

Use this when an MCP client launches the server process:

```bash
./scripts/local-run-mcp.sh
```

or:

```bash
uv run --locked mcp-server-qdrant --transport stdio
```

### Streamable HTTP MCP

Use this when multiple local clients/agents should share one MCP server process.
For true REST+MCP concurrency, also use Qdrant server mode:

```bash
QDRANT_MODE=server uv run --locked mcp-server-qdrant --transport streamable-http --host 127.0.0.1 --port 8000
```

If auth is enabled, send:

```http
Authorization: Bearer <MCP_HTTP_AUTH_TOKEN>
```

Recommended MCP tool flow:

1. `get_server_capabilities`
2. `list_embedding_models`
3. `create_collection`
4. `bootstrap_collection_indexes`
5. `ingest_file` or `ingest_folder`
6. `search_documents`

Useful MCP tools:

- `list_collections`
- `get_collection_info`
- `list_embedding_models`
- `create_collection`
- `set_collection_embedding_model`
- `ingest_file`
- `search_documents`

Prefer `search_documents` over raw chunk search for normal use.

## REST Communication

Start REST API:

```bash
EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-webui.sh
```

Health:

```bash
curl http://127.0.0.1:8765/health
```

List models:

```bash
curl http://127.0.0.1:8765/embedding_models
```

Create a 4B collection:

```bash
curl -X POST http://127.0.0.1:8765/collections \
  -H 'Content-Type: application/json' \
  --data '{"collection_name":"my_docs_qwen3_4b","embedding_model":"Qwen/Qwen3-Embedding-4B","distance":"cosine"}'
```

Switch active REST embedding model:

```bash
curl -X POST http://127.0.0.1:8765/embedding_models/active \
  -H 'Content-Type: application/json' \
  --data '{"model_name":"Qwen/Qwen3-Embedding-4B"}'
```

Create a hybrid (dense + BM25) collection:

```bash
curl -X POST http://127.0.0.1:8765/collections/hybrid \
  -H 'Content-Type: application/json' \
  --data '{"collection_name":"my_docs_hybrid","embedding_model":"Qwen/Qwen3-Embedding-4B","distance":"cosine"}'
```

Ingest one file (auto-detects hybrid vs dense from collection config):

```bash
curl -X POST http://127.0.0.1:8765/ingest/file \
  -H 'Content-Type: application/json' \
  --data '{"file_path":"/absolute/path/to/file.pdf","collection_name":"my_docs_hybrid"}'
```

Search:

```bash
curl -X POST http://127.0.0.1:8765/search_documents \
  -H 'Content-Type: application/json' \
  --data '{"query":"your question","collection_name":"my_docs_qwen3_4b","limit":5,"chunks_per_document":4}'
```

## Key Fixes In This Session (2026-05-03, session 2)

### Session 1 (original)
- Added `Qwen/Qwen3-Embedding-4B` as a first-class supported Qwen3 model.
- Added Qwen3 response-buffer setting for large sidecar JSON responses.
- Added per-call Qwen3 metrics logging.
- Added password-protected PDF detection.
- Reduced default ingest chunk size to 700 chars with 70 overlap.
- Reduced default embedding batch size to 4.
- Made `batch_store` upsert incrementally per embedding batch.
- Fixed Qdrant local query shape.

### Session 2
- **Implemented `QwenReranker`**: Qwen3-Reranker-{0.6B,4B,8B} via `transformers`
  `AutoModelForCausalLM`. CausalLM yes/no logit scoring. Auto-selects MPS on
  Apple Silicon. Lazy-loads on first use. Configurable batch size and instruction.
- **BM42 support**: `QDRANT_SPARSE_MODEL=Qdrant/bm42-all-minilm-l6-v2-attentions`
  as an alternative to BM25.
- **Multi-query retrieval** (`additional_queries` param): run parallel subqueries,
  merge+dedup by content hash, rerank all unique candidates against the primary
  query. This is the most important fix for recall regression when query compression
  drops rare/discriminative terms.
- **Diversity pass**: after reranking, limit ≤2 chunks per page/section to prevent
  same-region clustering in the answer context.
- **Configurable candidate pool**: `prefetch_limit`, `rerank_top_k`,
  `QDRANT_RERANKER_INSTRUCTION` env var, per-request instruction override.
- **Optional `[reranking]` extras**: `torch>=2.0`, `transformers>=4.51`,
  `accelerate>=0.26` via `uv pip install 'mcp-server-qdrant[reranking]'`.
- Rewrote README with Mermaid architecture diagram, calibration guide, A/B
  progression, and multi-query guidance.

### Session 3 (2026-05-04)
- **Hybrid fallback observability**: `_retrieval_warnings` ContextVar; sparse fallback
  warnings surface in MCP response envelope `observability.warnings`. REST API also
  collects warnings and returns them as `response.warnings`.
- **Hybrid fallback tests** (`tests/test_hybrid_fallback.py`): 6 tests covering RRF
  exception, empty-RRF, ContextVar propagation, both-fail graceful return.
- **REST API reranker support**: `SearchDocumentsRequest` now accepts `reranker_model`
  and `reranker_instruction`. The `/search_documents` endpoint builds and applies the
  reranker the same way the MCP tool does.
- **`batch_store_hybrid` batching fix**: was sending all entries to embedder at once
  (OOM on 878-chunk books). Now iterates in `QDRANT_EMBEDDING_BATCH_SIZE` batches,
  matches `batch_store` behavior.
- **PDF whitespace normalization** (`build_chunks`): `re.sub(r"[^\S\n]+", " ", text)`
  collapses PDF column-layout double-spaces before chunking. Fixes phrase-match failures
  like `"Critical  reading,  critical  thinking"` → `"Critical reading, critical thinking"`.
- **Retrieval diagnostic script** (`scripts/diagnostic_retrieval.py`): runs 5 configs
  (dense, hybrid, hybrid+MiniLM, multi-query, multi-query+MiniLM) against gold phrases,
  writes `test-1/summary.md`, per-config chunk tables, and JSON results.
- **`socratic_circles_hybrid` collection**: dense (Qwen3-4B, 2560d) + sparse (BM25)
  hybrid collection; re-ingested Socratic Circles with whitespace normalization applied.
- **`POST /collections/hybrid` REST endpoint**: new endpoint that creates a collection
  with both dense and sparse (BM25) vector slots in one call. Accepts same fields as
  `POST /collections` plus optional `sparse_model` (default `Qdrant/bm25`).
- **Auto-routing ingest** (`/ingest/file`, `/ingest/folder`): both endpoints now call
  `get_sparse_vector_name()` on the target collection. If sparse vectors are present
  (hybrid collection), ingest automatically uses `batch_store_hybrid`; otherwise uses
  `batch_store`. No request-level parameter needed.
- **`get_sparse_vector_name()` helper** (`qdrant.py`): returns first sparse vector name
  or None. Used by ingest routing and tested in 3 new unit tests
  (`test_hybrid_fallback.py`).
- **REST API route tests** (`tests/test_webui_api_routes.py`): 3 new tests verifying
  `POST /collections/hybrid` route exists, calls `create_hybrid_collection`, and is
  not swallowed by `DELETE /collections/{name}`.
- **Gold phrase correction** (`diagnostic_retrieval.py`): G4/G8 were from Adler (1982)
  directly, not from Copeland's 2005 book. Corrected: G4→"raise their minds up from a
  state of understanding", G8→"Wednesday Revolution". Confirmed via page-by-page
  pdfminer scan.
- **`socratic_circles_hybrid_v2` collection**: fresh hybrid collection re-ingested with
  whitespace normalization applied from the start. Corrects the double-space embedding
  artifacts in the original `socratic_circles_hybrid`.
- **Diagnostic findings** (`test-1/diagnosis.md`):
  - Multi-query is the largest single improvement (G5/G6 rank 2 vs never found)
  - MiniLM reranker hurts this academic domain (G5/G6 drop rank 2→48); use Qwen3-Reranker
  - `socratic_circles_qwen3_4b` was dense-only; hybrid tests blocked until now
  - G4/G8 invalid gold phrases — "not the possession of knowledge" and "desire and
    capacity to learn" are from Adler (1982) directly, NOT quoted in Copeland's book.
    Replaced with valid phrases: G4→"raise their minds up from a state of understanding"
    (pgs 18/122), G8→"Wednesday Revolution" (pg 124). This is a gold-set correction,
    not a PDF extraction failure.

## Collections Verified

Current known local collections:

- `documents`
- `socratic_circles_qwen3_4b` — dense-only (Qwen3-4B), 878 chunks, original ingest
- `socratic_circles_hybrid` — dense (Qwen3-4B) + BM25 sparse, 878 chunks,
  double-space artifacts in stored text (normalization applied mid-ingest)
- `socratic_circles_hybrid_v2` — dense (Qwen3-4B) + BM25 sparse, fully
  whitespace-normalized; re-ingested with corrected `build_chunks`; use this for
  v2 diagnostic runs and future production use

## Known Caveats

- G4/G8 gold phrases in the original diagnostic were wrong — those phrases are from
  Adler's 1982 source book, not from Copeland's 2005 book which is the PDF. Confirmed
  via page-by-page pdfminer scan (zero matches). Gold phrases corrected in
  `scripts/diagnostic_retrieval.py`. Future v2 diagnostic runs use valid gold phrases.
- Qwen3 8B is too slow for book-scale local ingestion on this machine unless
  quality needs justify hours of runtime.
- Embedded Qdrant storage is single-process. Multi-agent launch should use
  `QDRANT_MODE=server`/`QDRANT_URL=http://127.0.0.1:6333`.
- The REST `/embedding_models/active` switch is process-global for REST. For MCP,
  prefer per-collection model settings and per-request model overrides.
- Existing staged files include user-modified `README.md`; do not assume all
  staged changes are yours.

## Verification Commands

```bash
uv run --locked pytest
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/collections/socratic_circles_qwen3_4b
```

Expected latest full test result:

```text
74 passed, 1 skipped
```

(71 + 3 new in `tests/test_webui_api_routes.py`:
`test_post_collections_hybrid_route_exists`,
`test_post_collections_hybrid_calls_create_hybrid_collection`,
`test_collections_hybrid_route_not_swallowed_by_parameterized_route`)
