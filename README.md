# mcp-server-qdrant-enhanced

A production-minded Python server that extends the Qdrant Model Context Protocol
workflow with document ingestion, document-level semantic search, hybrid
dense/sparse retrieval, dynamic FastEmbed model selection, MCP tool profiles,
secure streamable HTTP transport, and a FastAPI interface for non-MCP clients.

This project began as an enhancement of the base Qdrant MCP server, but has
grown into a broader local AI retrieval layer for desktop agents, MCP clients,
and API consumers. It focuses on practical retrieval workflows: ingesting files,
preserving useful metadata, searching by distinct documents instead of raw
chunks, exposing a configurable tool surface, and supporting safer multi-agent
usage over HTTP.

## What changed from the original

Compared with the original Qdrant MCP server, this version adds:

- File and folder ingestion for Markdown, text, structured data, PDFs, DOCX,
  and common code/config formats.
- Document-grouped retrieval through `search_documents`, which returns distinct
  documents ranked by their strongest chunks.
- Hybrid dense + sparse search using FastEmbed dense models and Qdrant BM25
  sparse vectors.
- Optional rerank and late-interaction search modes for more advanced retrieval.
- Dynamic per-collection embedding model selection.
- MCP tool profiles (`minimal`, `canonical`, `full`) to control how much tool
  surface a client sees.
- Streamable HTTP support with loopback binding, Origin validation, and optional
  Bearer token auth.
- A FastAPI application exposing the same Qdrant connector and ingestion
  pipeline to non-MCP clients.
- Structured response envelopes for priority tools.
- Report/apply gating for expensive or destructive actions such as folder
  ingestion and collection deletion.
- macOS-aware metadata capture through filesystem, Spotlight, and Finder metadata.

## Why this project matters

This repository demonstrates practical AI infrastructure work across retrieval,
tool design, local-first agent workflows, API design, safety controls, and
developer experience. It is intended to be useful both as an MCP server and as
a reference implementation for building safer, more capable retrieval systems
around Qdrant.

## Current project state

This repository is in active development.

- The package is a Python project named `mcp-server-qdrant` in `pyproject.toml`.
- The main MCP entry point is `mcp-server-qdrant`.
- The REST API entry point is `mcp-server-qdrant-webui`.
- The default MCP tool profile is `canonical`.
- The five discovery tools (`get_indexed_fields`, `get_supported_extractors`,
  `get_collection_schema`, `list_search_modes`, `get_server_capabilities`) are
  implemented and registered under the `minimal` profile.
- Streamable HTTP transport is supported alongside `stdio`, with loopback
  binding, Origin validation, and optional Bearer token auth.
- Embedding-provider state is resolved per request rather than mutated globally,
  so multiple agents can share one HTTP server safely.
- `delete_collection` and `ingest_folder` support a report/apply gating pattern
  with a single-use `plan_id` and a 10-minute TTL.

## What it does

At a high level, the server lets an MCP client or HTTP client:

- Create and inspect Qdrant collections.
- Store individual text entries or batches.
- Ingest plain-text-ish files, structured `.json`/`.jsonl`/`.csv`/`.tsv`,
  PDFs, and DOCX files.
- Capture macOS Spotlight and Finder metadata while ingesting files.
- Search by semantic similarity.
- Search by distinct document instead of raw chunks.
- Filter searches using a compact high-level filter grammar.
- Use FastEmbed dense embedding models, including supplemental Qwen3 entries.
- Create hybrid collections with dense vectors plus Qdrant BM25 sparse vectors.
- Run over MCP stdio, MCP SSE, MCP streamable HTTP, or the included FastAPI app.

## Installation

Requirements:

- Python 3.10 or newer
- `uv`
- Rust toolchain, if building the Qwen3 sidecar locally
- Docker, recommended for multi-agent Qdrant server mode
- macOS, if you want Spotlight/Finder metadata extraction

Install dependencies from the repository root:

```bash
uv sync --frozen --group dev
```

Run tests:

```bash
uv run --locked pytest
```

## Local Apple Silicon Qwen3 Setup

For local desktop use, this repo includes helper scripts that keep runtime
state out of Git:

```bash
./scripts/local-install.sh
./scripts/local-run-qdrant.sh
./scripts/local-configure-hermes.py
./scripts/local-doctor.sh
./scripts/local-run-webui.sh
./scripts/local-run-mcp.sh
```

Runtime state goes under `.local/`, while `.gitignore` excludes `.local/`,
`storage/`, `logs/`, and `.DS_Store`.

Qwen3 embedding models are routed through a Rust sidecar at:

```text
rust/qwen3_embedder/target/release/qwen3-embedder
```

Supported Qwen3 dense models:

| Model | Vector size | Local note |
| --- | ---: | --- |
| `Qwen/Qwen3-Embedding-0.6B` | 1024 | Fastest, lower quality |
| `Qwen/Qwen3-Embedding-4B` | 2560 | Recommended local book-scale default |
| `Qwen/Qwen3-Embedding-8B` | 4096 | Higher quality, much slower locally |

Recommended local REST startup for one-process embedded book ingestion:

```bash
EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-webui.sh
```

