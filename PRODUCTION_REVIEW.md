# Production Review Notes

Last reviewed: 2026-05-03.

## Verification Run

- `uv run --locked pytest -q` passes.
- `uv run --locked ruff check src tests --output-format concise` passes.
- `uv run --locked python -m compileall -q src/mcp_server_qdrant` passes.
- Stdio transport and concurrent streamable HTTP clients are covered by pytest.
- Late-interaction storage/search has unit coverage and an in-memory smoke path.

## Remaining Limitations

- OCR is not implemented. PDF preflight detects likely scanned/image-only PDFs
  and fails early with an OCR-needed message instead of spending time on full
  text extraction.
- PDF preflight samples only the first few pages. Mixed PDFs can still have
  later image-only pages that are not OCRed.
- Only FastEmbed is a runtime embedding provider. `FlagEmbedding`/BGE is covered
  by an optional smoke test but is not wired as a provider.
- Late-interaction retrieval requires late-interaction collections and ingestion;
  dense/hybrid collections cannot be queried with `mode="late_interaction"`.
- Late-interaction multivectors use more storage and ingest time than dense
  vectors.
- Chunking is still paragraph-aware character chunking, not semantic or
  language-aware chunking.
- Large-folder throughput has not been load tested. Expected bottlenecks are
  PDF extraction, embedding compute, Qdrant upserts, and macOS metadata
  subprocesses.
- `.docx` paragraphs and tables are extracted, but embedded images are not.
- macOS metadata is best-effort. On non-macOS platforms or Spotlight failures,
  base filesystem metadata is still collected but Finder/Spotlight fields may
  be empty.

## Notes For Follow-Up

- Add OCR as an explicit optional pipeline, likely behind configuration, rather
  than silently adding a heavyweight dependency.
- Add a real load test fixture for large folder ingestion before claiming
  throughput numbers.
- Consider provider plugin interfaces after FastEmbed behavior stabilizes.
