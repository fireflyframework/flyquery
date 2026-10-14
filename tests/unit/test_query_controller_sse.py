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

"""Unit tests for the QueryController SSE stream and :explain/:validate endpoints.

Uses in-process fakes for all agents, executor, and database so no API keys
or live Postgres are required. The SSE generator is exercised directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC

import pytest

from flyquery.core.agents.explainer_agent import ResultExplanation
from flyquery.core.agents.generation_agent import GeneratedCandidate, GeneratedCandidates
from flyquery.core.agents.grounding_agent import GroundedColumn, GroundedContext, GroundedTable
from flyquery.core.services.execution.duckdb_executor import ExecutionResult

# ---------------------------------------------------------------------------
# Helpers — SSE frame parser
# ---------------------------------------------------------------------------


def _parse_sse_frames(frames: list[bytes]) -> list[dict]:
    """Parse SSE byte frames into list of {event, data_str} dicts."""
    import json

    results = []
    for frame in frames:
        text = frame.decode("utf-8")
        event = None
        data_str = None
        for line in text.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:") :].strip()
        if event:
            results.append({"event": event, "data": json.loads(data_str) if data_str else {}})
    return results


# ---------------------------------------------------------------------------
# Fake pipeline components for SSE tests
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, output):
        self._output = output

    async def run(self, _):
        return self._output


class _FakeRetriever:
    async def retrieve(self, query, *, dataset_id, workspace_id, **kwargs):
        return {"schema_objects": [], "examples": [], "metrics": [], "glossary": [], "relations": []}


class _FakeReranker:
    async def rerank(self, query, hits, top_n):
        return hits[:top_n]


class _FakeExecutor:
    def __init__(self, result):
        self._result = result

    async def execute(self, sql, attached):
        return self._result


class _FakeTableResolver:
    def __init__(self):
        self._session = _FakeSession()

    async def resolve(self, dataset_id, table_names, object_store_base=None, pins=None):
        return {}

    async def table_kinds_by_name(self, dataset_id, table_names):
        return {}

    async def current_snapshots(self, dataset_id, table_names):
        return {}


class _FakeSession:
    async def execute(self, stmt, params=None):
        return _FakeMappingResult([])


class _FakeMappingResult:
    def mappings(self):
        return self

    def all(self):
        return []

    def __iter__(self):
        return iter([])


class _FakeQueryRepo:
    async def create_query(self, **kwargs):
        return uuid.uuid4()

    async def upsert_result(self, **kwargs):
        pass


class _FakeObjectStore:
    async def put(self, key, body, content_type, kms_key_uri=None):
        from datetime import datetime

        from flyquery.core.services.storage.object_store import ObjectMeta

        return ObjectMeta(
            key=key,
            size_bytes=len(body),
            content_type=content_type,
            etag=None,
            last_modified=datetime.now(UTC),
        )


class _FakeExamplesService:
    async def create(self, *args, **kwargs):
        pass


class _FakeSettings:
    grounding_model = "test"
    generation_model = "test"
    critic_model = "test"
    explainer_model = "test"
    top_k_schema = 5
    top_k_examples = 3
    top_k_metrics = 3
    max_refine_retries = 1
    grounding_min_confidence = 0.55
    duckdb_memory_limit = "256MB"
    default_row_cap = 100
    default_statement_timeout_ms = 5000
    rrf_k = 60
    reranker_model = ""
    result_preview_max_bytes = 131072
    result_ttl_hours = 24
    object_store_base = "/tmp"


def _make_grounded(confidence: float = 0.9) -> GroundedContext:
    return GroundedContext(
        path="SYNTHESIS",
        tables=[GroundedTable(table_qualified_name="orders", relevance=0.9)],
        columns=[GroundedColumn(column_qualified_name="orders.total", relevance=0.9)],
        confidence=confidence,
    )


def _make_candidates(sql: str = "SELECT 1 AS v") -> GeneratedCandidates:
    return GeneratedCandidates(
        candidates=[GeneratedCandidate(sql=sql, reasoning="unit test", confidence=0.9)]
    )


# ---------------------------------------------------------------------------
# SSE generator tests using the _stream_events method directly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_happy_path_emits_all_events():
    """SSE generator emits schema_linked, sql_generated, executed, explained, final."""
    from unittest.mock import MagicMock, patch

    from flyquery.interfaces.query import QueryRequest
    from flyquery.web.controllers.query_controller import QueryController

    settings = _FakeSettings()

    # Build controller with minimal fakes
    ctrl = QueryController.__new__(QueryController)
    ctrl._settings = settings
    ctrl._session_factory = None  # not used in this test (we mock _stream_events)
    ctrl._object_store = _FakeObjectStore()
    ctrl._query_repo = _FakeQueryRepo()
    ctrl._examples_service = _FakeExamplesService()
    ctrl._embedder = MagicMock()
    ctrl._ast_classifier = MagicMock()
    ctrl._scope_guard = MagicMock()
    ctrl._executor = _FakeExecutor(
        ExecutionResult(rows=[{"v": 1}], columns=["v"], row_count=1, truncated=False)
    )

    # Patch the builders used by _stream_events
    grounded = _make_grounded()
    candidates = _make_candidates()
    explanation = ResultExplanation(summary="1 result.", chart_hint="none")

    # We test _stream_events with a fake session factory
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_session_factory():
        yield _FakeSession()

    ctrl._session_factory = _fake_session_factory

    # Patch the agent builders and other components
    with (
        patch(
            "flyquery.web.controllers.query_controller.build_grounding_agent",
            return_value=_FakeAgent(grounded),
        ),
        patch(
            "flyquery.web.controllers.query_controller.build_generation_agent",
            return_value=_FakeAgent(candidates),
        ),
        patch("flyquery.web.controllers.query_controller.build_critic_agent", return_value=_FakeAgent(None)),
        patch(
            "flyquery.web.controllers.query_controller.build_explainer_agent",
            return_value=_FakeAgent(explanation),
        ),
        patch("flyquery.web.controllers.query_controller.HybridRetriever", return_value=_FakeRetriever()),
        patch("flyquery.web.controllers.query_controller.TableResolver", return_value=_FakeTableResolver()),
        patch("flyquery.web.controllers.query_controller.SearchIndex", return_value=MagicMock()),
        patch("flyquery.web.controllers.query_controller.build_reranker", return_value=_FakeReranker()),
    ):
        from flyquery.interfaces.query import QueryRequest

        request = QueryRequest(dataset_id=uuid.uuid4(), question="how many orders?")

        frames = []
        async for frame in ctrl._stream_events(
            tenant_id="ten-a",
            workspace_id=uuid.uuid4(),
            request=request,
        ):
            frames.append(frame)

    parsed = _parse_sse_frames(frames)
    event_names = [f["event"] for f in parsed]

    assert "schema_linked" in event_names
    assert "sql_generated" in event_names
    assert "executed" in event_names
    assert "explained" in event_names
    assert "final" in event_names
    # schema_linked must come first
    assert event_names[0] == "schema_linked"
    # final must come last
    assert event_names[-1] == "final"


@pytest.mark.asyncio
async def test_sse_emits_clarification_when_low_confidence():
    """SSE emits a clarification frame between schema_linked and sql_generated."""
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock, patch

    from flyquery.web.controllers.query_controller import QueryController

    settings = _FakeSettings()
    ctrl = QueryController.__new__(QueryController)
    ctrl._settings = settings
    ctrl._object_store = _FakeObjectStore()
    ctrl._query_repo = _FakeQueryRepo()
    ctrl._examples_service = _FakeExamplesService()
    ctrl._embedder = MagicMock()
    ctrl._ast_classifier = MagicMock()
    ctrl._scope_guard = MagicMock()
    ctrl._executor = _FakeExecutor(ExecutionResult(rows=[], columns=[], row_count=0, truncated=False))

    @asynccontextmanager
    async def _fake_factory():
        yield _FakeSession()

    ctrl._session_factory = _fake_factory

    low_confidence_grounded = GroundedContext(
        path="SYNTHESIS",
        tables=[GroundedTable(table_qualified_name="orders", relevance=0.5)],
        columns=[],
        confidence=0.3,
        missing_info=["Which date range?"],
    )
    candidates = _make_candidates()
    explanation = ResultExplanation(summary="0 results.", chart_hint="none")

    with (
        patch(
            "flyquery.web.controllers.query_controller.build_grounding_agent",
            return_value=_FakeAgent(low_confidence_grounded),
        ),
        patch(
            "flyquery.web.controllers.query_controller.build_generation_agent",
            return_value=_FakeAgent(candidates),
        ),
        patch("flyquery.web.controllers.query_controller.build_critic_agent", return_value=_FakeAgent(None)),
        patch(
            "flyquery.web.controllers.query_controller.build_explainer_agent",
            return_value=_FakeAgent(explanation),
        ),
        patch("flyquery.web.controllers.query_controller.HybridRetriever", return_value=_FakeRetriever()),
        patch("flyquery.web.controllers.query_controller.TableResolver", return_value=_FakeTableResolver()),
        patch("flyquery.web.controllers.query_controller.SearchIndex", return_value=MagicMock()),
        patch("flyquery.web.controllers.query_controller.build_reranker", return_value=_FakeReranker()),
    ):
        from flyquery.interfaces.query import QueryRequest

        request = QueryRequest(dataset_id=uuid.uuid4(), question="show orders")

        frames = []
        async for frame in ctrl._stream_events(
            tenant_id="ten-a",
            workspace_id=uuid.uuid4(),
            request=request,
        ):
            frames.append(frame)

    parsed = _parse_sse_frames(frames)
    event_names = [f["event"] for f in parsed]

    assert "clarification" in event_names
    # clarification must appear after schema_linked
    assert event_names.index("clarification") > event_names.index("schema_linked")
    # clarification must appear before sql_generated
    assert event_names.index("clarification") < event_names.index("sql_generated")


@pytest.mark.asyncio
async def test_sse_no_clarification_when_high_confidence():
    """SSE does NOT emit clarification when confidence is above threshold."""
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock, patch

    from flyquery.web.controllers.query_controller import QueryController

    settings = _FakeSettings()
    ctrl = QueryController.__new__(QueryController)
    ctrl._settings = settings
    ctrl._object_store = _FakeObjectStore()
    ctrl._query_repo = _FakeQueryRepo()
    ctrl._examples_service = _FakeExamplesService()
    ctrl._embedder = MagicMock()
    ctrl._ast_classifier = MagicMock()
    ctrl._scope_guard = MagicMock()
    ctrl._executor = _FakeExecutor(
        ExecutionResult(rows=[{"v": 1}], columns=["v"], row_count=1, truncated=False)
    )

    @asynccontextmanager
    async def _fake_factory():
        yield _FakeSession()

    ctrl._session_factory = _fake_factory

    grounded = _make_grounded(confidence=0.95)
    candidates = _make_candidates()
    explanation = ResultExplanation(summary="1 result.", chart_hint="none")

    with (
        patch(
            "flyquery.web.controllers.query_controller.build_grounding_agent",
            return_value=_FakeAgent(grounded),
        ),
        patch(
            "flyquery.web.controllers.query_controller.build_generation_agent",
            return_value=_FakeAgent(candidates),
        ),
        patch("flyquery.web.controllers.query_controller.build_critic_agent", return_value=_FakeAgent(None)),
        patch(
            "flyquery.web.controllers.query_controller.build_explainer_agent",
            return_value=_FakeAgent(explanation),
        ),
        patch("flyquery.web.controllers.query_controller.HybridRetriever", return_value=_FakeRetriever()),
        patch("flyquery.web.controllers.query_controller.TableResolver", return_value=_FakeTableResolver()),
        patch("flyquery.web.controllers.query_controller.SearchIndex", return_value=MagicMock()),
        patch("flyquery.web.controllers.query_controller.build_reranker", return_value=_FakeReranker()),
    ):
        from flyquery.interfaces.query import QueryRequest

        request = QueryRequest(dataset_id=uuid.uuid4(), question="total revenue")

        frames = []
        async for frame in ctrl._stream_events(
            tenant_id="ten-a",
            workspace_id=uuid.uuid4(),
            request=request,
        ):
            frames.append(frame)

    parsed = _parse_sse_frames(frames)
    event_names = [f["event"] for f in parsed]

    assert "clarification" not in event_names


@pytest.mark.asyncio
async def test_sse_final_frame_contains_answer_fields():
    """The ``final`` SSE frame contains all expected AnswerResponse fields."""
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock, patch

    from flyquery.web.controllers.query_controller import QueryController

    settings = _FakeSettings()
    ctrl = QueryController.__new__(QueryController)
    ctrl._settings = settings
    ctrl._object_store = _FakeObjectStore()
    ctrl._query_repo = _FakeQueryRepo()
    ctrl._examples_service = _FakeExamplesService()
    ctrl._embedder = MagicMock()
    ctrl._ast_classifier = MagicMock()
    ctrl._scope_guard = MagicMock()
    ctrl._executor = _FakeExecutor(
        ExecutionResult(rows=[{"val": 42}], columns=["val"], row_count=1, truncated=False)
    )

    @asynccontextmanager
    async def _fake_factory():
        yield _FakeSession()

    ctrl._session_factory = _fake_factory

    grounded = _make_grounded()
    candidates = _make_candidates("SELECT 42 AS val")
    explanation = ResultExplanation(summary="The value is 42.", chart_hint="none")

    with (
        patch(
            "flyquery.web.controllers.query_controller.build_grounding_agent",
            return_value=_FakeAgent(grounded),
        ),
        patch(
            "flyquery.web.controllers.query_controller.build_generation_agent",
            return_value=_FakeAgent(candidates),
        ),
        patch("flyquery.web.controllers.query_controller.build_critic_agent", return_value=_FakeAgent(None)),
        patch(
            "flyquery.web.controllers.query_controller.build_explainer_agent",
            return_value=_FakeAgent(explanation),
        ),
        patch("flyquery.web.controllers.query_controller.HybridRetriever", return_value=_FakeRetriever()),
        patch("flyquery.web.controllers.query_controller.TableResolver", return_value=_FakeTableResolver()),
        patch("flyquery.web.controllers.query_controller.SearchIndex", return_value=MagicMock()),
        patch("flyquery.web.controllers.query_controller.build_reranker", return_value=_FakeReranker()),
    ):
        from flyquery.interfaces.query import QueryRequest

        request = QueryRequest(dataset_id=uuid.uuid4(), question="what is 42?")

        frames = []
        async for frame in ctrl._stream_events(
            tenant_id="ten-a",
            workspace_id=uuid.uuid4(),
            request=request,
        ):
            frames.append(frame)

    parsed = _parse_sse_frames(frames)
    final = next(f["data"] for f in parsed if f["event"] == "final")

    assert "query_id" in final
    assert "sql" in final
    assert final["execution_status"] in ("OK", "REFINED_OK", "FAILED", "REJECTED_BY_FIREWALL", None)
    assert "row_count" in final
    assert "explanation" in final
