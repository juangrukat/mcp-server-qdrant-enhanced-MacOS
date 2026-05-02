# Handoff Brief — `mcp-server-qdrant-enhanced-MacOS`

> Last updated: 2026-05-03
> Repo: <https://github.com/juangrukat/mcp-server-qdrant-enhanced-MacOS>
> Audience: a fresh session (human or model) picking this up cold.

This document is the single source of truth for "where is this project and
what's next." Read it top-to-bottom before making changes. If you finish a
priority below, update the **Status** column and the **Last updated** date.

---

## 1. TL;DR

A macOS-native fork of the Qdrant MCP server. It now does:

- **macOS file ingestion** (.txt, .md, .pdf, .docx) with Spotlight + Finder metadata
- **Qwen3-Embedding-8B** (4096D) supplemental dense model alongside the FastEmbed lineup
- **Hybrid retrieval** — dense + sparse (Qdrant/bm25) with server-side RRF fusion
- **Document-grouped search** with reranker abstraction (NoOp / FastEmbed cross-encoder / Qwen3-Reranker stub)
- **Filter grammar** (`must`/`should`/`must_not` × `==`/`!=`/`>`/`>=`/`<`/`<=`/`any`/`except`)
- **MCP layer overhaul** (this is the meaningful new surface):
  - dual transport: `stdio` and Streamable HTTP (loopback bind, Origin allowlist, optional Bearer token)
  - tool profiles `minimal | canonical | full` driven by `QDRANT_MCP_TOOL_PROFILE`
  - structured response envelope `{contract, data, observability}` on priority tools
  - five discovery tools (`get_server_capabilities`, `get_indexed_fields`, `get_supported_extractors`, `get_collection_schema`, `list_search_modes`)
  - per-request embedding provider resolution (multi-agent safe)
  - report/apply gating on `delete_collection` and `ingest_folder`
- **FastAPI REST surface** — same connector + pipeline, served via `mcp-server-qdrant-webui`

The local working directory is `/Users/kat/REPOS/mcp-server-qdrant-enhanced/`
(the original clone — not renamed, by design). The remote `macos-fork` points
at the public repo above; `origin` is the upstream `angrysky56` fork; `upstream`
is `qdrant/mcp-server-qdrant`.

---

## 2. Repository map

```
src/mcp_server_qdrant/
├── main.py                    # CLI entry: --transport stdio|sse|streamable-http|http
├── server.py                  # bootstraps QdrantMCPServer
├── mcp_server.py              # FastMCP subclass — registers tools, profile gate
├── settings.py                # pydantic settings (env-driven)
├── enhanced_tool_descriptions.py  # human-readable tool docstrings
├── qdrant.py                  # QdrantConnector — store/search/hybrid methods
├── embedding_manager.py       # FastEmbed registry + Qwen3 supplemental
├── docker_utils.py            # auto-spawn local Qdrant container
├── port_manager.py            # interactive port handling
│
├── embeddings/
│   ├── base.py                # EmbeddingProvider ABC
│   ├── fastembed.py           # dense provider; KNOWN_MODEL_DIMS fallback for Qwen
│   ├── sparse.py              # SparseEmbeddingProvider (Qdrant/bm25 default)
│   ├── factory.py             # provider construction
│   └── types.py
│
├── ingest/
│   ├── extractor.py           # txt/md/pdf/docx; pdfminer→pypdf fallback
│   ├── macos_metadata.py      # mdls + xattr + MACOS_INDEX_FIELDS
│   └── document_id.py         # sha1-based stable doc ids
│
├── search/
│   ├── document_search.py     # group-by-document reranking + overfetch
│   ├── filter_grammar.py      # high-level filter compiler
│   ├── retrieval_mode.py      # dense | hybrid | rerank | late_interaction
│   └── reranker.py            # Reranker ABC + NoOp + FastEmbed + Qwen3 stub
│
├── mcp_runtime/               # NEW: MCP-layer concerns
│   ├── http_security.py       # OriginValidationMiddleware, BearerAuthMiddleware
│   ├── profiles.py            # ToolProfile enum + TOOL_PROFILES map
│   ├── envelope.py            # success/failure helpers, envelope_context
│   ├── discovery.py           # static payloads for discovery tools
│   ├── provider_resolver.py   # per-request provider cache
│   └── plan_registry.py       # report/apply plan registry
│
├── webui/
│   ├── api.py                 # FastAPI app — mirrors MCP tools as REST
│   └── main.py                # uvicorn entry: mcp-server-qdrant-webui
│
└── common/
    ├── filters.py             # legacy make_indexes
    ├── func_tools.py          # make_partial_function
    └── wrap_filters.py        # wrap_filters
```

