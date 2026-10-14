# Copyright 2024-2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cross-encoder reranker with graceful fallback to no-op.

``CrossEncoderReranker`` lazy-imports ``sentence-transformers``.
If the package is absent (or the model fails to load), ``build_reranker``
silently returns a ``NoopReranker`` instead.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from flyquery.core.services.retrieval.search_index import Hit

logger = logging.getLogger(__name__)

# Guard so the cross-encoder-unavailable warning is emitted at most once per process.
_warned_noop_fallback = False

_TOKEN = re.compile(r"[\wÀ-ý]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if len(t) >= 2}


class Reranker(Protocol):
    """Protocol for a reranking step in the retrieval pipeline."""

    async def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        """Return at most *top_n* hits re-ordered by cross-encoder score."""
        ...


class NoopReranker:
    """Identity reranker that preserves the original order."""

    async def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:  # noqa: ARG002
        """Return the first ``top_n`` hits unchanged."""
        return hits[:top_n]


class LexicalReranker:
    """Dependency-free reranker: token-overlap between the query and each hit.

    A real cross-encoder is better, but when ``sentence-transformers`` is not
    installed this is a strict improvement over the identity ``NoopReranker``:
    it boosts hits whose text (now including the column's indexed VALUES) shares
    tokens with the question, blending the lexical score with the retriever's
    RRF score so a token-exact value/name match surfaces the owning column.
    Fully dataset-agnostic.
    """

    async def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        if not hits:
            return []
        qtok = _tokens(query)
        if not qtok:
            return hits[:top_n]

        def score(h: Hit) -> float:
            htok = _tokens(h.text)
            if not htok:
                return 0.0
            overlap = len(qtok & htok)
            lex = overlap / (len(qtok) ** 0.5)
            return lex + 0.25 * float(getattr(h, "score", 0.0) or 0.0)

        order = sorted(range(len(hits)), key=lambda i: score(hits[i]), reverse=True)
        return [hits[i] for i in order[:top_n]]


class CrossEncoderReranker:
    """Reranker backed by a sentence-transformers CrossEncoder model.

    The model is loaded lazily in ``__init__``; if the import or model
    load fails the caller should use ``build_reranker`` which catches
    the error and falls back to ``NoopReranker``.
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

        self._model = CrossEncoder(model_name)

    async def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        """Score (query, passage) pairs and return top-n by score.

        :param query: NL query string
        :param hits: candidate hits to rerank
        :param top_n: how many top results to return
        :return: hits sorted by cross-encoder score, descending
        """
        if not hits:
            return []
        pairs = [(query, h.text) for h in hits]
        scores = self._model.predict(pairs)
        order = sorted(range(len(hits)), key=lambda i: float(scores[i]), reverse=True)
        return [hits[i] for i in order[:top_n]]


def build_reranker(settings: Any) -> NoopReranker | LexicalReranker | CrossEncoderReranker:
    """Factory: return a ``CrossEncoderReranker`` when possible.

    Falls back to the dependency-free ``LexicalReranker`` (NOT a no-op) when:
    - ``settings.reranker_model`` is empty / falsy
    - ``sentence-transformers`` is not installed
    - The specified model cannot be loaded (network error, etc.)

    The previous default silently degraded to an identity pass-through, leaving
    wide-table column precision unimproved; the lexical fallback is a strict win
    on any dataset and is what makes value-aware retrieval reach the prompt.

    :param settings: ``FlyquerySettings`` instance
    :return: a ready-to-use reranker
    """
    global _warned_noop_fallback
    model_name = getattr(settings, "reranker_model", "") or ""
    if not model_name:
        return LexicalReranker()
    try:
        return CrossEncoderReranker(model_name)
    except Exception as exc:  # noqa: BLE001
        if not _warned_noop_fallback:
            _warned_noop_fallback = True
            logger.warning(
                "reranker model=%s unavailable (%s) -- falling back to the "
                "dependency-free LexicalReranker (token-overlap). Cross-encoder "
                "reranking is disabled; install sentence-transformers / make the "
                "model loadable to re-enable it.",
                model_name,
                exc,
            )
        return LexicalReranker()
