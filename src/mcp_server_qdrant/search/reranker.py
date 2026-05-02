"""
Reranker abstraction.

A reranker takes a query and a candidate list (from first-stage retrieval) and
returns the candidates re-ordered by a more expensive but more accurate scorer —
typically a cross-encoder.

Why an abstraction now: the search pipeline already has dense + hybrid first-stage
retrieval, and reranking is the highest-leverage next quality improvement. Having
the interface in place lets us plug in different rerankers (FastEmbed cross-encoders,
Qwen3-Reranker, ColBERT late interaction) without touching call sites.

The default `NoOpReranker` is the safe fallback when reranking is disabled. The
`FastEmbedReranker` lazy-loads a cross-encoder via fastembed when available.

For Qwen3-Reranker-4B / 8B, see `QwenReranker` (stub — requires a
torch+transformers backend that is not currently a hard dependency of this project).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RerankCandidate:
    """One candidate passed into the reranker; preserves original payload for re-emission."""
    content: str
    metadata: dict | None
    first_stage_score: float
    payload: Any | None = None  # opaque slot for callers to keep their own object


class Reranker(ABC):
    """Reranker interface — implementations should be safe to call repeatedly."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int | None = None,
    ) -> list[tuple[RerankCandidate, float]]:
        """
        Rerank candidates and return them ordered by descending relevance score.
        The returned scores are reranker scores, not first-stage scores.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class NoOpReranker(Reranker):
    """Returns candidates in their first-stage order with first-stage scores. Safe default."""

    @property
    def model_name(self) -> str:
        return "noop"

    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int | None = None,
    ) -> list[tuple[RerankCandidate, float]]:
        ordered = sorted(candidates, key=lambda c: c.first_stage_score, reverse=True)
        if top_k:
            ordered = ordered[:top_k]
        return [(c, c.first_stage_score) for c in ordered]


class FastEmbedReranker(Reranker):
    """
    Cross-encoder reranker via fastembed's TextCrossEncoder, when available.

    Recommended models (in order of size/speed tradeoff):
      - Xenova/ms-marco-MiniLM-L-6-v2  (light, fast)
      - jinaai/jina-reranker-v1-tiny-en
      - BAAI/bge-reranker-base
      - BAAI/bge-reranker-large

    The Qwen3-Reranker family is not yet exposed via fastembed at the time of writing;
    use `QwenReranker` (transformers-based) for those.
    """

    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        self._model_name = model_name
        self._encoder = None  # lazy

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self):
        if self._encoder is not None:
            return
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as e:
            raise RuntimeError(
                "FastEmbedReranker requires fastembed>=0.4 with TextCrossEncoder. "
                f"Import error: {e}"
            )
        self._encoder = TextCrossEncoder(self._model_name)

    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int | None = None,
    ) -> list[tuple[RerankCandidate, float]]:
        if not candidates:
            return []
        self._load()
        loop = asyncio.get_event_loop()
        texts = [c.content for c in candidates]
        scores = await loop.run_in_executor(
            None, lambda: list(self._encoder.rerank(query, texts))
        )
        scored = list(zip(candidates, scores))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        if top_k:
            scored = scored[:top_k]
        return scored


class QwenReranker(Reranker):
    """
    Stub for Qwen3-Reranker-{4B,8B}. Requires torch + transformers, which are NOT
    currently hard dependencies of this project. Install them separately:

        pip install torch transformers accelerate

    Then construct:

        QwenReranker(model_name="Qwen/Qwen3-Reranker-4B", device="mps")

    The implementation here is intentionally a clear placeholder so the abstraction
    is in place; uncomment and complete when you wire up transformers.
    """

    def __init__(self, model_name: str = "Qwen/Qwen3-Reranker-4B", device: str = "mps"):
        self._model_name = model_name
        self._device = device
        self._loaded = False

    @property
    def model_name(self) -> str:
        return self._model_name

    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int | None = None,
    ) -> list[tuple[RerankCandidate, float]]:
        raise NotImplementedError(
            "QwenReranker is a stub. Install torch+transformers and implement "
            "the forward pass to enable Qwen3-Reranker-{4B,8B}."
        )


def build_default_reranker(model_name: str | None = None) -> Reranker:
    """Factory that returns FastEmbedReranker if a model name is given, else NoOp."""
    if not model_name or model_name.lower() == "noop":
        return NoOpReranker()
    if model_name.startswith("Qwen/"):
        return QwenReranker(model_name=model_name)
    return FastEmbedReranker(model_name=model_name)