> The submodule was named `mcp_runtime` (not `mcp`) to avoid shadowing the
> top-level `mcp` SDK package that fastmcp depends on.

---

## 3. What's been done (commit timeline)

### Phase 1 — foundation (5 commits, pushed)
| Commit | Subject |
|---|---|
| `310b9eb` | feat: add Qwen3 embedding support and per-collection model swapping |
| `27eaa9c` | feat: add macOS metadata ingestion and text extractors |
| `520d81f` | feat: add hybrid search, filter grammar, and reranker abstraction |
| `924f87b` | feat: add FastAPI REST API for web UI integration |
| `270a73a` | docs: update README, configs, Dockerfile, and requirements |

### Phase 2 — MCP layer overhaul (7 commits, pushed)
| Commit | Subject |
|---|---|
| `c901cdf` | feat(mcp): add streamable-http transport for multi-client local use |
| `4e42424` | feat(mcp): add tool profiles (minimal \| canonical \| full) |
| `57098e2` | feat(mcp): add structured response envelope for priority tools |
| `01ef33c` | feat(mcp): add discovery / capability tools |
| `23d0b0c` | feat(mcp): per-request embedding provider resolution |
| `b2e39cc` | feat(mcp): add report/apply gating for delete_collection and ingest_folder |
| `1ec20cd` | docs(mcp): document transports, profiles, envelope, discovery, report/apply |

All commits include `Co-Authored-By: Claude Sonnet 4.6`.

---

## 4. Acceptance criteria — current state

| Criterion | Status |
|---|---|
| `stdio` and Streamable HTTP transport | ✅ done |
| Multi-agent safety (no shared mutable provider) | ✅ done — per-request resolver, providers cached but never mutated |
| Profile-based tool exposure | ✅ done — `minimal=11`, `canonical=15`, `full=21` tools (counts include discovery) |
| Structured response envelope on priority tools | ✅ done for 6 tools + 5 discovery tools |
| Discovery tools | ✅ done — 5 tools |
| README explains the new MCP model | ✅ done |
| Existing core functionality still works | ✅ verified at module level (imports, registration). Not end-to-end tested under HTTP transport with concurrent clients. |
| `outputSchema` + `structuredContent` declared per tool | ⚠️ **PARTIAL** — fastmcp 2.8's `@tool()` decorator does not accept `output_schema=`. Tools return typed dicts so JSON serialization is correct, but the MCP-protocol-level `outputSchema` field is not populated. See Priority 1 below. |
| Test coverage for transport, schema, multi-client | ❌ **MISSING** — see Priority 2. |

---

## 5. Known limitations / blockers

### 5a. `outputSchema` not declared at MCP protocol level
**Why this matters:** the MCP spec lets tools advertise an `outputSchema` so
clients can validate the shape of `structuredContent`. We return the right
shape — fastmcp serializes `dict` returns as `structuredContent` — but the
`outputSchema` JSON in `tools/list` is not populated. Strict clients won't
get the contract guarantees the brief specified.

