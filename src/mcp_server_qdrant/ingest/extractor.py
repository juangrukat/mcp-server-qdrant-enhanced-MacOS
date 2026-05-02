"""
Text extraction for ingest pipeline.
Priority per format:
  .txt / .md  → direct UTF-8 read (charset fallback)
  .pdf        → pdfminer.six primary, pypdf fallback
  .docx       → python-docx
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

# Max chars per chunk; overlap in chars
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150


@dataclass
class ExtractedDocument:
    text: str
    extractor_used: str
    char_count: int
    page_count: int | None = None
    error: str | None = None


@dataclass
class Chunk:
    text: str
    chunk_index: int
    total_chunks: int
    metadata: dict = field(default_factory=dict)


def extract_text(path: str) -> ExtractedDocument:
    """Dispatch to the right extractor based on file extension."""
    ext = Path(path).suffix.lower()
    if ext in (".txt", ".md"):
        return _extract_plain(path)
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    return ExtractedDocument(
        text="",
        extractor_used="none",
        char_count=0,
        error=f"Unsupported file type: {ext}",
    )


def build_chunks(doc: ExtractedDocument, file_metadata: dict) -> list[Chunk]:
    """
    Split extracted text into overlapping chunks.
    Splits on paragraph boundaries first, then hard-cuts long paragraphs.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", doc.text) if p.strip()]
    raw_chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > CHUNK_SIZE:
            # Hard split the oversized paragraph
            if current:
                raw_chunks.append(current)
                current = ""
            for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                raw_chunks.append(para[i : i + CHUNK_SIZE])
        elif len(current) + len(para) + 2 > CHUNK_SIZE:
            raw_chunks.append(current)
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para

    if current:
        raw_chunks.append(current)

    total = len(raw_chunks)
    chunks = []
    for i, text in enumerate(raw_chunks):
        chunk_meta = {**file_metadata, "chunk_index": i, "total_chunks": total}
        chunks.append(Chunk(text=text, chunk_index=i, total_chunks=total, metadata=chunk_meta))
    return chunks


# --- Plain text ---

def _extract_plain(path: str) -> ExtractedDocument:
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = Path(path).read_text(encoding=enc)
            # Strip YAML/TOML frontmatter from markdown
            if path.endswith(".md"):
                text = _strip_frontmatter(text)
            return ExtractedDocument(
                text=text,
                extractor_used=f"plain-{enc}",
                char_count=len(text),
            )
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return ExtractedDocument(text="", extractor_used="plain", char_count=0, error=str(e))
    return ExtractedDocument(text="", extractor_used="plain", char_count=0, error="Could not decode file")


def _strip_frontmatter(text: str) -> str:
    """Remove YAML (---) or TOML (+++) frontmatter from markdown."""
    for fence in ("---", "+++"):
        if text.startswith(fence):
            end = text.find(fence, len(fence))
            if end != -1:
                return text[end + len(fence):].lstrip("\n")
    return text


# --- PDF ---

def _extract_pdf(path: str) -> ExtractedDocument:
    text, pages, extractor = _pdf_pdfminer(path)
    if not text:
        text, pages, extractor = _pdf_pypdf(path)
    if not text:
        return ExtractedDocument(text="", extractor_used="pdf-failed", char_count=0, error="All PDF extractors returned empty text")
    return ExtractedDocument(text=text, extractor_used=extractor, char_count=len(text), page_count=pages)


def _pdf_pdfminer(path: str) -> tuple[str, int | None, str]:
    try:
        from pdfminer.high_level import extract_text as pm_extract
        from pdfminer.high_level import extract_pages
        text = pm_extract(path)
        pages = sum(1 for _ in extract_pages(path))
        return (text or "").strip(), pages, "pdfminer"
    except Exception as e:
        logger.debug(f"pdfminer failed for {path}: {e}")
        return "", None, "pdfminer"


def _pdf_pypdf(path: str) -> tuple[str, int | None, str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = len(reader.pages)
        text = "\n\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()
        return text, pages, "pypdf"
    except Exception as e:
        logger.debug(f"pypdf failed for {path}: {e}")
        return "", None, "pypdf"


# --- DOCX ---

def _extract_docx(path: str) -> ExtractedDocument:
    try:
        from docx import Document
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        return ExtractedDocument(
            text=text,
            extractor_used="python-docx",
            char_count=len(text),
        )
    except Exception as e:
        return ExtractedDocument(text="", extractor_used="python-docx", char_count=0, error=str(e))