Recommended multi-agent startup uses a shared Qdrant server instead:

```bash
./scripts/local-run-qdrant.sh
QDRANT_MODE=server EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-webui.sh
QDRANT_MODE=server EMBEDDING_MODEL='Qwen/Qwen3-Embedding-4B' ./scripts/local-run-mcp.sh --transport streamable-http
```

`local-run-qdrant.sh` requires a reachable Docker daemon because it runs the
official Qdrant server container.

In server mode, REST, MCP, and other local agents all connect to
`http://127.0.0.1:6333` through `QDRANT_URL`. Do not set
`QDRANT_LOCAL_PATH` in that mode. Server-mode MCP processes treat Qdrant as an
external dependency and do not stop the Docker container when an MCP client
disconnects.

For Hermes, run:

```bash
./scripts/local-configure-hermes.py
hermes mcp test qdrant
```

The Hermes helper intentionally writes the direct virtualenv entrypoint
`.venv/bin/mcp-server-qdrant` instead of `uv run --locked mcp-server-qdrant`.
Some long-running launchers do not inherit the same `uv` environment as an
interactive shell, while the venv entrypoint is stable after
`./scripts/local-install.sh`.

Use the doctor script when something looks down:

```bash
./scripts/local-doctor.sh
```

It checks the MCP binary, Qwen3 sidecar, Docker daemon, Qdrant server readiness,
and Hermes MCP connection.

Useful local defaults from `scripts/local-env.sh`:

- `QDRANT_MODE=embedded`
- `QDRANT_LOCAL_PATH=.local/qdrant-storage`
- `QWEN3_DEVICE=auto`
- `QWEN3_MAX_LENGTH=1024`
- `QWEN3_DTYPE=auto`
- `QWEN3_RESPONSE_LIMIT_BYTES=67108864`
- `QDRANT_EMBEDDING_BATCH_SIZE=4`
- `QDRANT_INGEST_CHUNK_SIZE=700`
- `QDRANT_INGEST_CHUNK_OVERLAP=70`
- `QDRANT_WRITE_MAX_CONCURRENCY=1`
- `QDRANT_WRITE_QUEUE_SIZE=8`

Qwen3 timing and error metrics are written as JSONL to:

```text
.local/logs/qwen3-embeddings.jsonl
```

This file is intentionally runtime state and should not be committed.

Important implementation notes:

- Document embeddings are prefixed with `passage: ` before being sent to Qwen3.
- Multi-vector sidecar JSON responses can exceed asyncio's default line buffer;
  `QWEN3_RESPONSE_LIMIT_BYTES` keeps larger batches readable.
- Book-scale ingestion is now upserted incrementally per embedding batch, so a
  late failure does not discard all earlier successful batches.
- Password-protected PDFs fail during preflight instead of producing garbage
  extracted text.

## Launch Modes

There are two supported local launch modes.

| Mode | Qdrant config | Use when |
| --- | --- | --- |
| Embedded | `QDRANT_MODE=embedded`, `QDRANT_LOCAL_PATH=.local/qdrant-storage` | One process owns the store, such as only REST or only stdio MCP |
| Server | `QDRANT_MODE=server`, `QDRANT_URL=http://127.0.0.1:6333` | REST, MCP, and multiple agents need concurrent access |

Embedded Qdrant local mode takes an exclusive lock on its storage directory.
That is normal Qdrant behavior. If the REST API has `.local/qdrant-storage`
open, a second stdio MCP process pointed at the same path will fail with a
storage-lock error. This is why multi-agent launch uses one Qdrant server and
has every client connect over `QDRANT_URL`.

Qdrant server is safe for concurrent clients, but ingestion still needs
application-level backpressure. REST and MCP wrap store and ingest writes in a
bounded local queue. By default each server process runs one embedding/upsert
job at a time and allows eight waiting jobs:

```bash
QDRANT_WRITE_MAX_CONCURRENCY=1
QDRANT_WRITE_QUEUE_SIZE=8
```

This protects local Qwen3 embedding and Qdrant from simultaneous agent dumps.
Raise the concurrency only after load testing on the target machine. For the
cleanest multi-agent setup, route agents through one streamable HTTP MCP server
instead of many stdio MCP processes, so they share one write queue.

Do not mount `.local/qdrant-storage` directly into a Qdrant Docker server.
Python local-mode storage is not a supported server storage format. To keep
existing local-mode data, start a Qdrant server and copy collections:

```bash
./scripts/local-run-qdrant.sh
uv run --locked python scripts/migrate-local-to-server.py \
  --source-path .local/qdrant-storage \
  --target-url http://127.0.0.1:6333
```

Stop any embedded REST or MCP process before migration so the source path is
not locked.

## Running the MCP server

The CLI entry point is:

```bash
uv run mcp-server-qdrant
```

By default it uses MCP stdio, which is the right transport for clients that
spawn the server process directly, such as Claude Desktop or LM Studio.

Supported transports:

```bash
uv run mcp-server-qdrant --transport stdio
uv run mcp-server-qdrant --transport sse --host 127.0.0.1 --port 8000
uv run mcp-server-qdrant --transport streamable-http --host 127.0.0.1 --port 8000
```