**What's needed:** either (a) upgrade past fastmcp 2.8 once it gains
`output_schema=` (watch <https://github.com/jlowin/fastmcp/releases>), or
(b) post-process registered `FunctionTool` objects to attach an
`output_schema` to their MCP metadata. Option (b) is a thin wrapper, ~50 LOC.

**Workaround for now:** clients can rely on `contract.contract_version=="1.0"`
and the documented envelope shape. Bumping `contract_version` is the signal
for any future shape change.

### 5b. No tests
The `tests/` directory contains 1 file (`test_vector_name_fix.py`) from
upstream. Nothing covers profiles, envelope, transport, plan registry,
provider resolver, or filter grammar.

### 5c. `late_interaction` retrieval mode is reserved but not implemented
Returns a structured "mode_not_supported" failure today. ColBERT-style late
interaction is the planned implementation; FastEmbed has a `LateInteractionTextEmbedding`
class (e.g. `colbert-ir/colbertv2.0`) but it requires per-token storage and
multi-vector collections — significantly more work than the current dense+sparse path.

### 5d. Sparse provider is still a lazy singleton
`get_sparse_provider()` caches one instance per server. This is OK for
multi-agent safety because BM25 is stateless from the request's perspective,
but if we ever swap to a sparse model with mutable state (some SPLADE variants),
this becomes unsafe. Documented in commit `23d0b0c`.

### 5e. `set_collection_embedding_model` storage is in-memory
The collection→model assignment lives in `ProviderResolver._collection_models`
(a dict). It's lost on server restart. For persistence we'd need to either:
- Store it in Qdrant's collection metadata (Qdrant supports payload but not
  arbitrary collection-level metadata; would need a `_meta` collection or
  similar), or
- Persist a sidecar JSON file.

Not blocking, but the assignment doesn't survive a process restart today.

### 5f. `qdrant_find` is broken under default settings
`QdrantConnector.search()` (used by the legacy `qdrant_find` tool) was not
audited for the per-request provider refactor. It still uses
`self._embedding_provider` directly. This is fine for the default profile
because `qdrant_find` is gated to `full` only, but if someone enables `full`
profile and shares the server, two clients could see each other's provider.
Low priority because the curated tools (`search_documents`) already replace it.

### 5g. uv lockfile drift on macOS
`uv sync` regenerates the lockfile and we committed a snapshot. If a
contributor runs `uv sync` on a different platform (Linux), the lockfile
will see platform-specific wheels (e.g. CUDA onnxruntime). We currently
have no CI matrix or guidance on this. Not urgent; flag if PRs start
producing noisy lockfile diffs.

### 5h. macOS metadata extraction blocks the event loop
`get_macos_metadata()` shells out to `mdls` + `xattr` synchronously inside
async tool handlers. For folder ingest of 1000s of files this serializes
the spawns and adds latency. Should run in a thread pool executor.

---

## 6. Next-session priorities (ordered)

> Each priority has: scope, why it matters, files touched, exit criteria,
> and an estimated effort. Do them in this order unless you have a reason
> to deviate. **Don't bundle priorities into one giant commit.**

### Priority 1 — `outputSchema` per priority tool 🔴 high value
**Why:** the brief explicitly required this; without it, agent clients
can't introspect tool return shapes. Strict MCP clients will see
unschema'd tools.

**Approach:** post-process FunctionTool objects after registration. After
`self.tool(...)(fn)` returns the `FunctionTool`, write its `outputSchema`
metadata directly. The fastmcp `FunctionTool` exposes
`output_schema: dict | None` (verify in 2.8 source). If not, attach via
`tool.annotations["outputSchema"] = ...` and fall back at protocol level.

**Per-tool schemas needed:**
- `search_documents` — full schema given in the original brief
- `ingest_file` — `{contract, data: {filename, document_id, chunks_stored, extractor_used, char_count, page_count}, observability}`
- `ingest_folder` — `{contract, data: {folder, files_processed, files_total, chunks_stored, errors[]}, observability}` plus the `mode=report` variant `{contract, data: {mode, plan_id, plan, expires_at}, observability}`
- `create_collection`, `create_hybrid_collection` — `{contract, data: {collection_name, vector_size, distance, embedding_model, hybrid}, observability}`
- `bootstrap_collection_indexes` — `{contract, data: {collection, indexes_ensured: string[]}, observability}`
- Discovery tools — define schemas matching `mcp_runtime/discovery.py` payloads
- `delete_collection` — split schema for report vs apply variants

