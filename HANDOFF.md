# Handoff: mcp-server-qdrant-enhanced

Last updated: 2026-05-03

Repo path: `/Users/kat/REPOS/mcp-server-qdrant-enhanced`

## Current State

This repo runs locally with either single-process Qdrant embedded storage or
multi-agent Qdrant server mode, plus a Rust fastembed/Candle sidecar for Qwen3
embeddings on Apple Silicon Metal.

The active local REST API was last verified at:

- URL: `http://127.0.0.1:8765`
- Docs: `http://127.0.0.1:8765/docs`
- Active model: `Qwen/Qwen3-Embedding-4B`
- Vector size: `2560`
- Test result: `44 passed, 1 skipped`

The optional skipped test is:

- `tests/test_flagembedding_optional.py`
- Reason: `FlagEmbedding` is optional; it skips a BGE compatibility smoke test.

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

Ingest one file:

```bash
curl -X POST http://127.0.0.1:8765/ingest/file \
  -H 'Content-Type: application/json' \
  --data '{"file_path":"/absolute/path/to/file.pdf","collection_name":"my_docs_qwen3_4b"}'
```

Search:

```bash
curl -X POST http://127.0.0.1:8765/search_documents \
  -H 'Content-Type: application/json' \
  --data '{"query":"your question","collection_name":"my_docs_qwen3_4b","limit":5,"chunks_per_document":2}'
```

## Key Fixes In This Session

- Added `Qwen/Qwen3-Embedding-4B` as a first-class supported Qwen3 model.
- Added Qwen3 response-buffer setting for large sidecar JSON responses.
- Added per-call Qwen3 metrics logging.
- Added password-protected PDF detection.
- Reduced default ingest chunk size to 700 chars with 70 overlap.
- Reduced default embedding batch size to 4.
- Made `batch_store` upsert incrementally per embedding batch.
- Fixed Qdrant local query shape:
  - old: `query=(vector_name, vector)`
  - new: `query=vector, using=vector_name`

## Known Caveats

- PDF extraction can still produce ugly chunks, especially letter-spaced pages
  or copyright/rubric pages. Retrieval works, but a future text-cleaning pass
  would improve quality.
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
44 passed, 1 skipped
```