`--transport http` is accepted as an alias for `streamable-http`.

By default, local Qdrant storage lives in `storage` under the project root for
embedded one-process use. Set `QDRANT_LOCAL_PATH` to move it. For concurrent
multi-agent use, set `QDRANT_URL` instead so the MCP server connects to a
shared Qdrant server.

## Communicating With MCP

There are two common ways to talk to this server as MCP.

### 1. Stdio MCP

Use stdio when the MCP client launches the server process itself:

```bash
./scripts/local-run-mcp.sh
```

Equivalent explicit command:

```bash
uv run --locked mcp-server-qdrant --transport stdio
```

Claude Desktop-style configuration for the recommended shared-server path:

```json
{
  "mcpServers": {
    "qdrant-enhanced": {
      "command": "/path/to/mcp-server-qdrant-enhanced/.venv/bin/mcp-server-qdrant",
      "args": [],
      "cwd": "/path/to/mcp-server-qdrant-enhanced",
      "env": {
        "QDRANT_MODE": "server",
        "QDRANT_URL": "http://127.0.0.1:6333",
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-4B",
        "QWEN3_SIDECAR_PATH": "/path/to/mcp-server-qdrant-enhanced/rust/qwen3_embedder/target/release/qwen3-embedder",
        "QDRANT_MCP_TOOL_PROFILE": "canonical"
      }
    }
  }
}
```

### 2. Streamable HTTP MCP

Use streamable HTTP when multiple local agents should share one MCP process:

```bash
QDRANT_MODE=server uv run --locked mcp-server-qdrant \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

If `MCP_HTTP_AUTH_TOKEN` is set, clients must send:

```http
Authorization: Bearer <token>
```

Recommended MCP workflow:

1. `get_server_capabilities`
2. `list_embedding_models`
3. `create_collection`
4. `bootstrap_collection_indexes`
5. `ingest_file` or `ingest_folder`
6. `search_documents`

Prefer `search_documents` over raw chunk search for normal retrieval.

## Claude Desktop example

Example configuration:

```json
{
  "mcpServers": {
    "qdrant-enhanced": {
      "command": "/path/to/mcp-server-qdrant-enhanced/.venv/bin/mcp-server-qdrant",
      "args": [],
      "cwd": "/path/to/mcp-server-qdrant-enhanced",
      "env": {
        "QDRANT_MODE": "server",
        "QDRANT_URL": "http://127.0.0.1:6333",
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-4B",
        "QDRANT_MCP_TOOL_PROFILE": "canonical"
      }
    }
  }
}
```

## HTTP security

For streamable HTTP, the server binds to `127.0.0.1` by default.

Relevant settings:

- `MCP_HOST`: HTTP bind host. Default: `127.0.0.1`.
- `MCP_PORT`: HTTP bind port. Default: `8000`.
- `FASTMCP_PORT`: fallback port env var.
- `MCP_HTTP_AUTH_TOKEN`: optional bearer token required on HTTP requests.
- `MCP_HTTP_ALLOWED_ORIGINS`: comma-separated allowed origins for origin checks.

Use loopback binding for local desktop use.

## Running the REST API

The FastAPI entry point mirrors the same Qdrant connector and ingestion
pipeline:

```bash
uv run mcp-server-qdrant-webui --host 127.0.0.1 --port 8765
```

OpenAPI docs are available at:

```text
http://127.0.0.1:8765/docs
```

REST endpoints include:

- `GET /health`
- `GET /collections`
- `GET /collections/{name}`
- `POST /collections`
- `DELETE /collections/{name}`
- `POST /collections/{name}/bootstrap_indexes`
- `POST /store`
- `POST /store_batch`
- `GET /scroll/{name}`
- `POST /search`
- `POST /search_documents`
- `POST /ingest/file`
- `POST /ingest/folder`
- `GET /embedding_models`
- `POST /embedding_models/active`

### REST Examples

Health:

```bash
curl http://127.0.0.1:8765/health
```

Create a Qwen3 4B collection:

```bash
curl -X POST http://127.0.0.1:8765/collections \
  -H 'Content-Type: application/json' \
  --data '{"collection_name":"my_docs_qwen3_4b","embedding_model":"Qwen/Qwen3-Embedding-4B","distance":"cosine"}'
```

Switch the active REST embedding provider:

```bash
curl -X POST http://127.0.0.1:8765/embedding_models/active \
  -H 'Content-Type: application/json' \
  --data '{"model_name":"Qwen/Qwen3-Embedding-4B"}'
```

Ingest a PDF:

```bash
curl -X POST http://127.0.0.1:8765/ingest/file \
  -H 'Content-Type: application/json' \
  --data '{"file_path":"/absolute/path/to/book.pdf","collection_name":"my_docs_qwen3_4b"}'
```

Search by distinct document:

```bash
curl -X POST http://127.0.0.1:8765/search_documents \
  -H 'Content-Type: application/json' \
  --data '{"query":"What is the main argument?","collection_name":"my_docs_qwen3_4b","limit":5,"chunks_per_document":2}'