**Files:**
- `src/mcp_server_qdrant/mcp_runtime/schemas.py` (new) — JSON Schema definitions
- `src/mcp_server_qdrant/mcp_server.py` — extend `_profile_tool` to attach schemas

**Exit criteria:**
1. `tools/list` over MCP includes `outputSchema` for every priority tool
2. Returns conform to schemas (strict subset of envelope is OK)
3. Document the schemas in the README

**Effort:** half a session. Mostly mechanical — define schemas + thread
through the wrapper.

### Priority 2 — test suite 🔴 required
**Why:** acceptance criteria. Also: zero tests means refactoring is
risky.

**Coverage targets:**
1. `mcp_runtime/profiles.py` — `is_tool_visible` for every (tool, profile) pair
2. `mcp_runtime/envelope.py` — success/failure shapes, contract version stable
3. `mcp_runtime/plan_registry.py` — TTL, single-use, cross-tool rejection, expired
4. `mcp_runtime/provider_resolver.py` — explicit > collection > default, cache hit/miss
5. `mcp_runtime/http_security.py` — Origin allow/deny, Bearer present/absent/wrong
6. `search/filter_grammar.py` — every operator, type coercion, ISO date detection
7. `search/document_search.py` — grouping, overfetch, score ordering
8. `ingest/extractor.py` — txt/md frontmatter, PDF fallback path, DOCX
9. **Multi-client integration test** — start the HTTP server, hit it concurrently from two asyncio clients, verify no cross-contamination of provider state. Use fastmcp's test client.
10. `outputSchema` conformance — once Priority 1 lands, validate every priority tool's return against its declared schema.

**Files:**
- `tests/test_profiles.py` (new)
- `tests/test_envelope.py` (new)
- `tests/test_plan_registry.py` (new)
- `tests/test_provider_resolver.py` (new)
- `tests/test_http_security.py` (new)
- `tests/test_filter_grammar.py` (new)
- `tests/test_document_search.py` (new)
- `tests/test_extractor.py` (new)
- `tests/test_multi_client_http.py` (new) — the most important one
- `tests/conftest.py` — fixtures for QdrantConnector with local path, sample fixtures dir for ingestion

**Pin notes:** `pytest-asyncio>=0.23` is already in dev-deps. Use `asyncio_mode = "auto"`. fastmcp has its own test utilities — see <https://gofastmcp.com/v2/testing>.

**Exit criteria:** `uv run pytest` green; >80% coverage on `mcp_runtime/`.

**Effort:** a full focused session.

### Priority 3 — persist `set_collection_embedding_model` assignments 🟡 medium
**Why:** the assignment is lost on restart, which is surprising for users.

**Approach:** simplest path — sidecar JSON file at
`<qdrant_local_path>/_assignments.json` (when local) or env-var-configurable
path (`QDRANT_ASSIGNMENTS_FILE`). On startup, load. On `assign_collection_model`,
write atomically.

For external Qdrant, the file path needs an explicit env var or it ends up
in the working directory. Document this clearly.

**Files:**
- `src/mcp_server_qdrant/mcp_runtime/provider_resolver.py` — add load/save
- `src/mcp_server_qdrant/settings.py` — add the env var

**Effort:** quarter session.

### Priority 4 — async-friendly macOS metadata 🟡 medium
**Why:** ingesting a folder of N files spawns N synchronous `mdls` calls
on the event loop. Folder ingest of 1000s of files is unusably slow.

**Approach:** wrap `subprocess.run` calls in
`loop.run_in_executor`. Even better, batch: `mdls` accepts multiple paths.
Preserve the per-file dict shape.

**Files:**
- `src/mcp_server_qdrant/ingest/macos_metadata.py`

