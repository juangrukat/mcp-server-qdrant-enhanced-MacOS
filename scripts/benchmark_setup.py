import asyncio
import sys
import time
from pathlib import Path

from mcp_server_qdrant.settings import QdrantSettings, EmbeddingProviderSettings
from mcp_server_qdrant.qdrant import QdrantConnector, BatchEntry
from mcp_server_qdrant.embeddings.factory import create_embedding_provider
from mcp_server_qdrant.embeddings.sparse import SparseEmbeddingProvider
from mcp_server_qdrant.embeddings.late_interaction import LateInteractionEmbeddingProvider, DEFAULT_LATE_INTERACTION_MODEL
from mcp_server_qdrant.ingest.extractor import extract_text, build_chunks

PDF_PATH = "/Users/kat/Documents/50_LIBRARY/Books_&_Reading/calibre_library/socratic_method/socratic_circles_fostering_critical_and_c-matt_copeland.pdf"

qs = QdrantSettings()
es = EmbeddingProviderSettings()
ep = create_embedding_provider(es)

async def main():
    conn = QdrantConnector(qs.location, qs.api_key, None, ep, qs.local_path)
    existing = await conn.get_collection_names()
    print(f"Existing collections: {existing}")
    
    # Create late_interaction collection if it doesn't exist
    if "default_li" not in existing:
        print("=== Creating late_interaction collection ===")
        li = LateInteractionEmbeddingProvider(DEFAULT_LATE_INTERACTION_MODEL)
        vs = li.get_vector_size()
        vn = li.get_vector_name()
        print(f"  vector_size={vs}, vector_name={vn}")
        ok = await conn.create_late_interaction_collection("default_li", vs, vn)
        print(f"Created default_li: {ok}")
    else:
        li = LateInteractionEmbeddingProvider(DEFAULT_LATE_INTERACTION_MODEL)
    
    existing = await conn.get_collection_names()
    print(f"Collections now: {existing}")
    
    # Extract text once
    print(f"\n=== Extracting text ===")
    t0 = time.time()
    doc = extract_text(str(PDF_PATH))
    et = time.time() - t0
    print(f"Extracted {doc.char_count} chars, {doc.page_count} pages in {et:.1f}s")
    
    # Build chunks
    file_meta = {
        "path": str(PDF_PATH), "filename": Path(PDF_PATH).name,
        "extractor_used": doc.extractor_used, "char_count": doc.char_count,
        "page_count": doc.page_count,
    }
    chunks = build_chunks(doc, file_meta)
    entries = [BatchEntry(content=c.text, metadata=c.metadata) for c in chunks]
    print(f"Built {len(entries)} chunks")
    
    # Ingest into collections that don't have data yet
    for col_name in ["default_hybrid", "default_li"]:
        info = await conn.get_detailed_collection_info(col_name)
        if info and info.points_count > 0:
            print(f"\n{col_name}: already has {info.points_count} points, skipping")
            continue
        
        print(f"\n=== Ingesting into {col_name} ===")
        t0 = time.time()
        if col_name == "default_hybrid":
            sp = SparseEmbeddingProvider("Qdrant/bm25")
            n = await conn.batch_store_hybrid(entries, col_name, sp)
        elif col_name == "default_li":
            li_p = LateInteractionEmbeddingProvider(DEFAULT_LATE_INTERACTION_MODEL)
            n = await conn.batch_store_late_interaction(entries, col_name, li_p)
        print(f"Stored {n} chunks in {time.time()-t0:.1f}s")
    
    # Check default collection (should already have data from REST ingest)
    info = await conn.get_detailed_collection_info("default")
    if info and info.points_count > 0:
        print(f"\ndefault: already has {info.points_count} points, skipping")
    else:
        print(f"\n=== Ingesting into default ===")
        t0 = time.time()
        n = await conn.batch_store(entries, "default")
        print(f"Stored {n} chunks in {time.time()-t0:.1f}s")
    
    # Verify all
    print("\n=== Final state ===")
    for col_name in ["default", "default_hybrid", "default_li"]:
        info = await conn.get_detailed_collection_info(col_name)
        if info:
            print(f"  {col_name}: {info.points_count} points, vector_size={info.vector_size}, status={info.status}")
        else:
            print(f"  {col_name}: NOT FOUND")

asyncio.run(main())