```

## MCP tool profiles

The server has a profile gate so clients can expose a smaller or larger tool
surface. Configure it with:

```bash
QDRANT_MCP_TOOL_PROFILE=minimal
QDRANT_MCP_TOOL_PROFILE=canonical
QDRANT_MCP_TOOL_PROFILE=full
```

The default is `canonical`.

Profile intent:

- `minimal`: daily ingestion, document search, model listing, collection info.
- `canonical`: minimal plus collection creation, hybrid setup, index bootstrap,
  and active embedding model switching.
- `full`: canonical plus raw chunk-level storage/search/admin tools.

Configured profile mapping:

| Tool | Minimal | Canonical | Full |
| --- | --- | --- | --- |
| `search_documents` | yes | yes | yes |
| `ingest_file` | yes | yes | yes |
| `ingest_folder` | yes | yes | yes |
| `list_embedding_models` | yes | yes | yes |
| `get_collection_info` | yes | yes | yes |
| `list_collections` | yes | yes | yes |
| `get_server_capabilities` | yes | yes | yes |
| `get_indexed_fields` | yes | yes | yes |
| `get_supported_extractors` | yes | yes | yes |
| `get_collection_schema` | yes | yes | yes |
| `list_search_modes` | yes | yes | yes |
| `create_collection` | no | yes | yes |
| `create_hybrid_collection` | no | yes | yes |
| `bootstrap_collection_indexes` | no | yes | yes |
| `set_collection_embedding_model` | no | yes | yes |
| `delete_collection` | no | no | yes |
| `qdrant_find` | no | no | yes |
| `qdrant_store` | no | no | yes |
| `qdrant_store_batch` | no | no | yes |
| `scroll_collection` | no | no | yes |
| `hybrid_search` | no | no | yes |

## Main MCP tools

### Document search

`search_documents` is the preferred search tool.

It overfetches raw chunk hits, groups them by `metadata.document_id`, and
returns distinct documents ranked by their best representative chunks.

Arguments:

- `query`: semantic search query.
- `collection_name`: collection to search.
- `limit`: number of distinct documents to return. Default: `10`.
- `chunks_per_document`: number of best chunks to include per document.
  Default: `1`.
- `filter`: optional high-level filter object.
- `mode`: `dense`, `hybrid`, `rerank`, or `late_interaction`.
- `reranker_model`: optional reranker for `mode="rerank"`.
- `late_interaction_model`: optional model for `mode="late_interaction"`.

Search modes:

- `dense`: dense vector search with the active FastEmbed model.
- `hybrid`: dense + sparse BM25 search fused with reciprocal rank fusion.
- `rerank`: hybrid first stage followed by a cross-encoder reranker.
- `late_interaction`: ColBERT-style multivector retrieval using Qdrant MaxSim.
  Create or ingest into a late-interaction collection first.

### File ingestion

`ingest_file` extracts text from one file, captures metadata, chunks the text,
and stores all chunks in Qdrant.

Arguments:

- `file_path`: absolute path.
- `collection_name`: target collection; defaults to `documents`.
- `extra_metadata`: optional JSON string merged into every chunk.
- `mode`: `dense`, `hybrid`, or `late_interaction`.
- `embedding_model`: optional dense embedding model override.
- `late_interaction_model`: optional late-interaction model override.

`ingest_folder` recursively ingests supported files from a directory.

Arguments:

- `folder_path`: absolute path.
- `collection_name`: target collection; defaults to `documents`.
- `recursive`: default `true`.
- `skip_hidden`: default `true`.
- `extra_metadata`: optional JSON string merged into every file.
- `mode`: `dense`, `hybrid`, or `late_interaction`.
- `embedding_model`: optional dense embedding model override.
- `late_interaction_model`: optional late-interaction model override.
- `run_mode`: `apply` or `report`.
- `plan_id`: optional report/apply plan id.

Supported file types:

| Extension | Extractor |
| --- | --- |
| `.txt`, `.log`, `.rst`, `.conf`, `.ini`, `.env` | direct text read with charset fallback |
| `.md`, `.markdown` | direct text read, YAML/TOML frontmatter stripped |
| `.json`, `.jsonl` | parsed and rendered as searchable path/value text |
| `.csv`, `.tsv` | parsed and rendered as row/column text |
| `.yaml`, `.yml`, `.toml`, `.xml`, `.html`, `.htm` | direct text read with charset fallback |
| common code/script extensions | direct text read with charset fallback |
| `.pdf` | preflight scan, then `pdfminer.six`, with `pypdf` fallback |
| `.docx` | `python-docx`, including paragraphs and tables |

Chunking is paragraph-aware with a default target size of 700 characters and
70 characters of overlap. Tune with `QDRANT_INGEST_CHUNK_SIZE` and
`QDRANT_INGEST_CHUNK_OVERLAP`.

### Ingestion bottlenecks

Foreseeable ingestion bottlenecks:

- **PDF extraction:** `pdfminer.six` is CPU-heavy on large or structurally
  complex PDFs. The server now runs a cheap PDF preflight first, sampling a few
  pages for embedded text/images before full extraction.
- **OCR-less scanned PDFs:** OCR is not implemented. If preflight sees image
  resources but no extractable text in the sampled pages, the file is treated as
  probably scanned and full PDF text extraction is skipped. Ingest returns an
  extraction failure saying OCR is needed.
- **Password-protected PDFs:** encrypted PDFs that require a password fail
  during preflight. They are not extracted or embedded, because extractors can
  otherwise produce garbage-looking text that hurts retrieval quality.
- **Embedding throughput:** FastEmbed is batched, but dense, hybrid, and
  late-interaction modes still spend most ingestion time in embedding for large
  folders. On this local Apple Silicon setup, Qwen3 4B is the practical
  book-scale default; Qwen3 8B is much slower.
- **Late-interaction storage:** ColBERT-style multivectors store many vectors
  per chunk, so ingestion is slower and storage use is higher than dense mode.
- **Chunking quality:** current chunking is paragraph-aware with fixed
  character overlap. It is predictable and cheap, but code, tables, and
  structured files may benefit from format-aware chunking later.
- **macOS metadata:** Spotlight/Finder metadata collection runs in bounded async
  subprocesses. Raising `QDRANT_METADATA_MAX_PROCS` can increase throughput but
  may make folder ingest noisier on the machine.
- **Qdrant writes and indexes:** large folders pay for vector upsert and payload
  indexes. Running `bootstrap_collection_indexes` before bulk ingest avoids
  creating metadata indexes late.
- **Sidecar JSON response size:** large embedding batches return large JSON
  lines. `QWEN3_RESPONSE_LIMIT_BYTES` raises the asyncio subprocess read limit
  so multi-vector responses do not fail at the pipe boundary.

### Collection tools

`list_collections` lists available Qdrant collections.

`get_collection_info` returns point/vector counts, status, vector size, and
distance metric.

`create_collection` creates a dense-vector collection from an embedding model.
The vector size is inferred from the model unless `vector_size` is provided.

`create_hybrid_collection` creates a collection with:

- One dense vector slot using the selected FastEmbed model.
- One sparse vector slot using `Qdrant/bm25` by default.

`create_late_interaction_collection` creates a Qdrant multivector collection
for ColBERT-style MaxSim retrieval. The default late-interaction model is
`colbert-ir/colbertv2.0`, and `search_documents(mode="late_interaction")`
queries the multivector field.

`bootstrap_collection_indexes` creates payload indexes for the standard macOS
metadata fields.

`delete_collection` is only exposed in the `full` profile and requires
`confirm=true`.

### Embedding model tools

`list_embedding_models` asks FastEmbed for supported dense models and appends
supplemental Qwen3 entries.

The supplemental Qwen3 entries are:

- `Qwen/Qwen3-Embedding-0.6B` — 1024 dimensions
- `Qwen/Qwen3-Embedding-4B` — 2560 dimensions
- `Qwen/Qwen3-Embedding-8B` — 4096 dimensions

`set_collection_embedding_model` switches the active provider for subsequent
store and search operations for that collection. Assignments are persisted to
`<storage>/collection_models.json` and reloaded on server startup.

### Raw tools

The `full` profile exposes raw chunk-level tools:

- `qdrant_store`
- `qdrant_find`
- `qdrant_store_batch`
- `scroll_collection`
- `hybrid_search`

These are useful for diagnostics and low-level manipulation, but
`search_documents` and the ingestion tools are the preferred high-level path.
`qdrant_find` is retained for compatibility and resolves embedding providers
per request, but new clients should prefer `search_documents`.

## Structured outputs

Priority tools return the versioned `{contract, data, observability}` envelope
and advertise MCP `outputSchema` metadata in `tools/list`. The schemas are
defined in `src/mcp_server_qdrant/mcp_runtime/schemas.py` and attached during
tool registration.

## Discovery tools

Five read-only self-description tools let an agent inspect the server before
acting. All five live in the `minimal` profile and return the structured
envelope.

| Tool | Returns |
| --- | --- |
| `get_server_capabilities` | transports, profiles, search modes, extraction formats, feature flags |
| `get_indexed_fields` | filterable payload fields with types, allowed operators, role, and the high-level filter grammar |
| `get_supported_extractors` | per-extension extractor stack and chunking strategy |
| `list_search_modes` | `dense`, `hybrid`, `rerank`, `late_interaction` with when-to-use guidance |
| `get_collection_schema` | per-collection vector config, distance metric, point counts, status |

These payloads are static where possible (no per-request work) so calling
them cheaply is fine.

## Report/apply gating

Mutating or expensive tools support a two-step pattern:

1. Call with `mode="report"` (or `run_mode="report"` for `ingest_folder`) to
   preview the action. The server returns a `plan_id` with a 10-minute TTL plus
   a description of what would happen.
2. Call again with `mode="apply"` and `plan_id=<id>` to execute. The plan_id
   is single-use, scoped to the originating tool, and validated against the
   request target before execution.

| Tool | Report payload includes |
| --- | --- |
| `delete_collection` | target collection, existence, vector config, point count, destructive warning |
| `ingest_folder` | candidate file count, extension breakdown, sample paths, warnings |

`bootstrap_collection_indexes` is idempotent and not gated. Direct `apply`
without first running `report` is allowed for low-risk cases (e.g. running
`ingest_folder` once you already trust the inputs); strict gating can be
enforced by your client by requiring a fresh plan_id.

## Multi-agent safety

The server is designed for multiple AI agents sharing one running process
over Streamable HTTP. The relevant guarantees:

- Embedding providers are resolved per request, not held as a single mutable
  global. `set_collection_embedding_model` records a per-collection assignment
  in the resolver and does not affect other clients targeting other collections.
- Provider instances are cached by `(provider_type, model_name)` so re-using a
  model across requests is fast, but no cached entry is mutated after creation.
- The plan registry is process-local, namespaced by tool, with TTL eviction
  and single-use semantics.
- HTTP transport binds to `127.0.0.1` by default, validates the `Origin`
  header against an allowlist, and supports an optional Bearer token via
  `MCP_HTTP_AUTH_TOKEN`.

If you discover a request path that mutates shared state, please open an
issue — the auditing intent is that no client can change behavior another
client observes.

## Recommended workflows

### Safe setup
1. `get_server_capabilities` — confirm transport and feature set
2. `list_embedding_models` — pick a dense model
3. `create_collection` *or* `create_hybrid_collection` for hybrid retrieval
4. `bootstrap_collection_indexes` — pre-create payload indexes
5. `ingest_folder` (optionally with `run_mode="report"` first)
6. `search_documents` to verify the corpus

### Safe search
1. `get_indexed_fields` — inspect the filter grammar and available fields
2. `search_documents(mode="dense" | "hybrid" | "rerank", filter=...)`
3. Refine filters / re-search until satisfied

### Safe mutation
1. `delete_collection(collection_name="x", mode="report")` → returns plan_id
2. Inspect the plan payload; confirm the target and warnings
3. `delete_collection(collection_name="x", mode="apply", plan_id="plan_xyz")`

## Response envelope

Priority tools return a versioned JSON envelope:

```json
{
  "contract": {
    "contract_version": "1.0",
    "toolset_version": "0.8.0",
    "profile": "canonical"
  },
  "data": {},
  "observability": {
    "duration_ms": 12,
    "warnings": [],
    "stats": {}
  }
}
```

Failures use the same outer structure with `error` instead of `data`:

```json
{
  "contract": {
    "contract_version": "1.0",
    "toolset_version": "0.8.0",
    "profile": "canonical"
  },
  "error": {
    "code": "invalid_argument",
    "message": "Unsupported search mode",
    "retryable": false
  },
  "observability": {
    "duration_ms": 4,
    "warnings": [],
    "stats": {}
  }
}
```

Some legacy/raw tools still return strings or lists of strings.

## macOS metadata

During file ingestion, the server reads filesystem metadata, Spotlight metadata
via `mdls`, and Finder tags via extended attributes when available.

Common metadata fields:

| Field | Description |
| --- | --- |
| `metadata.document_id` | stable SHA-1-based file identifier |
| `metadata.path` | absolute source path |
| `metadata.parent_path` | parent folder |
| `metadata.filename` | filename with extension |
| `metadata.extension` | lowercase extension without dot |
| `metadata.size_bytes` | file size |
| `metadata.is_hidden` | dotfile/hidden flag |
| `metadata.has_text` | extraction produced text |
| `metadata.content_type` | Spotlight content type |
| `metadata.title` | Spotlight title |
| `metadata.tags` | Finder/Spotlight tags |
| `metadata.authors` | Spotlight authors |
| `metadata.keywords` | Spotlight keywords |
| `metadata.comment` | Spotlight comment |
| `metadata.source_urls` | Spotlight where-from URLs |
| `metadata.created_at` | ISO timestamp |
| `metadata.modified_at` | ISO timestamp |
| `metadata.last_opened_at` | ISO timestamp |
| `metadata.page_count` | page count when available |
| `metadata.extractor_used` | extraction backend |
| `metadata.char_count` | extracted character count |
| `metadata.ingested_at` | ingestion timestamp |
| `metadata.chunk_index` | chunk number within document |
| `metadata.total_chunks` | total chunks for document |

The index bootstrap path creates Qdrant payload indexes for the common
filterable fields.

## Filter grammar

`search_documents` and the REST search endpoints accept a high-level filter
shape:

```json
{
  "must": [
    { "field": "extension", "op": "==", "value": "pdf" },
    { "field": "modified_at", "op": ">=", "value": "2026-01-01T00:00:00Z" }
  ],
  "should": [
    { "field": "tags", "op": "any", "value": ["work", "reference"] }
  ],
  "must_not": [
    { "field": "is_hidden", "op": "==", "value": true }
  ]
}
```

Operators:

- `==`
- `!=`
- `>`
- `>=`
- `<`
- `<=`
- `any`
- `except`

Field names are automatically prefixed with `metadata.` unless they already
contain a dot. ISO date strings are compiled to Qdrant datetime ranges for
range operators.

For strict exclusion on array fields, prefer `must_not` with `any`.

## Embedding models

The only implemented embedding provider type is FastEmbed. The test suite also
contains an optional FlagEmbedding/BGE smoke test; it skips automatically unless
`FlagEmbedding` is installed.

Default model:

```text
sentence-transformers/all-MiniLM-L6-v2
```

Supplemental model entries added by this project:

| Model | Dimensions | Notes |
| --- | ---: | --- |
| `Qwen/Qwen3-Embedding-0.6B` | 1024 | lightweight Qwen3 embedding model |
| `Qwen/Qwen3-Embedding-8B` | 4096 | larger multilingual/code retrieval model |

The server also lists models reported by `fastembed.TextEmbedding`.

Optional compatibility smoke:

```bash
uv pip install FlagEmbedding
uv run --locked pytest tests/test_flagembedding_optional.py
```

That test checks `BAAI/bge-base-en-v1.5` through `FlagEmbedding.FlagModel` and
expects a 768-dimensional vector. It is intentionally not a required provider
path yet.

Important: collection vector dimensions must match the model used to store and
search data. Create a new collection when switching to a model with a different
dimension.

FastEmbed runs on CPU by default. Set `EMBEDDING_DEVICE` to another device
supported by the installed FastEmbed/ONNX runtime, such as `cuda` or `mps`, to
use local acceleration when available.

Batch storage paths call FastEmbed with document batches, so embedding
computation is batched for `batch_store`, `ingest_file`, and `ingest_folder`.
Repeated high-level metadata filters are compiled through a small in-process
cache before being sent to Qdrant.

## Configuration

Core environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `QDRANT_MODE` | `embedded` in local scripts | `embedded`, `server`, or `docker` helper mode |
| `QDRANT_URL` | unset, or `http://127.0.0.1:6333` in server/docker local scripts | External Qdrant server URL |
| `QDRANT_API_KEY` | unset | Qdrant API key |
| `QDRANT_LOCAL_PATH` | `<repo>/storage`, or `.local/qdrant-storage` in embedded local scripts | Embedded local-mode storage path; leave unset when `QDRANT_URL` is set |
| `QDRANT_DOCKER_STORAGE_PATH` | `.local/qdrant-server-storage` in docker local scripts | Qdrant server Docker volume path |
| `COLLECTION_NAME` | `documents` | Optional default collection |
| `EMBEDDING_PROVIDER` | `fastembed` | Embedding provider type |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-8B` | Active dense embedding model |
| `EMBEDDING_DEVICE` | `auto` | FastEmbed/Qwen3 device, e.g. `auto`, `cpu`, `cuda`, `mps`, or `metal` when supported |
| `QWEN3_SIDECAR_PATH` | auto-detected | Optional Rust Qwen3 sidecar binary path |
| `QWEN3_RESPONSE_LIMIT_BYTES` | `67108864` in local scripts | Async stdout read limit for large Qwen3 sidecar responses |
| `QWEN3_METRICS_PATH` | `.local/logs/qwen3-embeddings.jsonl` in local scripts | Optional JSONL timing/error metrics path |
| `QDRANT_EMBEDDING_BATCH_SIZE` | `4` | Embedding/upsert batch size for batch storage and ingestion |
| `QDRANT_INGEST_CHUNK_SIZE` | `700` in local scripts | Target ingest chunk size in characters |
| `QDRANT_INGEST_CHUNK_OVERLAP` | `70` in local scripts | Chunk overlap in characters |
| `QDRANT_WRITE_MAX_CONCURRENCY` | `1` | Concurrent embedding/upsert write jobs per server process |
| `QDRANT_WRITE_QUEUE_SIZE` | `8` | Waiting write jobs before new writes return a queue-full error |
| `QDRANT_SEARCH_LIMIT` | `50` | Default limit for raw find |
| `QDRANT_READ_ONLY` | `false` | Hide mutation tools when true |
| `QDRANT_ALLOW_ARBITRARY_FILTER` | `false` | Allow raw Qdrant filters on legacy find |
| `QDRANT_ENABLE_COLLECTION_MANAGEMENT` | `true` | Register collection tools |
| `QDRANT_ENABLE_DYNAMIC_EMBEDDING_MODELS` | `true` | Register embedding model tools |
| `QDRANT_ENABLE_RESOURCES` | `true` | Register MCP resources |
| `QDRANT_DEFAULT_VECTOR_SIZE` | `384` | Default vector-size setting |
| `QDRANT_DEFAULT_DISTANCE_METRIC` | `cosine` | Default distance metric setting |
| `QDRANT_MAX_BATCH_SIZE` | `10000` | Configured batch-size ceiling |
| `QDRANT_MCP_TOOL_PROFILE` | `canonical` | Tool exposure profile |
| `QDRANT_METADATA_MAX_PROCS` | `8` | Maximum concurrent macOS metadata subprocesses |

HTTP transport variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | `stdio`, `sse`, `streamable-http`, or `http` |
| `MCP_HOST` | `127.0.0.1` | HTTP bind host |
| `MCP_PORT` | `8000` | HTTP bind port |
| `FASTMCP_PORT` | `8000` fallback | Alternate port variable |
| `MCP_HTTP_AUTH_TOKEN` | unset | Optional bearer token |
| `MCP_HTTP_ALLOWED_ORIGINS` | unset | Allowed HTTP origins |

Development dependency policy:

- Use `uv sync --frozen --group dev` for normal setup.
- Use `uv run --locked ...` for day-to-day commands when possible.
- Treat `uv.lock` as committed, cross-platform state; dependency updates
  should be deliberate and reviewed, preferably from a single canonical
  environment.

## Perplexity MCP Research Companion

This repository work has used a separate Perplexity MCP server for external
research. It is not part of `mcp-server-qdrant`; it is an auxiliary MCP tool
available in this Codex environment. When asking an agent to use Perplexity, be
explicit about both the **mode** and the **source focus**.

Perplexity modes map to MCP tools like this:

| Human request | Perplexity MCP tool | What it does | When to use |
| --- | --- | --- | --- |
| Search | `perplexity_search` or `perplexity_ask` with concise/default mode | One-step lookup plus quick synthesis | Daily questions, quick answers, current facts |
| Reasoning | `perplexity_reason` or `perplexity_ask` with `mode="copilot"` / reasoning model when available | Uses stronger reasoning over web context | Multi-step debugging, analytical coding/math questions |
| Deep Research | `perplexity_research` | Agentic research loop over many sources, returns a mini-report | Technical investigations, competitive analysis, literature-review style work |
| Compute / ASI | `perplexity_compute` | Computer/ASI mode for heavier task execution | Calculation-heavy or workflow-like research tasks |

Source focus is a separate setting. It changes where Perplexity looks, not
which reasoning mode it uses:

| Focus | MCP value here | What it surfaces | Best use cases |
| --- | --- | --- | --- |
| Web | `sources=["web"]` | Broad internet: docs, news, blogs, product pages | General research, current events, product overviews |
| Academic | `sources=["scholar"]` | Papers, scholarly indexes, arXiv-style sources | Scientific/technical questions and citation-heavy reports |
| Social | `sources=["social"]` | Reddit, X/Twitter, forums, community discussion | Developer sentiment, community workarounds, “what are people saying?” |

The common mistake is mixing up **mode** and **focus**. For example, asking for
“research with social sources” means `perplexity_research` plus
`sources=["social"]`. Asking for “reasoning with social sources” means
`perplexity_reason` or a reasoning/copilot ask plus `sources=["social"]`.

The current Perplexity MCP schema exposes `web`, `scholar`, and `social` source
focus values. Perplexity product focus modes such as Video and Writing may exist
in the Perplexity UI, but they are not part of the MCP source list used here
unless that MCP server adds them.

Examples:

```text
Use Perplexity deep research with sources=["scholar"] to compare Qdrant
multivector late-interaction implementation patterns.
```

```text
Use Perplexity reasoning with sources=["social"] to debug why Codex MCP stdio
transports are closing for this server.
```

```text
Use Perplexity search with sources=["web"] for the current FastMCP output_schema
API and cite official docs.
```

In this session, “research” means `perplexity_research`. “Reasoning” means
`perplexity_reason` or `perplexity_ask` configured for a reasoning/copilot mode.
If the request matters, spell out the exact tool or mode.

## MCP resources

When resources are enabled:

- `qdrant://collections`: markdown overview of all collections.
- `qdrant://collection/{collection_name}/schema`: markdown schema/statistics
  for one collection.

