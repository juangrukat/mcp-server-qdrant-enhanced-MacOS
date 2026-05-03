from mcp_server_qdrant.embeddings.base import EmbeddingProvider
from mcp_server_qdrant.embeddings.types import EmbeddingProviderType
from mcp_server_qdrant.settings import EmbeddingProviderSettings


def create_embedding_provider(settings: EmbeddingProviderSettings) -> EmbeddingProvider:
    """
    Create an embedding provider based on the specified type.
    :param settings: The settings for the embedding provider.
    :return: An instance of the specified embedding provider.
    """
    if settings.provider_type == EmbeddingProviderType.FASTEMBED:
        if settings.model_name.startswith("Qwen/Qwen3-Embedding-"):
            from mcp_server_qdrant.embeddings.qwen3_rust import Qwen3RustProvider

            return Qwen3RustProvider(
                settings.model_name,
                device=settings.device,
                max_length=settings.qwen3_max_length,
                dtype=settings.qwen3_dtype,
                binary_path=settings.qwen3_sidecar_path,
                metrics_path=settings.qwen3_metrics_path,
                response_limit_bytes=settings.qwen3_response_limit_bytes,
            )

        from mcp_server_qdrant.embeddings.fastembed import FastEmbedProvider

        return FastEmbedProvider(settings.model_name, device=settings.device)
    else:
        raise ValueError(f"Unsupported embedding provider: {settings.provider_type}")