**Effort:** quarter session. Profile a realistic folder before/after.

### Priority 5 — connector quickstart docs 🟢 low priority
**Why:** brief asked for client connector examples (Claude Code, Codex, VS Code).
These live in markdown today. Worth adding sample config files in
`examples/` or `connectors/`.

**Files:**
- `connectors/claude-code.json`
- `connectors/claude-desktop.json`
- `connectors/lm-studio.json`
- `connectors/cursor.json`
- `connectors/vscode.json`
- `README.md` — link them

**Effort:** quarter session.

### Priority 6 — `late_interaction` retrieval mode 🟢 research / future
**Why:** reserved in the enum, mentioned in the brief, but real
implementation is significant work — requires multi-vector collections and
ColBERT-style scoring.

**Approach:** investigate FastEmbed's `LateInteractionTextEmbedding`. Add
`create_late_interaction_collection` connector method. Probably a separate
collection type (third axis of the `vectors_config`).

**Effort:** full session minimum. **Don't start this without concrete user
demand.**

### Priority 7 — evaluation harness 🟢 research / future
**Why:** retrieval-quality choices are hard to validate without metrics.
Brief mentioned BEIR-style nDCG@10 / Recall@k / MRR.

**Approach:** add a `eval/` directory with a small gold set (your own docs
or BEIR scifact), an eval script, and a Markdown table comparing dense vs
hybrid vs rerank.

**Effort:** full session.

---

## 7. Operational reference

### Running the server
```bash
# stdio (default — for Claude Desktop, LM Studio, etc.)
uv run mcp-server-qdrant

# Streamable HTTP for multi-agent local use
uv run mcp-server-qdrant --transport streamable-http --port 8000

# REST API (parallel surface for web UI)
uv run mcp-server-qdrant-webui --host 127.0.0.1 --port 8765
```

### Key environment variables
| Var | Default | Purpose |
|---|---|---|
| `QDRANT_URL` | — | Qdrant HTTP endpoint |
| `QDRANT_LOCAL_PATH` | — | Local file mode (mutually exclusive with URL) |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Default dense model |
| `QDRANT_DEFAULT_VECTOR_SIZE` | `384` | Bump to `4096` for Qwen3-Embedding-8B default |
| `QDRANT_MCP_TOOL_PROFILE` | `canonical` | `minimal`, `canonical`, or `full` |
| `MCP_TRANSPORT` | `stdio` | CLI override: `--transport` |
| `MCP_HOST` | `127.0.0.1` | HTTP bind (loopback only by default) |
| `MCP_PORT` | `8000` | HTTP port |
| `MCP_HTTP_AUTH_TOKEN` | — | Required Bearer token if set |
| `MCP_HTTP_ALLOWED_ORIGINS` | localhost+127.0.0.1 | Comma-separated extra origins |

### Smoke test commands
```bash
# Imports clean, server constructs:
uv run python -c "from mcp_server_qdrant.mcp_server import QdrantMCPServer; print('OK')"

# Tool registration under each profile:
QDRANT_MCP_TOOL_PROFILE=minimal uv run python -c "..."  # see commit 4e42424 for full snippet

# REST API smoke:
uv run mcp-server-qdrant-webui --port 8765 &
curl http://127.0.0.1:8765/health
```

### Git remotes
```
origin       → angrysky56/mcp-server-qdrant-enhanced (read-only upstream of fork chain)
upstream     → qdrant/mcp-server-qdrant (original)
macos-fork   → juangrukat/mcp-server-qdrant-enhanced-MacOS (this fork — push here)
```

The `master` branch tracks `macos-fork/master`.

---

## 8. Decisions log

> Why we chose X over Y. Read this before "improving" something — the
> alternative was probably already considered.

