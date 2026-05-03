"""
Lightweight tests for the REST API route structure.

These tests verify that routes are registered correctly and that
request/response models behave as expected, without requiring a real Qdrant
connection. Qdrant and embedding calls are mocked at the connector level.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcp_server_qdrant.webui.api import create_app


def _build_test_app():
    """Create a REST app with a mocked QdrantConnector."""
    mock_connector = MagicMock()
    mock_connector.get_collection_names = AsyncMock(return_value=["docs", "hybrid_test"])
    mock_connector.get_sparse_vector_name = AsyncMock(return_value=None)
    mock_connector.create_hybrid_collection = AsyncMock(return_value=True)
    mock_connector.ensure_macos_metadata_indexes = AsyncMock()

    mock_mgr = MagicMock()
    mock_model_info = MagicMock()
    mock_model_info.vector_size = 2560
    mock_mgr.get_model_info = MagicMock(return_value=mock_model_info)

    mock_provider = MagicMock()
    mock_provider.get_vector_name = MagicMock(return_value="qwen3-qwen3-embedding-4b")
    mock_provider.get_model_name = MagicMock(return_value="Qwen/Qwen3-Embedding-4B")
    mock_provider.get_vector_size = MagicMock(return_value=2560)
    mock_mgr.create_provider_for_model = MagicMock(return_value=mock_provider)

    class _FakeQueueStats:
        max_concurrency = 1
        max_queue_size = 8
        running = 0
        waiting = 0

    # Patch the constructor so create_app uses our mock objects
    with patch("mcp_server_qdrant.webui.api.QdrantConnector", return_value=mock_connector), \
         patch("mcp_server_qdrant.webui.api.EnhancedEmbeddingModelManager", return_value=mock_mgr), \
         patch("mcp_server_qdrant.webui.api.WriteQueue") as mock_wq_cls:
        mock_wq = MagicMock()
        mock_wq.stats = AsyncMock(return_value=_FakeQueueStats())
        mock_wq_cls.return_value = mock_wq
        app = create_app()

    return app, mock_connector


def test_post_collections_hybrid_route_exists():
    """POST /collections/hybrid is registered as a distinct route."""
    app, _ = _build_test_app()
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/collections/hybrid" in routes


def test_post_collections_hybrid_calls_create_hybrid_collection():
    """POST /collections/hybrid calls connector.create_hybrid_collection with correct args."""
    app, mock_connector = _build_test_app()
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.post(
        "/collections/hybrid",
        json={
            "collection_name": "my_hybrid",
            "embedding_model": "Qwen/Qwen3-Embedding-4B",
            "distance": "cosine",
        },
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["collection_name"] == "my_hybrid"
    assert data["sparse_vector_name"] == "sparse-bm25"
    assert data["dense_vector_name"] == "qwen3-qwen3-embedding-4b"
    mock_connector.create_hybrid_collection.assert_called_once()


def test_collections_hybrid_route_not_swallowed_by_parameterized_route():
    """
    POST /collections/hybrid must not be caught by DELETE /collections/{name}.

    The two routes share the path pattern but differ on HTTP method —
    FastAPI routes by (method, path). Verify that a POST to /collections/hybrid
    reaches our handler (201) and not the DELETE handler (which would 405).
    """
    app, _ = _build_test_app()
    client = TestClient(app, raise_server_exceptions=True)

    # If the route were swallowed by the DELETE handler, this would return 405.
    resp = client.post(
        "/collections/hybrid",
        json={"collection_name": "test_col", "embedding_model": "Qwen/Qwen3-Embedding-4B"},
    )
    assert resp.status_code == 201, (
        f"Expected 201 from POST /collections/hybrid, got {resp.status_code}: {resp.text}"
    )
