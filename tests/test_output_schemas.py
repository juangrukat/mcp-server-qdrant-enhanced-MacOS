import asyncio

from mcp_server_qdrant.mcp_server import QdrantMCPServer
from mcp_server_qdrant.settings import (
    EmbeddingProviderSettings,
    QdrantSettings,
    ToolSettings,
)


def test_priority_tools_have_output_schemas(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    monkeypatch.delenv("QDRANT_LOCAL_PATH", raising=False)
    server = QdrantMCPServer(
        tool_settings=ToolSettings(),
        qdrant_settings=QdrantSettings(),
        embedding_provider_settings=EmbeddingProviderSettings(),
        name="schema-test",
    )

    tools = asyncio.run(server.get_tools())

    for name in ("search_documents", "ingest_file", "ingest_folder", "get_supported_extractors"):
        assert name in tools
        assert tools[name].output_schema
        assert tools[name].output_schema["type"] == "object"
