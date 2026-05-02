# mcp-server-qdrant-enhanced

An enhanced Model Context Protocol server for storing, ingesting, and searching
semantic context in Qdrant.

This project extends the base Qdrant MCP idea with macOS-aware file ingestion,
document-grouped retrieval, dynamic FastEmbed model selection, hybrid dense +
sparse search support, MCP tool exposure profiles, and a FastAPI surface for
non-MCP clients.

## Current project state

This repository is in active development.

Important status for the current checkout:

- The package is a Python project named `mcp-server-qdrant` in
  `pyproject.toml`.
- The main MCP entry point is `mcp-server-qdrant`.
- The REST API entry point is `mcp-server-qdrant-webui`.
- The default MCP tool profile is `canonical`.
- The worktree currently contains a pending discovery-tools integration:
  `src/mcp_server_qdrant/mcp_runtime/discovery.py` exists and
  `mcp_server.py` calls `self.setup_discovery_tools()`, but that method is not
  defined in the current file. As of this checkout, importing the MCP server
  fails until that integration is completed or the call is removed.
- This README documents the implemented code paths and flags the known startup
  issue rather than hiding it.

## What it does

At a high level, the server lets an MCP client or HTTP client:

- Create and inspect Qdrant collections.
- Store individual text entries or batches.
- Ingest `.txt`, `.md`, `.pdf`, and `.docx` files.
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
- Docker for the current MCP CLI path, which attempts to auto-start Qdrant
- macOS, if you want Spotlight/Finder metadata extraction

Install dependencies from the repository root:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

Because the current checkout has the pending `setup_discovery_tools()` call,
server startup is expected to fail until that code path is fixed.

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

The CLI currently calls the Docker helper on startup. That helper starts a
container named `qdrant_mcp_server` from the `qdrant/qdrant` image and stores
data in `qdrant_storage` under the project root.

## Claude Desktop example

Example configuration:

```json
{
  "mcpServers": {
    "qdrant-enhanced": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/kat/REPOS/mcp-server-qdrant-enhanced",
        "run",
        "mcp-server-qdrant"
      ],
      "env": {
        "QDRANT_URL": "http://localhost:6333",
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
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

The profile map also lists discovery tools such as `get_indexed_fields` and
`get_server_capabilities`, but those are part of the incomplete discovery-tool
integration in the current checkout.

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
- `mode`: `dense`, `hybrid`, `rerank`, or reserved `late_interaction`.
- `reranker_model`: optional reranker for `mode="rerank"`.

Search modes:

- `dense`: dense vector search with the active FastEmbed model.
- `hybrid`: dense + sparse BM25 search fused with reciprocal rank fusion.
- `rerank`: hybrid first stage followed by a cross-encoder reranker.
- `late_interaction`: reserved for future ColBERT-style retrieval.

### File ingestion

`ingest_file` extracts text from one file, captures metadata, chunks the text,
and stores all chunks in Qdrant.

Arguments:

- `file_path`: absolute path.
- `collection_name`: target collection.
- `extra_metadata`: optional JSON string merged into every chunk.
- `mode`: `dense` or `hybrid`.

`ingest_folder` recursively ingests supported files from a directory.

Arguments:

- `folder_path`: absolute path.
- `collection_name`: target collection.
- `recursive`: default `true`.
- `skip_hidden`: default `true`.
- `extra_metadata`: optional JSON string merged into every file.
- `mode`: `dense` or `hybrid`.

Supported file types:

| Extension | Extractor |
| --- | --- |
| `.txt` | direct text read with charset fallback |
| `.md` | direct text read, YAML/TOML frontmatter stripped |
| `.pdf` | `pdfminer.six`, with `pypdf` fallback |
| `.docx` | `python-docx` |

Chunking is paragraph-aware with a target size of 1500 characters and 150
characters of overlap.

### Collection tools

`list_collections` lists available Qdrant collections.

`get_collection_info` returns point/vector counts, status, vector size, and
distance metric.

`create_collection` creates a dense-vector collection from an embedding model.
The vector size is inferred from the model unless `vector_size` is provided.

`create_hybrid_collection` creates a collection with:

- One dense vector slot using the selected FastEmbed model.
- One sparse vector slot using `Qdrant/bm25` by default.

`bootstrap_collection_indexes` creates payload indexes for the standard macOS
metadata fields.

`delete_collection` is only exposed in the `full` profile and requires
`confirm=true`.

### Embedding model tools

`list_embedding_models` asks FastEmbed for supported dense models and appends
supplemental Qwen3 entries.

`set_collection_embedding_model` switches the active provider for subsequent
store and search operations. Despite the historical name, the current
implementation switches the active model on the server instance; it does not
persist a per-collection model mapping.

### Raw tools

The `full` profile exposes raw chunk-level tools:

- `qdrant_store`
- `qdrant_find`
- `qdrant_store_batch`
- `scroll_collection`
- `hybrid_search`

These are useful for diagnostics and low-level manipulation, but
`search_documents` and the ingestion tools are the preferred high-level path.

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

The only implemented embedding provider type is FastEmbed.

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

Important: collection vector dimensions must match the model used to store and
search data. Create a new collection when switching to a model with a different
dimension.

## Configuration

Core environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `QDRANT_URL` | unset | External Qdrant URL |
| `QDRANT_API_KEY` | unset | Qdrant API key |
| `QDRANT_LOCAL_PATH` | unset | Local Qdrant client storage path |
| `COLLECTION_NAME` | unset | Optional default collection |
| `EMBEDDING_PROVIDER` | `fastembed` | Embedding provider type |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Active dense embedding model |
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

HTTP transport variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | `stdio`, `sse`, `streamable-http`, or `http` |
| `MCP_HOST` | `127.0.0.1` | HTTP bind host |
| `MCP_PORT` | `8000` | HTTP bind port |
| `FASTMCP_PORT` | `8000` fallback | Alternate port variable |
| `MCP_HTTP_AUTH_TOKEN` | unset | Optional bearer token |
| `MCP_HTTP_ALLOWED_ORIGINS` | unset | Allowed HTTP origins |

## MCP resources

When resources are enabled:

- `qdrant://collections`: markdown overview of all collections.
- `qdrant://collection/{collection_name}/schema`: markdown schema/statistics
  for one collection.

## Development notes

Useful commands:

```bash
uv sync
uv run pytest
uv run ruff check .
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

- Current checkout startup is blocked by the incomplete discovery-tools wiring
  noted above.
- OCR is not implemented. Image-only PDFs produce empty extraction results.
- `.docx` table and embedded-image extraction is limited.
- Only FastEmbed is implemented as an embedding provider.
- `set_collection_embedding_model` changes the active server-side provider; it
  does not persist per-collection model state.
- The CLI Docker helper currently attempts to manage a local Qdrant container
  on startup.
- Some older docs in the repository describe historical configuration modes
  that do not map cleanly to the current settings code.

## License

Apache-2.0. See `LICENSE`.