| Decision | Why |
|---|---|
| fork name `mcp-server-qdrant-enhanced-MacOS` | macOS Spotlight integration is the differentiator; explicit OS suffix avoids confusion with the Linux/cross-platform parent fork |
| public repo | builds on a public fork chain; private would be friction without benefit |
| local working dir kept as `mcp-server-qdrant-enhanced/` | renaming risks tool calls and shell history |
| logical commits, not one big commit | brief explicitly requested this; review-friendly |
| fastmcp pinned `>=2.7,<3` | bounded but flexible; 2.8 verified to expose Streamable HTTP cleanly |
| Streamable HTTP over SSE | spec-recommended for shared multi-client local servers |
| `127.0.0.1` default bind | DNS rebinding mitigation; explicit override required for non-loopback |
| Bearer token optional | defense in depth; MCP doesn't standardize auth, so we make it env-driven |
| envelope `contract_version: "1.0"` fixed | bump on shape change; clients can rely on stability today |
| Qwen3 surfaced via `SUPPLEMENTAL_MODELS` | fastembed's `list_supported_models()` doesn't always include feature-gated models; this is the cleanest fallback |
| sparse default = `Qdrant/bm25` | lightweight, no model download; SPLADE++ is heavier and often not worth the trouble for general doc retrieval |
| reranker default = `Xenova/ms-marco-MiniLM-L-6-v2` | fastembed-friendly, fast cross-encoder; Qwen3-Reranker-4B is a stub because it needs torch+transformers (not currently dependencies) |
| `mcp_runtime/` submodule (not `mcp/`) | `mcp` would shadow the top-level `mcp` SDK package |
| `set_collection_embedding_model` no longer mutates global state | multi-agent safety (intentional API change, documented) |
| profile default = `canonical` | minimal is too restrictive for typical use; full is too loud; canonical is the curated daily surface |
| report/apply only on `delete_collection` (required) and `ingest_folder` (opt-in) | brief scope; add others only when they exist and are meaningfully destructive |
| `bootstrap_collection_indexes` NOT gated | idempotent; adding gating would be friction |
| envelope migration is layered, not flag day | preserve backward compatibility on legacy `qdrant_find` / `qdrant_store` |
| no tests this round | scope; budgeted for next session as Priority 2 |

---

## 9. How to start the next session

1. Read this file top-to-bottom.
2. `git fetch macos-fork && git status` — confirm clean tree, nothing pending.
3. Pick a Priority from §6. Don't skip P1/P2 unless you have a strong reason.
4. For each commit you produce: keep it logical, single-purpose, with a
   clear subject line and body. Match the existing style:
   - `feat(area): subject` — new features
   - `fix(area): subject` — bug fixes
   - `docs(area): subject` — documentation only
   - `test(area): subject` — tests only
   - `refactor(area): subject` — restructure without behavior change
5. Run smoke tests after each commit (see §7).
6. When you finish a Priority, **update §4 and §6 in this file** to reflect
   the new state. Bump `Last updated` at the top.
7. Push to `macos-fork master`. Don't force-push.

---

## 10. Open questions for the human

These are decisions that need user input before they can be made:

1. **Schema-first or behavior-first for outputSchema?** Should we extend
   the envelope to include schema URLs (`$id`) so clients can fetch them,
   or keep schemas inline in `tools/list` only?
2. **Should the default profile change?** Currently `canonical`. Some
   deployments might want `minimal` as a stricter default for
   agent-as-untrusted-client scenarios.
3. **Is Qwen3-Reranker actually needed?** It requires adding
   torch+transformers as a dependency (~4 GB install). The
   FastEmbed cross-encoder default is fast and decent. Drop the Qwen3
   reranker stub or commit to implementing it?
4. **CI matrix.** Worth setting up GitHub Actions to run `pytest` on
   ubuntu-latest + macos-latest? We have a `pytest.yaml` workflow but it
   was pre-existing for the upstream fork — not validated.
5. **Versioning.** `pyproject.toml` says `version = "0.7.1"` (inherited
   from upstream). The envelope's `toolset_version` is `"0.8.0"`. Should
   we bump pyproject to `0.8.0` and tag a release?

---

*End of brief. Update §4, §6, and the timestamp when you finish work.*
