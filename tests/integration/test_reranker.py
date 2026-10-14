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

"""Integration tests for reranker module (deterministic, no LLM needed)."""

from __future__ import annotations

import uuid

import pytest

from flyquery.core.services.retrieval.reranker import LexicalReranker, NoopReranker, build_reranker
from flyquery.core.services.retrieval.search_index import Hit


def _make_hits(n: int) -> list[Hit]:
    return [
        Hit(
            source_kind="schema_object",
            id=uuid.uuid4(),
            text=f"hit {i}",
            score=float(n - i),
            metadata={},
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_noop_reranker_truncates() -> None:
    reranker = NoopReranker()
    hits = _make_hits(10)
    result = await reranker.rerank("revenue", hits, top_n=5)
    assert len(result) == 5
    assert result == hits[:5]


@pytest.mark.asyncio
async def test_noop_reranker_handles_empty() -> None:
    reranker = NoopReranker()
    result = await reranker.rerank("revenue", [], top_n=5)
    assert result == []


@pytest.mark.asyncio
async def test_build_reranker_returns_lexical_when_no_model() -> None:
    class FakeSettings:
        reranker_model = ""

    r = build_reranker(FakeSettings())
    # No model configured -> the dependency-free LexicalReranker (a strict win
    # over the identity NoopReranker, which left wide-table precision unimproved).
    assert isinstance(r, LexicalReranker)


@pytest.mark.asyncio
async def test_build_reranker_falls_back_to_lexical_on_bad_model() -> None:
    class FakeSettings:
        reranker_model = "nonexistent/model-that-does-not-exist"

    r = build_reranker(FakeSettings())
    # Falls back to LexicalReranker when sentence-transformers isn't installed or
    # the cross-encoder model can't be loaded (token-overlap still beats no-op).
    assert isinstance(r, LexicalReranker)


@pytest.mark.asyncio
async def test_noop_reranker_does_not_change_order() -> None:
    reranker = NoopReranker()
    hits = _make_hits(4)
    original_ids = [h.id for h in hits]
    result = await reranker.rerank("test", hits, top_n=4)
    assert [h.id for h in result] == original_ids
