"""
Enhanced MCP server with improved embedding management and API key security.
"""

import json
import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field
from qdrant_client import models

from mcp_server_qdrant.common.filters import make_indexes
from mcp_server_qdrant.common.func_tools import make_partial_function
from mcp_server_qdrant.common.wrap_filters import wrap_filters
from mcp_server_qdrant.embedding_manager import EnhancedEmbeddingModelManager
from mcp_server_qdrant.mcp_runtime.profiles import ToolProfile, is_tool_visible
from mcp_server_qdrant.qdrant import ArbitraryFilter, Entry, QdrantConnector, BatchEntry
from mcp_server_qdrant.settings import (
    EmbeddingProviderSettings,
    QdrantSettings,
    ToolSettings,
)

logger = logging.getLogger(__name__)


class QdrantMCPServer(FastMCP):
    """
    Enhanced MCP server with improved embedding management and collection handling.
    Includes graceful error handling for different MCP clients (LM Studio, Claude Desktop, etc.)
    """

    def __init__(
        self,
        tool_settings: ToolSettings,
        qdrant_settings: QdrantSettings,
        embedding_provider_settings: EmbeddingProviderSettings,
        name: str = "mcp-server-qdrant",
        instructions: str | None = None,
        **settings: Any,
    ):
        try:
            self.tool_settings = tool_settings
            self.qdrant_settings = qdrant_settings
            self.embedding_provider_settings = embedding_provider_settings

            # Initialize enhanced embedding model manager
            self.embedding_manager = EnhancedEmbeddingModelManager(embedding_provider_settings)

            # Use the default provider from the simplified embedding manager
            self.embedding_provider = self.embedding_manager.get_default_provider()

            # Sparse provider is lazily initialized on first hybrid operation
            self._sparse_provider = None

            # Active MCP tool profile (minimal | canonical | full)
            self.active_profile = ToolProfile.parse(qdrant_settings.mcp_tool_profile)

            # Initialize Qdrant connector with secure connection handling
            self.qdrant_connector = self._create_secure_qdrant_connector()



            super().__init__(name=name, instructions=instructions, **settings)

            self.setup_tools()
            if self.qdrant_settings.enable_resources:
                self.setup_resources()

        except Exception as e:
            logger.error(f"Failed to initialize MCP server: {e}")
            # For MCP clients, we need to fail gracefully
            raise RuntimeError(f"MCP server initialization failed: {e}") from e

    def _create_secure_qdrant_connector(self) -> QdrantConnector:
        """Create Qdrant connector with proper security handling."""
        # Only pass API key if the connection is secure (https) or local
        api_key = self.qdrant_settings.api_key
        location = self.qdrant_settings.location

        if api_key and location:
            # Check if connection is secure
            if not (location.startswith("https://") or
                    location.startswith("localhost") or
                    location.startswith("127.0.0.1") or
                    location.startswith("http://localhost") or
                    location.startswith("http://127.0.0.1")):
                logger.warning("Insecure connection detected. API key will not be sent over insecure connection.")
                api_key = None

        return QdrantConnector(
            location,
            api_key,
            self.qdrant_settings.collection_name,
            self.embedding_provider,
            self.qdrant_settings.local_path,
            make_indexes(self.qdrant_settings.filterable_fields_dict()),
        )

    def get_sparse_provider(self):
        """Lazily initialize and cache the sparse embedding provider."""
        if self._sparse_provider is None:
            from mcp_server_qdrant.embeddings.sparse import SparseEmbeddingProvider
            self._sparse_provider = SparseEmbeddingProvider()
        return self._sparse_provider

    def _profile_tool(self, *, name: str | None = None, **kwargs):
        """
        Profile-aware replacement for ``self.tool``. If the tool's required
        profile exceeds the active profile, registration is skipped (the
        function still defines normally — it just isn't visible to MCP clients).

        Drop-in for ``@self._profile_tool(...)``:
            ``@self._profile_tool(description="...")`` uses the wrapped fn name
            ``@self._profile_tool(name="qdrant_find", description="...")`` overrides it
        """
        def decorator(fn):
            check_name = name or fn.__name__
            if not is_tool_visible(check_name, self.active_profile):
                logger.info(f"Skipping tool '{check_name}' under profile '{self.active_profile.name.lower()}'")
                return fn
            registry_kwargs = dict(kwargs)
            if name is not None:
                registry_kwargs["name"] = name
            return self.tool(**registry_kwargs)(fn)
        return decorator

    def _register_legacy_tool(self, tool_name: str, fn, description: str) -> None:
        """Register a tool via the old ``self.tool(name=..., description=...)(fn)`` path,
        respecting the active profile."""
        if not is_tool_visible(tool_name, self.active_profile):
            logger.info(f"Skipping legacy tool '{tool_name}' under profile '{self.active_profile.name.lower()}'")
            return
        fn.__name__ = tool_name
        self.tool(name=tool_name, description=description)(fn)

    def format_entry(self, entry: Entry) -> str:
        """Format an entry for display."""
        entry_metadata = json.dumps(entry.metadata) if entry.metadata else ""
        return f"<entry><content>{entry.content}</content><metadata>{entry_metadata}</metadata></entry>"

    def setup_tools(self) -> None:
        """Register all tools in the server."""

        # Core find tool with enhanced embedding support
        async def find(
            ctx: Context,
            query: Annotated[str, Field(description="What to search for")],
            collection_name: Annotated[str, Field(description="The collection to search in")],
            query_filter: ArbitraryFilter | None = None,
        ) -> list[str]:
            """Find memories in Qdrant."""
            try:
                filter_obj = models.Filter(**query_filter) if query_filter else None

                entries = await self.qdrant_connector.search(
                    query,
                    collection_name=collection_name,
                    limit=self.qdrant_settings.search_limit,
                    query_filter=filter_obj,
                )

                if not entries:
                    return [f"No information found for the query '{query}'"]

                content = [f"Results for the query '{query}'"]
                for entry in entries:
                    content.append(self.format_entry(entry))
                return content

            except Exception as e:
                await ctx.debug(f"Error in find: {e}")
                return [f"Error searching: {str(e)}"]

        # Enhanced store tool
        async def qdrant_store(
            ctx: Context,
            content: Annotated[str, Field(description="Text content to store")],
            collection_name: Annotated[str, Field(description="Collection to store the information in")],
            metadata: Annotated[str | None, Field(description="Optional metadata as JSON string")] = None,
            entry_id: Annotated[str | None, Field(description="Optional custom ID for the entry")] = None,
        ) -> str:
            """Store information in Qdrant with optional metadata."""
            try:
                await ctx.debug(f"Storing content in collection '{collection_name}'")

                # Parse metadata from JSON string
                parsed_metadata = None
                if metadata:
                    try:
                        parsed_metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        return f"Invalid metadata JSON: {metadata}"

                # Create entry
                batch_entry = BatchEntry(
                    content=content,
                    metadata=parsed_metadata,
                    id=entry_id
                )

                stored_count = await self.qdrant_connector.batch_store([batch_entry], collection_name)

                if stored_count > 0:
                    # Record the model mapping for this collection if not already stored
                    model_name = self.embedding_provider.get_model_name()
                    vector_size = self.embedding_provider.get_vector_size()
                    await ctx.debug(f"Recorded model mapping: {collection_name} -> {model_name} ({vector_size}D)")

                    return f"Successfully stored entry in collection '{collection_name}'"
                else:
                    return f"Failed to store entry in collection '{collection_name}'"

            except Exception as e:
                await ctx.debug(f"Error storing content: {e}")
                return f"Error storing content: {str(e)}"

        # Register tools with appropriate filters
        filterable_conditions = self.qdrant_settings.filterable_fields_dict_with_conditions()

        find_tool = find
        if len(filterable_conditions) > 0:
            find_tool = wrap_filters(find_tool, filterable_conditions)
        elif not self.qdrant_settings.allow_arbitrary_filter:
            find_tool = make_partial_function(find_tool, {"query_filter": None})

        if self.qdrant_settings.collection_name:
            find_tool = make_partial_function(
                find_tool, {"collection_name": self.qdrant_settings.collection_name}
            )

        self._register_legacy_tool("qdrant_find", find_tool, self.tool_settings.tool_find_description)

        if not self.qdrant_settings.read_only:
            store_tool = qdrant_store
            if self.qdrant_settings.collection_name:
                store_tool = make_partial_function(
                    store_tool, {"collection_name": self.qdrant_settings.collection_name}
                )

            self._register_legacy_tool("qdrant_store", store_tool, self.tool_settings.tool_store_description)

        # Add enhanced tools if enabled
        if self.qdrant_settings.enable_collection_management:
            self.setup_collection_management_tools()

        if self.qdrant_settings.enable_dynamic_embedding_models:
            self.setup_embedding_model_tools()

        self.setup_advanced_search_tools()

        if not self.qdrant_settings.read_only:
            self.setup_ingest_tools()

        self.setup_discovery_tools()

    def setup_collection_management_tools(self):
        """Setup enhanced collection management tools."""

        @self._profile_tool(description=self.tool_settings.tool_list_collections_description)
        async def list_collections(ctx: Context) -> list[str]:
            """List all available Qdrant collections."""
            try:
                collections = await self.qdrant_connector.get_collection_names()
                if not collections:
                    return ["No collections found"]
                return [f"Available collections: {', '.join(collections)}"]
            except Exception as e:
                await ctx.debug(f"Error listing collections: {e}")
                return [f"Error listing collections: {str(e)}"]

        @self._profile_tool(description=self.tool_settings.tool_get_collection_info_description)
        async def get_collection_info(
            ctx: Context,
            collection_name: Annotated[str, Field(description="Name of the collection to get info about")]
        ) -> list[str]:
            """Get detailed information about a specific collection."""
            try:
                info = await self.qdrant_connector.get_detailed_collection_info(collection_name)
                if not info:
                    return [f"Collection '{collection_name}' not found"]

                result = [
                    f"Collection Information for '{collection_name}':",
                    f"Points: {info.points_count:,}",
                    f"Vectors: {info.vectors_count:,}",
                    f"Indexed Vectors: {info.indexed_vectors_count:,}",
                    f"Segments: {info.segments_count}",
                    f"Status: {info.status}",
                    f"Optimizer Status: {info.optimizer_status}",
                    f"Vector Size: {info.vector_size or 'Unknown'}",
                    f"Distance Metric: {info.distance_metric or 'Unknown'}"
                ]

                return result
            except Exception as e:
                await ctx.debug(f"Error getting collection info: {e}")
                return [f"Error getting collection info: {str(e)}"]

        if not self.qdrant_settings.read_only:
            @self._profile_tool(description=self.tool_settings.tool_create_collection_description)
            async def create_collection(
                ctx: Context,
                collection_name: Annotated[str, Field(description="Name of the collection to create")],
                embedding_model: Annotated[str, Field(description="Embedding model, e.g. 'Qwen/Qwen3-Embedding-8B' or 'sentence-transformers/all-MiniLM-L6-v2'")],
                vector_size: Annotated[int, Field(description="Vector size override — 0 means infer from model")] = 0,
                distance: Annotated[str, Field(description="Distance metric: cosine, dot, euclidean, manhattan")] = "cosine",
            ) -> dict:
                """Create a new collection with specified parameters."""
                from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from
                profile = self.active_profile.name.lower()
                with envelope_context(profile) as acc:
                    try:
                        model_info = self.embedding_manager.get_model_info(embedding_model)
                        if not model_info:
                            return failure_from(
                                acc,
                                code="unknown_embedding_model",
                                message=f"Unknown embedding model: '{embedding_model}'. Use list_embedding_models to see options.",
                                profile=profile,
                            )

                        resolved_size = vector_size or model_info.vector_size
                        if vector_size and vector_size != model_info.vector_size:
                            if vector_size > model_info.vector_size:
                                return failure_from(
                                    acc,
                                    code="invalid_vector_size",
                                    message=f"Requested vector_size {vector_size} exceeds model max {model_info.vector_size} for '{embedding_model}'.",
                                    profile=profile,
                                )
                            acc.warnings.append(
                                f"Using custom vector_size {vector_size} (model supports up to {model_info.vector_size})"
                            )
                        vector_size = resolved_size

                        ok = await self.qdrant_connector.create_collection_with_config(
                            collection_name, vector_size, distance
                        )
                        if not ok:
                            return failure_from(acc, code="create_failed", message=f"Failed to create collection '{collection_name}'", profile=profile, retryable=True)

                        return success_from(
                            acc,
                            data={
                                "collection_name": collection_name,
                                "vector_size": vector_size,
                                "distance": distance,
                                "embedding_model": embedding_model,
                                "hybrid": False,
                            },
                            profile=profile,
                        )
                    except Exception as e:
                        await ctx.debug(f"Error creating collection: {e}")
                        return failure_from(acc, code="internal_error", message=str(e), profile=profile, retryable=True)

            @self._profile_tool(description=self.tool_settings.tool_create_hybrid_collection_description)
            async def create_hybrid_collection(
                ctx: Context,
                collection_name: Annotated[str, Field(description="Name of the hybrid collection to create")],
                embedding_model: Annotated[str, Field(description="Dense embedding model, e.g. 'Qwen/Qwen3-Embedding-8B'")],
                sparse_model: Annotated[str, Field(description="Sparse model, default 'Qdrant/bm25'")] = "Qdrant/bm25",
                distance: Annotated[str, Field(description="Distance metric")] = "cosine",
            ) -> dict:
                """Create a collection with both dense and sparse vector slots for RRF hybrid search."""
                from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from
                profile = self.active_profile.name.lower()
                with envelope_context(profile) as acc:
                    try:
                        info = self.embedding_manager.get_model_info(embedding_model)
                        if not info:
                            return failure_from(acc, code="unknown_embedding_model", message=f"Unknown dense model: '{embedding_model}'.", profile=profile)
                        dense_provider = self.embedding_manager.create_provider_for_model(embedding_model)
                        from mcp_server_qdrant.embeddings.sparse import SparseEmbeddingProvider
                        sparse_provider = SparseEmbeddingProvider(sparse_model)
                        self._sparse_provider = sparse_provider

                        ok = await self.qdrant_connector.create_hybrid_collection(
                            collection_name=collection_name,
                            dense_size=info.vector_size,
                            dense_vector_name=dense_provider.get_vector_name(),
                            sparse_vector_name=sparse_provider.get_vector_name(),
                            distance=distance,
                        )
                        if not ok:
                            return failure_from(acc, code="create_failed", message=f"Failed to create hybrid collection '{collection_name}'", profile=profile, retryable=True)
                        await self.qdrant_connector.ensure_macos_metadata_indexes(collection_name)

                        return success_from(
                            acc,
                            data={
                                "collection_name": collection_name,
                                "vector_size": info.vector_size,
                                "distance": distance,
                                "embedding_model": embedding_model,
                                "sparse_model": sparse_model,
                                "hybrid": True,
                            },
                            profile=profile,
                        )
                    except Exception as e:
                        await ctx.debug(f"Error creating hybrid collection: {e}")
                        return failure_from(acc, code="internal_error", message=str(e), profile=profile, retryable=True)

            @self._profile_tool(description=self.tool_settings.tool_delete_collection_description)
            async def delete_collection(
                ctx: Context,
                collection_name: Annotated[str, Field(description="Name of the collection to delete")],
                confirm: Annotated[bool, Field(description="Confirmation that you want to delete this collection")] = False
            ) -> str:
                """Delete a collection permanently. Requires confirmation."""
                if not confirm:
                    return f"Please set confirm=True to delete collection '{collection_name}'. This action cannot be undone."

                try:
                    success = await self.qdrant_connector.delete_collection(collection_name)
                    if success:
                        return f"Successfully deleted collection '{collection_name}'"
                    else:
                        return f"Failed to delete collection '{collection_name}'"
                except Exception as e:
                    await ctx.debug(f"Error deleting collection: {e}")
                    return f"Error deleting collection: {str(e)}"

    def setup_embedding_model_tools(self):
        """Setup enhanced embedding model tools."""

        @self._profile_tool(description=self.tool_settings.tool_set_collection_embedding_model_impl_description)
        async def set_collection_embedding_model(
            ctx: Context,
            model_name: Annotated[str, Field(description="Embedding model name, e.g. 'Qwen/Qwen3-Embedding-8B'")],
        ) -> str:
            """Switch the active embedding model. Affects all subsequent store/search operations."""
            try:
                model_info = self.embedding_manager.get_model_info(model_name)
                if not model_info:
                    available = [m.model_name for m in self.embedding_manager.list_available_models()]
                    return (
                        f"Unknown model '{model_name}'. "
                        f"Available models include: {', '.join(available[:10])}..."
                    )
                provider = self.embedding_manager.create_provider_for_model(model_name)
                self.qdrant_connector.set_embedding_provider(provider)
                self.embedding_provider = provider
                return (
                    f"Active embedding model set to '{model_name}' "
                    f"({model_info.vector_size}D). "
                    f"Create a new collection with vector_size={model_info.vector_size} to use it."
                )
            except Exception as e:
                await ctx.debug(f"Error setting embedding model: {e}")
                return f"Error setting embedding model: {str(e)}"

        @self._profile_tool(description=self.tool_settings.tool_list_embedding_models_description)
        async def list_embedding_models(ctx: Context) -> list[str]:
            """List all available embedding models."""
            try:
                models = self.embedding_manager.list_available_models()
                if not models:
                    return ["No embedding models available"]

                result = [
                    "Available Embedding Models:",
                    ""
                ]
                for model in models:
                    result.append(f"• {model.model_name} ({model.provider_type}) - {model.vector_size}D - {model.description}")

                result.extend([
                    "",
                    "Available Distance Metrics:",
                    "• cosine - Cosine similarity (default, good for most cases)",
                    "• dot - Dot product (for normalized vectors)",
                    "• euclidean - Euclidean distance (L2 norm)",
                    "• manhattan - Manhattan distance (L1 norm)"
                ])

                return result
            except Exception as e:
                await ctx.debug(f"Error listing models: {e}")
                return [f"Error listing models: {str(e)}"]

    def setup_advanced_search_tools(self):
        """Setup advanced search and storage tools with enhanced embedding support."""

        @self._profile_tool(description=self.tool_settings.tool_search_documents_description)
        async def search_documents(
            ctx: Context,
            query: Annotated[str, Field(description="Semantic search query")],
            collection_name: Annotated[str, Field(description="Collection to search")],
            limit: Annotated[int, Field(description="Number of distinct documents to return")] = 10,
            chunks_per_document: Annotated[int, Field(description="Best chunks to surface per document")] = 1,
            filter: Annotated[dict | None, Field(description="High-level filter: {must, should, must_not}")] = None,
            mode: Annotated[str, Field(description="'dense' | 'hybrid' | 'rerank' | 'late_interaction' (reserved)")] = "dense",
            reranker_model: Annotated[str | None, Field(description="Reranker for mode='rerank' (default Xenova/ms-marco-MiniLM-L-6-v2)")] = None,
        ) -> dict:
            """Document-level grouped search — best chunk per file, ranked by document score."""
            from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from
            from mcp_server_qdrant.search.document_search import search_documents_grouped
            from mcp_server_qdrant.search.filter_grammar import compile_filter
            from mcp_server_qdrant.search.retrieval_mode import RetrievalMode
            from mcp_server_qdrant.search.reranker import build_default_reranker

            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                try:
                    rmode = RetrievalMode.parse(mode)
                    if rmode == RetrievalMode.LATE_INTERACTION:
                        return failure_from(
                            acc,
                            code="mode_not_supported",
                            message="Mode 'late_interaction' is reserved for future ColBERT-style retrieval.",
                            profile=profile,
                        )

                    qfilter = compile_filter(filter) if filter else None
                    use_sparse = rmode in (RetrievalMode.HYBRID, RetrievalMode.RERANK)
                    sparse_provider = self.get_sparse_provider() if use_sparse else None

                    reranker = None
                    if rmode == RetrievalMode.RERANK:
                        reranker_name = reranker_model or "Xenova/ms-marco-MiniLM-L-6-v2"
                        reranker = build_default_reranker(reranker_name)
                        acc.stats["reranker_model"] = reranker_name

                    docs = await search_documents_grouped(
                        self.qdrant_connector,
                        query=query,
                        collection_name=collection_name,
                        limit=limit,
                        chunks_per_document=chunks_per_document,
                        query_filter=qfilter,
                        sparse_provider=sparse_provider,
                        reranker=reranker,
                    )
                    acc.stats["raw_chunks_fetched"] = sum(len(d["chunks"]) for d in docs)
                    acc.stats["documents_returned"] = len(docs)

                    results = []
                    for d in docs:
                        best = d["chunks"][0] if d["chunks"] else None
                        snippet = (best["content"][:500] if best else "")
                        results.append({
                            "document_id": d["document_id"],
                            "path": d.get("path") or "",
                            "filename": d.get("filename") or "",
                            "title": d.get("title"),
                            "snippet": snippet,
                            "score": d["score"],
                            "chunk_count": len(d["chunks"]),
                            "metadata": (best["metadata"] if best else {}) or {},
                        })

                    return success_from(
                        acc,
                        data={
                            "query": query,
                            "mode": rmode.value,
                            "grouped_by_document": True,
                            "results": results,
                        },
                        profile=profile,
                    )
                except ValueError as e:
                    return failure_from(acc, code="invalid_argument", message=str(e), profile=profile)
                except Exception as e:
                    await ctx.debug(f"Error in search_documents: {e}")
                    return failure_from(acc, code="internal_error", message=str(e), profile=profile, retryable=True)

        @self._profile_tool(description=self.tool_settings.tool_bootstrap_indexes_description)
        async def bootstrap_collection_indexes(
            ctx: Context,
            collection_name: Annotated[str, Field(description="Collection to index")],
        ) -> dict:
            """Create all macOS metadata payload indexes on a collection up front."""
            from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from
            from mcp_server_qdrant.ingest.macos_metadata import MACOS_INDEX_FIELDS
            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                try:
                    await self.qdrant_connector.ensure_macos_metadata_indexes(collection_name)
                    return success_from(
                        acc,
                        data={
                            "collection": collection_name,
                            "indexes_ensured": [f for f, _ in MACOS_INDEX_FIELDS],
                        },
                        profile=profile,
                    )
                except Exception as e:
                    await ctx.debug(f"Error bootstrapping indexes: {e}")
                    return failure_from(acc, code="internal_error", message=str(e), profile=profile, retryable=True)

        @self._profile_tool(description=self.tool_settings.tool_hybrid_search_description)
        async def hybrid_search(
            ctx: Context,
            query: Annotated[str, Field(description="Search query")],
            collection_name: Annotated[str, Field(description="Collection to search in")],
            limit: Annotated[int, Field(description="Maximum number of results")] = 10,
            min_score: Annotated[float, Field(description="Minimum similarity score threshold")] = 0.0,
            include_scores: Annotated[bool, Field(description="Include similarity scores in results")] = True
        ) -> list[str]:
            """Perform advanced search with similarity scores and filtering."""
            try:
                results = await self.qdrant_connector.hybrid_search(
                    query=query,
                    collection_name=collection_name,
                    limit=limit,
                    min_score=min_score if min_score > 0 else None
                )

                if not results:
                    return [f"No results found for query '{query}' in collection '{collection_name}'"]

                content = [f"Hybrid search results for '{query}' in '{collection_name}':"]
                for entry, score in results:
                    if include_scores:
                        content.append(f"[Score: {score:.4f}] {self.format_entry(entry)}")
                    else:
                        content.append(self.format_entry(entry))

                return content
            except Exception as e:
                await ctx.debug(f"Error in hybrid search: {e}")
                return [f"Error in hybrid search: {str(e)}"]

        @self._profile_tool(description=self.tool_settings.tool_scroll_description)
        async def scroll_collection(
            ctx: Context,
            collection_name: Annotated[str, Field(description="Collection to browse")],
            limit: Annotated[int, Field(description="Maximum number of entries to return")] = 20,
            offset: Annotated[str, Field(description="Pagination offset (point ID to start from)")] = ""
        ) -> list[str]:
            """Browse through collection contents with pagination."""
            try:
                entries, next_offset = await self.qdrant_connector.scroll_collection(
                    collection_name=collection_name,
                    limit=limit,  # No artificial limit
                    offset=offset if offset else None
                )

                if not entries:
                    return [f"No entries found in collection '{collection_name}'"]

                content = [f"Browsing collection '{collection_name}' (showing {len(entries)} entries):"]
                for entry in entries:
                    content.append(self.format_entry(entry))

                if next_offset:
                    content.append(f"Next page offset: {next_offset}")
                else:
                    content.append("End of collection reached")

                return content
            except Exception as e:
                await ctx.debug(f"Error scrolling collection: {e}")
                return [f"Error scrolling collection: {str(e)}"]

        if not self.qdrant_settings.read_only:
            @self._profile_tool(description=self.tool_settings.tool_batch_store_description)
            async def qdrant_store_batch(
                ctx: Context,
                entries: Annotated[list[dict], Field(description="List of entries to store, each with 'content' and optional 'metadata' and 'id'")],
                collection_name: Annotated[str, Field(description="Collection to store entries in")]
            ) -> str:
                """Store multiple entries efficiently in a single batch operation."""
                try:
                    # Validate and convert entries
                    batch_entries = []
                    for i, entry_dict in enumerate(entries):
                        if "content" not in entry_dict:
                            return f"Entry {i} missing required 'content' field"

                        # Parse metadata from JSON string if needed
                        parsed_metadata = None
                        metadata = entry_dict.get("metadata")
                        if metadata:
                            if isinstance(metadata, str):
                                try:
                                    parsed_metadata = json.loads(metadata)
                                except json.JSONDecodeError:
                                    return f"Entry {i}: Invalid metadata JSON: {metadata}"
                            else:
                                parsed_metadata = metadata

                        batch_entries.append(BatchEntry(
                            content=entry_dict["content"],
                            metadata=parsed_metadata,
                            id=entry_dict.get("id")
                        ))

                    # No limit on batch size - process all entries
                    # if len(batch_entries) > self.qdrant_settings.max_batch_size:
                    #     return f"Batch size {len(batch_entries)} exceeds maximum {self.qdrant_settings.max_batch_size}"

                    stored_count = await self.qdrant_connector.batch_store(batch_entries, collection_name)

                    if stored_count > 0:
                        return f"Successfully stored {stored_count} entries in collection '{collection_name}'"
                    return f"No entries were stored in collection '{collection_name}'"
                except Exception as e:
                    await ctx.debug(f"Error in batch store: {e}")
                    return f"Error in batch store: {str(e)}"

    def setup_ingest_tools(self):
        """Setup file ingestion tools with macOS metadata extraction."""
        from datetime import datetime, timezone

        @self._profile_tool(description=self.tool_settings.tool_ingest_file_description)
        async def ingest_file(
            ctx: Context,
            file_path: Annotated[str, Field(description="Absolute path to the file to ingest")],
            collection_name: Annotated[str, Field(description="Collection to store chunks in")],
            extra_metadata: Annotated[str | None, Field(description="Optional extra metadata as JSON string")] = None,
            mode: Annotated[str, Field(description="'dense' (default) or 'hybrid' (collection must be hybrid)")] = "dense",
        ) -> dict:
            """Ingest a single file: extract text, collect macOS metadata, chunk and store."""
            from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from
            from mcp_server_qdrant.ingest.extractor import extract_text, build_chunks, SUPPORTED_EXTENSIONS
            from mcp_server_qdrant.ingest.macos_metadata import get_macos_metadata
            from mcp_server_qdrant.ingest.document_id import compute_document_id
            from pathlib import Path

            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                path = Path(file_path).resolve()
                if not path.exists():
                    return failure_from(acc, code="file_not_found", message=f"File not found: {file_path}", profile=profile)
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    return failure_from(
                        acc,
                        code="unsupported_file_type",
                        message=f"Unsupported file type '{path.suffix}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                        profile=profile,
                    )

                try:
                    extra = {}
                    if extra_metadata:
                        try:
                            extra = json.loads(extra_metadata)
                        except json.JSONDecodeError:
                            return failure_from(acc, code="invalid_metadata_json", message=f"Invalid extra_metadata JSON: {extra_metadata}", profile=profile)

                    file_meta = get_macos_metadata(str(path))
                    doc = extract_text(str(path))
                    file_meta["has_text"] = bool(doc.text)
                    file_meta["extractor_used"] = doc.extractor_used
                    file_meta["char_count"] = doc.char_count
                    if doc.page_count is not None:
                        file_meta["page_count"] = doc.page_count
                    file_meta["ingested_at"] = datetime.now(timezone.utc).isoformat()
                    file_meta["document_id"] = compute_document_id(str(path))
                    file_meta["parent_path"] = str(path.parent)
                    file_meta.update(extra)

                    if doc.error and not doc.text:
                        return failure_from(acc, code="extraction_failed", message=f"Extraction failed for '{path.name}': {doc.error}", profile=profile)
                    if doc.error:
                        acc.warnings.append(f"extractor_warning: {doc.error}")

                    chunks = build_chunks(doc, file_meta)
                    if not chunks:
                        return failure_from(acc, code="empty_extraction", message=f"No text extracted from '{path.name}'", profile=profile)

                    await self.qdrant_connector.ensure_macos_metadata_indexes(collection_name)

                    batch_entries = [
                        BatchEntry(content=chunk.text, metadata=chunk.metadata)
                        for chunk in chunks
                    ]
                    if mode == "hybrid":
                        stored = await self.qdrant_connector.batch_store_hybrid(
                            batch_entries, collection_name, self.get_sparse_provider()
                        )
                    else:
                        stored = await self.qdrant_connector.batch_store(batch_entries, collection_name)

                    acc.stats.update({
                        "extractor_used": doc.extractor_used,
                        "char_count": doc.char_count,
                        "page_count": doc.page_count,
                        "chunks_stored": stored,
                        "mode": mode,
                    })
                    return success_from(
                        acc,
                        data={
                            "file_path": str(path),
                            "filename": path.name,
                            "document_id": file_meta["document_id"],
                            "collection": collection_name,
                            "chunks_stored": stored,
                            "extractor_used": doc.extractor_used,
                            "char_count": doc.char_count,
                            "page_count": doc.page_count,
                        },
                        profile=profile,
                    )
                except Exception as e:
                    await ctx.debug(f"Error ingesting file: {e}")
                    return failure_from(acc, code="internal_error", message=str(e), profile=profile, retryable=True)

        @self._profile_tool(description=self.tool_settings.tool_ingest_folder_description)
        async def ingest_folder(
            ctx: Context,
            folder_path: Annotated[str, Field(description="Absolute path to the folder to ingest")],
            collection_name: Annotated[str, Field(description="Collection to store chunks in")],
            recursive: Annotated[bool, Field(description="Recurse into subdirectories")] = True,
            skip_hidden: Annotated[bool, Field(description="Skip hidden files and directories (starting with .)")] = True,
            extra_metadata: Annotated[str | None, Field(description="Optional extra metadata as JSON string applied to all files")] = None,
            mode: Annotated[str, Field(description="'dense' (default) or 'hybrid' (collection must be hybrid)")] = "dense",
        ) -> dict:
            """Recursively ingest all supported files in a folder."""
            from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from
            from mcp_server_qdrant.ingest.extractor import extract_text, build_chunks, SUPPORTED_EXTENSIONS
            from mcp_server_qdrant.ingest.macos_metadata import get_macos_metadata
            from mcp_server_qdrant.ingest.document_id import compute_document_id
            from datetime import datetime, timezone
            from pathlib import Path

            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                folder = Path(folder_path).resolve()
                if not folder.exists():
                    return failure_from(acc, code="folder_not_found", message=f"Folder not found: {folder_path}", profile=profile)
                if not folder.is_dir():
                    return failure_from(acc, code="not_a_directory", message=f"Not a directory: {folder_path}", profile=profile)

                extra = {}
                if extra_metadata:
                    try:
                        extra = json.loads(extra_metadata)
                    except json.JSONDecodeError:
                        return failure_from(acc, code="invalid_metadata_json", message=f"Invalid extra_metadata JSON: {extra_metadata}", profile=profile)

                pattern = "**/*" if recursive else "*"
                all_files = [
                    p for p in folder.glob(pattern)
                    if p.is_file()
                    and p.suffix.lower() in SUPPORTED_EXTENSIONS
                    and (not skip_hidden or not any(part.startswith(".") for part in p.parts))
                ]

                if not all_files:
                    return success_from(
                        acc,
                        data={
                            "folder": str(folder),
                            "files_processed": 0,
                            "files_total": 0,
                            "chunks_stored": 0,
                            "errors": [],
                        },
                        profile=profile,
                    )

                await self.qdrant_connector.ensure_macos_metadata_indexes(collection_name)

                total_chunks = 0
                total_files = 0
                errors: list[dict] = []
                ingested_at = datetime.now(timezone.utc).isoformat()

                for path in sorted(all_files):
                    try:
                        file_meta = get_macos_metadata(str(path))
                        doc = extract_text(str(path))
                        file_meta["has_text"] = bool(doc.text)
                        file_meta["extractor_used"] = doc.extractor_used
                        file_meta["char_count"] = doc.char_count
                        if doc.page_count is not None:
                            file_meta["page_count"] = doc.page_count
                        file_meta["ingested_at"] = ingested_at
                        file_meta["document_id"] = compute_document_id(str(path))
                        file_meta["parent_path"] = str(path.parent)
                        file_meta.update(extra)

                        if not doc.text:
                            errors.append({"file": str(path), "code": "empty_extraction", "message": doc.error or "empty"})
                            continue

                        chunks = build_chunks(doc, file_meta)
                        batch_entries = [
                            BatchEntry(content=chunk.text, metadata=chunk.metadata)
                            for chunk in chunks
                        ]
                        if mode == "hybrid":
                            stored = await self.qdrant_connector.batch_store_hybrid(
                                batch_entries, collection_name, self.get_sparse_provider()
                            )
                        else:
                            stored = await self.qdrant_connector.batch_store(batch_entries, collection_name)
                        total_chunks += stored
                        total_files += 1
                    except Exception as e:
                        errors.append({"file": str(path), "code": "internal_error", "message": str(e)})

                if errors:
                    acc.warnings.append(f"{len(errors)} file(s) failed; see data.errors")

                acc.stats["mode"] = mode
                return success_from(
                    acc,
                    data={
                        "folder": str(folder),
                        "files_processed": total_files,
                        "files_total": len(all_files),
                        "chunks_stored": total_chunks,
                        "errors": errors[:50],
                    },
                    profile=profile,
                )

    def setup_discovery_tools(self) -> None:
        """Register read-only self-description tools so agents can inspect the server."""
        from mcp_server_qdrant.mcp_runtime.discovery import (
            indexed_fields_payload,
            search_modes_payload,
            server_capabilities_payload,
            supported_extractors_payload,
        )
        from mcp_server_qdrant.mcp_runtime.envelope import envelope_context, success_from, failure_from

        @self._profile_tool(description="List all indexed payload fields with types, allowed operators, and the supported filter grammar.")
        async def get_indexed_fields(ctx: Context) -> dict:
            """Return filterable field schema and the high-level filter grammar."""
            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                return success_from(acc, data=indexed_fields_payload(), profile=profile)

        @self._profile_tool(description="List supported file extensions and the extractor stack used for each.")
        async def get_supported_extractors(ctx: Context) -> dict:
            """Return the supported file extractor matrix."""
            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                return success_from(acc, data=supported_extractors_payload(), profile=profile)

        @self._profile_tool(description="List supported retrieval modes (dense, hybrid, rerank, late_interaction) and when to use each.")
        async def list_search_modes(ctx: Context) -> dict:
            """Return the catalog of retrieval modes."""
            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                return success_from(acc, data=search_modes_payload(), profile=profile)

        @self._profile_tool(description="Detailed schema and configuration for a specific collection (vectors, distance, hybrid status).")
        async def get_collection_schema(
            ctx: Context,
            collection_name: Annotated[str, Field(description="Collection name to inspect")],
        ) -> dict:
            """Return per-collection schema."""
            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                try:
                    info = await self.qdrant_connector.get_detailed_collection_info(collection_name)
                    if not info:
                        return failure_from(acc, code="not_found", message=f"Collection '{collection_name}' does not exist", profile=profile)
                    return success_from(
                        acc,
                        data={
                            "name": info.name,
                            "vector_size": info.vector_size,
                            "distance_metric": info.distance_metric,
                            "points_count": info.points_count,
                            "vectors_count": info.vectors_count,
                            "indexed_vectors_count": info.indexed_vectors_count,
                            "segments_count": info.segments_count,
                            "status": info.status,
                            "optimizer_status": info.optimizer_status,
                        },
                        profile=profile,
                    )
                except Exception as e:
                    return failure_from(acc, code="internal_error", message=str(e), profile=profile, retryable=True)

        @self._profile_tool(description="Top-level server self-description: transports, profiles, search modes, extractors, and feature flags.")
        async def get_server_capabilities(ctx: Context) -> dict:
            """Return the top-level server capability map."""
            import os
            profile = self.active_profile.name.lower()
            with envelope_context(profile) as acc:
                models_avail = [m.model_name for m in self.embedding_manager.list_available_models()]
                payload = server_capabilities_payload(
                    profile=profile,
                    transports=["stdio", "sse", "streamable-http"],
                    dynamic_embedding_models=self.qdrant_settings.enable_dynamic_embedding_models,
                    resources_enabled=self.qdrant_settings.enable_resources,
                    auth_enabled=bool(os.getenv("MCP_HTTP_AUTH_TOKEN")),
                    available_models=models_avail,
                )
                return success_from(acc, data=payload, profile=profile)

    def setup_resources(self):
        """Setup enhanced MCP resources."""

        @self.resource("qdrant://collections")
        async def collections_overview() -> str:
            """Overview of all collections and their statistics."""
            try:
                collections = await self.qdrant_connector.get_collection_names()
                if not collections:
                    return "No collections found in Qdrant database."

                overview = ["# Qdrant Collections Overview\n"]

                for collection_name in collections:
                    info = await self.qdrant_connector.get_detailed_collection_info(collection_name)
                    if info:
                        overview.append(f"## Collection: {collection_name}")
                        overview.append(f"- **Points**: {info.points_count:,}")
                        overview.append(f"- **Vectors**: {info.vectors_count:,}")
                        overview.append(f"- **Status**: {info.status}")
                        overview.append(f"- **Vector Size**: {info.vector_size or 'Unknown'}")
                        overview.append(f"- **Distance Metric**: {info.distance_metric or 'Unknown'}")


                return "\n".join(overview)
            except Exception as e:
                return f"Error getting collections overview: {str(e)}"

        @self.resource("qdrant://collection/{collection_name}/schema")
        async def collection_schema(collection_name: str) -> str:
            """Detailed schema and configuration for a specific collection."""
            try:
                info = await self.qdrant_connector.get_detailed_collection_info(collection_name)
                if not info:
                    return f"Collection '{collection_name}' not found."

                schema = [f"# Collection Schema: {collection_name}\n"]

                schema.append("## Configuration")
                schema.append(f"- **Vector Size**: {info.vector_size or 'Unknown'}")
                schema.append(f"- **Distance Metric**: {info.distance_metric or 'Unknown'}")
                schema.append(f"- **Status**: {info.status}")
                schema.append(f"- **Optimizer Status**: {info.optimizer_status}")
                schema.append("")

                schema.append("## Statistics")
                schema.append(f"- **Total Points**: {info.points_count:,}")
                schema.append(f"- **Total Vectors**: {info.vectors_count:,}")
                schema.append(f"- **Indexed Vectors**: {info.indexed_vectors_count:,}")
                schema.append(f"- **Segments**: {info.segments_count}")
                schema.append("")

                return "\n".join(schema)
            except Exception as e:
                return f"Error getting collection schema: {str(e)}"
