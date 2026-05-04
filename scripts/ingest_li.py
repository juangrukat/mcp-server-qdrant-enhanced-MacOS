import asyncio, time
from pathlib import Path
from mcp_server_qdrant.settings import QdrantSettings, EmbeddingProviderSettings
from mcp_server_qdrant.qdrant import QdrantConnector, BatchEntry
from mcp_server_qdrant.embeddings.factory import create_embedding_provider
from mcp_server_qdrant.embeddings.late_interaction import LateInteractionEmbeddingProvider, DEFAULT_LATE_INTERACTION_MODEL
from mcp_server_qdrant.ingest.extractor import extract_text, build_chunks

PDF = "/Users/kat/Documents/50_LIBRARY/Books_&_Reading/calibre_library/socratic_method/socratic_circles_fostering_critical_and_c-matt_copeland.pdf"

qs = QdrantSettings(); es = EmbeddingProviderSettings()
ep = create_embedding_provider(es)
li = LateInteractionEmbeddingProvider(DEFAULT_LATE_INTERACTION_MODEL)

async def main():
    conn = QdrantConnector(qs.location, qs.api_key, None, ep, qs.local_path)
    
    info = await conn.get_detailed_collection_info("default_li")
    if info and info.points_count > 0:
        print(f"default_li already has {info.points_count} points")
        return
    
    print("Extracting...")
    doc = extract_text(str(PDF))
    print(f"  {doc.char_count} chars, {doc.page_count} pages")
    
    file_meta = {"path": str(PDF), "filename": Path(PDF).name, "extractor_used": doc.extractor_used, "char_count": doc.char_count, "page_count": doc.page_count}
    chunks = build_chunks(doc, file_meta)
    entries = [BatchEntry(content=c.text, metadata=c.metadata) for c in chunks]
    print(f"  {len(entries)} chunks")
    
    print(f"Ingesting into default_li...")
    t0 = time.time()
    n = await conn.batch_store_late_interaction(entries, "default_li", li)
    print(f"  Stored {n} chunks in {time.time()-t0:.1f}s")
    
    info = await conn.get_detailed_collection_info("default_li")
    print(f"  Verified: {info.points_count} points")

asyncio.run(main())