## Development notes

Useful commands:

```bash
uv sync --frozen --group dev
uv run --locked pytest
uv run --locked ruff check src tests
./scripts/local-run-qdrant.sh
./scripts/local-configure-hermes.py
./scripts/local-doctor.sh
uv run mcp-server-qdrant --transport stdio
uv run mcp-server-qdrant-webui --host 127.0.0.1 --port 8765 --reload
```

Main code areas:

| Path | Purpose |
| --- | --- |
| `src/mcp_server_qdrant/main.py` | MCP CLI transport entry point |
| `src/mcp_server_qdrant/server.py` | server construction |
| `src/mcp_server_qdrant/mcp_server.py` | MCP tool registration |
| `src/mcp_server_qdrant/qdrant.py` | async Qdrant connector |
| `src/mcp_server_qdrant/embedding_manager.py` | FastEmbed model registry |
| `src/mcp_server_qdrant/embeddings/` | dense and sparse embedding providers |
| `src/mcp_server_qdrant/ingest/` | extraction, metadata, document IDs |
| `src/mcp_server_qdrant/search/` | grouped search, filter grammar, reranking |
| `src/mcp_server_qdrant/mcp_runtime/` | profiles, envelopes, HTTP security |
| `src/mcp_server_qdrant/webui/` | FastAPI app |
| `tests/` | pytest suite |

## Known limitations

- OCR is not implemented. Probably scanned/image-only PDFs fail early with an
  OCR-needed extraction message after lightweight preflight.
- `.docx` tables are extracted with `python-docx`; embedded images are not.
- Only FastEmbed is implemented as an embedding provider.
- Late-interaction retrieval requires a collection created with
  `create_late_interaction_collection` or chunks ingested with
  `mode="late_interaction"`; dense/hybrid collections cannot be queried with
  that mode.

## License

Apache-2.0. See `LICENSE`.
