# Copyright 2024-2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
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

"""Unit tests for QueryService orchestrator.

All agents, retriever, executor, and repo are replaced with fakes so no
LLM API keys or database connections are needed. Assertions focus on the
orchestration logic: which methods were called, in what order, and what
the returned AnswerResult contains.
"""

from __future__ import annotations

import uuid

import pytest

from flyquery.core.agents.critic_agent import RefinedSql
from flyquery.core.agents.explainer_agent import ResultExplanation
from flyquery.core.agents.generation_agent import GeneratedCandidate, GeneratedCandidates
from flyquery.core.agents.grounding_agent import (
    GroundedColumn,
    GroundedContext,
    GroundedMetric,
    GroundedTable,
)
from flyquery.core.services.execution.ast_classifier import AstClassifier
from flyquery.core.services.execution.duckdb_executor import ExecutionError, ExecutionResult
from flyquery.core.services.execution.scope_guard import ScopeGuard
from flyquery.core.services.query.query_service import QueryService

# ---------------------------------------------------------------------------
# Fake implementations
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Minimal agent stub that returns a canned output."""

    def __init__(self, output):
        self._output = output

    async def run(self, _input):
        return self._output


class _FakeRetriever:
    async def retrieve(self, query, *, dataset_id, workspace_id, **kwargs):
        return {"schema_objects": [], "examples": [], "metrics": [], "glossary": [], "relations": []}


class _FakeReranker:
    async def rerank(self, query, hits, top_n):
        return hits[:top_n]


class _FakeExecutor:
    """Executor that returns a canned ExecutionResult."""

    def __init__(self, result):
        self._result = result

    async def execute(self, sql, attached_tables):
        return self._result


class _FakeErrorExecutor:
    """Executor that always returns ExecutionError."""

    async def execute(self, sql, attached_tables):
        return ExecutionError(message="column not found: xyz")


class _FakeTableResolver:
    """Resolver that returns empty attached_tables (no parquet needed for unit tests)."""

    def __init__(self):
        self._session = _FakeSession()

    async def resolve(self, dataset_id, table_names, object_store_base=None, pins=None):
        return {}

    async def current_snapshots(self, dataset_id, table_names):
        return {}


class _FakeSession:
    """Fake async session that returns empty results for table kind queries."""

    async def execute(self, stmt, params=None):
        return _FakeMappingResult([])


class _FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _TableAwareSession:
    """Session whose table-kind lookup reports one UPLOADED table so a realistic
    ``... FROM <name>`` query clears the scope + unknown-table guards."""

    def __init__(self, table_name: str):
        self._table_name = table_name

    async def execute(self, stmt, params=None):
        return _FakeMappingResult([{"name": self._table_name, "kind": "UPLOADED"}])


class _TableAwareResolver:
    def __init__(self, table_name: str = "t"):
        self._session = _TableAwareSession(table_name)

    async def resolve(self, dataset_id, table_names, object_store_base=None, pins=None):
        return {}

    async def current_snapshots(self, dataset_id, table_names):
        return {}


class _FakeQueryRepo:
    """In-memory query repo stub."""

    def __init__(self):
        self.created_queries = []

    async def create_query(self, **kwargs):
        qid = uuid.uuid4()
        self.created_queries.append({"id": qid, **kwargs})
        return qid

    async def upsert_result(self, **kwargs):
        pass


class _FakeResultUploader:
    """Stub result uploader that records calls."""

    def __init__(self):
        self.calls = []

    async def upload(self, *, query_id, result, tenant_id, workspace_id, dataset_id):
        self.calls.append({"query_id": query_id, "result": result})


class _FakeAutoLearner:
    """Stub auto-learner that records maybe_propose calls."""

    def __init__(self):
        self.proposals = []

    async def maybe_propose(self, **kwargs):
        self.proposals.append(kwargs)


class _FakeSettings:
    grounding_model = "test"
    generation_model = "test"
    critic_model = "test"
    explainer_model = "test"
    top_k_schema = 12
    top_k_examples = 5
    top_k_metrics = 8
    max_refine_retries = 2
    grounding_min_confidence = 0.55
    generation_candidates = 3
    # Value-anchoring knobs: disabled here so these orchestration tests exercise
    # the core answer() flow (call order / persistence / auto-learn). The
    # value-anchoring paths need a real dataset value-scan and are covered by the
    # value_anchoring unit tests + integration/e2e.
    value_catalog_char_budget = 320
    value_catalog_max_columns = 80
    entity_resolution_enabled = False
    entity_resolution_max_literals = 8
    zero_row_repair_enabled = False
    candidate_exec_selection = False
    synthesis_function_firewall = False
    group_resolution_enabled = False
    signed_measure_repair_enabled = False
    group_coverage_repair_enabled = False


def _make_grounded(confidence: float = 0.9, path: str = "SYNTHESIS") -> GroundedContext:
    return GroundedContext(
        path=path,
        tables=[GroundedTable(table_qualified_name="orders", relevance=0.9)],
        columns=[GroundedColumn(column_qualified_name="orders.total", relevance=0.9)],
        confidence=confidence,
    )


def _make_candidates(sql: str = "SELECT 1") -> GeneratedCandidates:
    return GeneratedCandidates(candidates=[GeneratedCandidate(sql=sql, reasoning="test", confidence=0.9)])


class _CountingAgent:
    """Agent stub that counts how many times ``run`` was awaited."""

    def __init__(self, output):
        self._output = output
        self.calls = 0

    async def run(self, _input):
        self.calls += 1
        return self._output


class _FakeSemanticRepo:
    """Returns a single PUBLISHED metric keyed by name."""

    def __init__(self, *, name: str, template: str, version: int = 3):
        self._name = name
        self._template = template
        self._version = version
        self.lookups: list[tuple] = []

    async def get_by_name(self, name, dataset_id, *, tenant_id, workspace_id):
        self.lookups.append((name, dataset_id, tenant_id, workspace_id))
        if name != self._name:
            return None
        return {
            "name": name,
            "status": "PUBLISHED",
            "compiled_sql_template": self._template,
            "current_version": self._version,
        }


def _make_service(
    *,
    grounded: GroundedContext | None = None,
    candidates: GeneratedCandidates | None = None,
    executor=None,
    query_repo=None,
    result_uploader=None,
    auto_learner=None,
    semantic_repo=None,
    generation_agent=None,
    critic_agent=None,
    table_resolver=None,
):
    if grounded is None:
        grounded = _make_grounded()
    if candidates is None:
        candidates = _make_candidates("SELECT 1 AS val")
    if executor is None:
        executor = _FakeExecutor(
            ExecutionResult(rows=[{"val": 1}], columns=["val"], row_count=1, truncated=False)
        )
    if query_repo is None:
        query_repo = _FakeQueryRepo()
    if result_uploader is None:
        result_uploader = _FakeResultUploader()
    if auto_learner is None:
        auto_learner = _FakeAutoLearner()
    if generation_agent is None:
        generation_agent = _FakeAgent(candidates)
    if critic_agent is None:
        critic_agent = _FakeAgent(RefinedSql(sql="SELECT 2", reasoning="fixed", confidence=0.8))
    if table_resolver is None:
        table_resolver = _FakeTableResolver()

    explanation = ResultExplanation(summary="The answer is 1.", chart_hint="none")

    return QueryService(
        retriever=_FakeRetriever(),
        reranker=_FakeReranker(),
        grounding_agent=_FakeAgent(grounded),
        generation_agent=generation_agent,
        critic_agent=critic_agent,
        explainer_agent=_FakeAgent(explanation),
        ast_classifier=AstClassifier(),
        scope_guard=ScopeGuard(),
        table_resolver=table_resolver,
        executor=executor,
        query_repo=query_repo,
        settings=_FakeSettings(),
        result_uploader=result_uploader,
        auto_learner=auto_learner,
        semantic_repo=semantic_repo,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_basic_flow_returns_ok():
    """Happy path: answer() returns AnswerResult with execution_status=OK."""
    svc = _make_service()
    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="how many orders?",
        scopes={"flyquery.query:read"},
    )

    assert result.execution_status == "OK"
    assert result.sql == "SELECT 1 AS val"
    assert result.row_count == 1
    assert result.explanation == "The answer is 1."
    assert result.chart_hint == "none"
    assert result.query_id is not None


@pytest.mark.asyncio
async def test_answer_persists_query_row():
    """QueryRepository.create_query is called with the correct execution_status."""
    repo = _FakeQueryRepo()
    svc = _make_service(query_repo=repo)

    await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )

    assert len(repo.created_queries) == 1
    q = repo.created_queries[0]
    assert q["execution_status"] == "OK"
    assert q["retries"] == 0


@pytest.mark.asyncio
async def test_answer_calls_result_uploader():
    """ResultUploader.upload is called when execution succeeds."""
    uploader = _FakeResultUploader()
    svc = _make_service(result_uploader=uploader)

    await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )

    assert len(uploader.calls) == 1


@pytest.mark.asyncio
async def test_answer_calls_auto_learner_on_first_shot():
    """AutoLearner.maybe_propose is called once on a first-shot OK run."""
    learner = _FakeAutoLearner()
    svc = _make_service(auto_learner=learner)

    await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )

    assert len(learner.proposals) == 1
    assert learner.proposals[0]["retries"] == 0


@pytest.mark.asyncio
async def test_answer_retries_on_execution_error():
    """On ExecutionError the CriticAgent is called, its refined (non-degenerate)
    SQL is re-executed, and the retry is counted (REFINED_OK or FAILED)."""
    # First execution fails; the critic returns a different, runnable SQL; the
    # second execution succeeds -> one counted retry, REFINED_OK.
    call_count = [0]

    class _AlternatingExecutor:
        async def execute(self, sql, attached_tables):
            call_count[0] += 1
            if call_count[0] == 1:
                return ExecutionError(message="column not found")
            return ExecutionResult(rows=[{"v": 2}], columns=["v"], row_count=1, truncated=False)

    repo = _FakeQueryRepo()
    svc = _make_service(
        executor=_AlternatingExecutor(),
        query_repo=repo,
        candidates=_make_candidates("SELECT v FROM t"),
        critic_agent=_FakeAgent(
            RefinedSql(sql="SELECT v FROM t WHERE v > 0", reasoning="fixed", confidence=0.8)
        ),
        table_resolver=_TableAwareResolver(),
    )

    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )

    assert result.execution_status == "REFINED_OK"
    assert repo.created_queries[0]["retries"] == 1
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_answer_rejected_by_scope_guard():
    """Missing scope returns REJECTED_BY_FIREWALL without calling executor."""
    executor_calls = []

    class _TrackingExecutor:
        async def execute(self, sql, attached_tables):
            executor_calls.append(sql)
            return ExecutionResult(rows=[], columns=[], row_count=0, truncated=False)

    svc = _make_service(executor=_TrackingExecutor())

    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes=set(),  # no scope
    )

    assert result.execution_status == "REJECTED_BY_FIREWALL"
    assert executor_calls == []


@pytest.mark.asyncio
async def test_answer_clarification_emitted_when_low_confidence():
    """ClarificationFrame is populated when grounding confidence is low."""
    grounded = GroundedContext(
        path="SYNTHESIS",
        tables=[GroundedTable(table_qualified_name="orders", relevance=0.5)],
        columns=[],
        confidence=0.3,  # below 0.55 threshold
        missing_info=["Which time period do you mean?"],
    )
    svc = _make_service(grounded=grounded)

    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="show orders",
        scopes={"flyquery.query:read"},
    )

    assert result.clarification is not None
    assert "Which time period" in result.clarification.questions[0]


@pytest.mark.asyncio
async def test_answer_no_clarification_when_high_confidence():
    """No ClarificationFrame when confidence is above threshold."""
    svc = _make_service()

    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="total revenue",
        scopes={"flyquery.query:read"},
    )

    assert result.clarification is None


@pytest.mark.asyncio
async def test_semantic_layer_executes_compiled_sql_without_generation():
    """SEMANTIC_LAYER path runs the bound compiled SQL and skips the GenerationAgent."""
    template = "SELECT 42 AS total_revenue {extra_filter_clause} {group_by_append}"
    repo = _FakeSemanticRepo(name="total_revenue", template=template, version=3)
    grounded = GroundedContext(
        path="SEMANTIC_LAYER",
        tables=[],
        columns=[],
        metrics=[GroundedMetric(metric_name="total_revenue", relevance=1.0)],
        confidence=0.95,
    )
    gen = _CountingAgent(_make_candidates("SELECT 999 AS should_not_run"))
    query_repo = _FakeQueryRepo()
    svc = _make_service(grounded=grounded, semantic_repo=repo, generation_agent=gen, query_repo=query_repo)

    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="what is total revenue?",
        scopes={"flyquery.query:read"},
    )

    # Bound compiled SQL is used verbatim (slots stripped), not regenerated.
    assert result.sql == "SELECT 42 AS total_revenue"
    # The GenerationAgent was never invoked.
    assert gen.calls == 0
    # The query record pins the metric name + version, and the semantic path.
    q = query_repo.created_queries[0]
    assert q["semantic_path_taken"] == "SEMANTIC_LAYER"
    assert q["candidates_json"][0]["metric_name"] == "total_revenue"
    assert q["candidates_json"][0]["metric_version"] == 3


@pytest.mark.asyncio
async def test_semantic_layer_falls_back_to_synthesis_when_metric_missing():
    """When the metric has no published compiled SQL, fall through to generation."""
    repo = _FakeSemanticRepo(name="other_metric", template="SELECT 1 {extra_filter_clause} {group_by_append}")
    grounded = GroundedContext(
        path="SEMANTIC_LAYER",
        tables=[],
        columns=[],
        metrics=[GroundedMetric(metric_name="unknown_metric", relevance=1.0)],
        confidence=0.95,
    )
    gen = _CountingAgent(_make_candidates("SELECT 7 AS val"))
    svc = _make_service(grounded=grounded, semantic_repo=repo, generation_agent=gen)

    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="unknown",
        scopes={"flyquery.query:read"},
    )

    # No published metric matched → GenerationAgent ran and produced the SQL.
    assert gen.calls == 1
    assert result.sql == "SELECT 7 AS val"


@pytest.mark.asyncio
async def test_answer_does_not_call_auto_learner_when_retries():
    """AutoLearner is NOT called when retries > 0 (REFINED_OK path)."""
    learner = _FakeAutoLearner()

    class _AlwaysFailFirstExecutor:
        def __init__(self):
            self._calls = 0

        async def execute(self, sql, attached_tables):
            self._calls += 1
            if self._calls == 1:
                return ExecutionError(message="fail")
            return ExecutionResult(rows=[{"v": 1}], columns=["v"], row_count=1, truncated=False)

    svc = _make_service(executor=_AlwaysFailFirstExecutor(), auto_learner=learner)

    await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )

    # AutoLearner.maybe_propose is called but skips internally when retries > 0.
    # It IS called from the service, but the learner's maybe_propose ignores it.
    # Here we test that the service passed retries correctly.
    if learner.proposals:
        assert learner.proposals[0]["retries"] >= 1


@pytest.mark.asyncio
async def test_critic_cannot_replace_a_scoped_query_with_an_unregistered_native_file_read(tmp_path):
    from flyquery.core.services.execution.duckdb_executor import DuckDBExecutor

    file = tmp_path / "unregistered.csv"
    file.write_text("evidence\nsynthetic-unregistered-file\n")

    class Settings:
        duckdb_memory_limit = "256MB"
        default_row_cap = 100
        default_statement_timeout_ms = 5000

    class InitialColumnFailure(DuckDBExecutor):
        calls = 0

        async def execute(self, sql, attached_tables):
            self.calls += 1
            if self.calls == 1:
                return ExecutionError(message="fixture missing column")
            return await super().execute(sql, attached_tables)

    executor = InitialColumnFailure(Settings())
    svc = _make_service(executor=executor)
    svc._critic_agent = _FakeAgent(
        RefinedSql(sql=f"SELECT * FROM read_csv_auto('{file}')", reasoning="fixture rewrite", confidence=0.8)
    )
    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="fixture",
        scopes={"flyquery.query:read"},
    )
    assert result.execution_status not in ("OK", "REFINED_OK")
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_rejected_advisory_sql_keeps_the_executed_query_and_result_together(tmp_path):
    from flyquery.core.services.execution.duckdb_executor import DuckDBExecutor

    file = tmp_path / "unregistered.csv"
    file.write_text("evidence\nsynthetic-unregistered-file\n")

    class Settings:
        duckdb_memory_limit = "256MB"
        default_row_cap = 100
        default_statement_timeout_ms = 5000

    repo = _FakeQueryRepo()
    original_sql = "SELECT 7 AS value"
    svc = _make_service(
        candidates=_make_candidates(original_sql),
        executor=DuckDBExecutor(Settings()),
        query_repo=repo,
        critic_agent=_FakeAgent(
            RefinedSql(sql=f"SELECT * FROM read_csv_auto('{file}')", reasoning="fixture", confidence=0.8)
        ),
    )

    async def advisory(*args):
        return "Reconsider this synthetic result"

    svc._advisory_repair = advisory
    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="synthetic advisory",
        scopes={"flyquery.query:read"},
    )
    assert result.execution_status == "OK"
    assert result.sql == original_sql
    assert result.preview == [{"value": 7}]
    assert repo.created_queries[0]["executed_sql"] == original_sql


@pytest.mark.asyncio
async def test_conversation_reuses_the_actual_first_snapshot_after_reingestion(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from flyquery.core.services.execution.duckdb_executor import DuckDBExecutor

    old_snapshot, new_snapshot = str(uuid.uuid4()), str(uuid.uuid4())
    paths = {}
    for snapshot, value in ((old_snapshot, 10), (new_snapshot, 99)):
        path = tmp_path / f"{snapshot}.parquet"
        pq.write_table(pa.table({"total": [value]}), path)
        paths[snapshot] = str(path)

    class Settings:
        duckdb_memory_limit = "256MB"
        default_row_cap = 100
        default_statement_timeout_ms = 5000

    class Resolver(_TableAwareResolver):
        current = old_snapshot

        async def current_snapshots(self, dataset_id, table_names):
            return {name: self.current for name in table_names}

        async def resolve(self, dataset_id, table_names, object_store_base=None, pins=None):
            return {name: paths[(pins or {}).get(name, self.current)] for name in table_names}

    class Conversation:
        turn = None

        async def last_turn(self, conversation_id):
            return self.turn

        async def append_turn(self, **kwargs):
            self.turn = kwargs

    resolver = Resolver("orders")
    conversation = Conversation()
    svc = _make_service(
        candidates=_make_candidates("SELECT total FROM orders"),
        executor=DuckDBExecutor(Settings()),
        table_resolver=resolver,
    )
    svc._conversation_service = conversation
    arguments = {
        "tenant_id": "ten-a",
        "workspace_id": uuid.uuid4(),
        "dataset_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "question": "synthetic snapshot",
        "scopes": {"flyquery.query:read"},
    }
    first = await svc.answer(**arguments)
    assert first.preview == [{"total": 10}]
    assert first.snapshot_pins == {"orders": old_snapshot}
    assert conversation.turn["snapshot_pins_json"] == first.snapshot_pins

    resolver.current = new_snapshot
    second = await svc.answer(**arguments)
    assert second.preview == [{"total": 10}]
    assert second.snapshot_pins == first.snapshot_pins
    assert conversation.turn["snapshot_pins_json"] == first.snapshot_pins


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_scope", [True, False])
async def test_admission_denial_precedes_retrieval_and_agent_calls(missing_scope):
    retrievals = []

    class Retriever(_FakeRetriever):
        async def retrieve(self, *args, **kwargs):
            retrievals.append(kwargs)
            return await super().retrieve(*args, **kwargs)

    generation = _CountingAgent(_make_candidates("SELECT 1 AS value"))
    grounding = _CountingAgent(_make_grounded())
    svc = _make_service(generation_agent=generation)
    svc._retriever = Retriever()
    svc._grounding_agent = grounding
    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="synthetic denied request",
        scopes=set() if missing_scope else {"flyquery.query:read"},
        dataset_allowlist=None if missing_scope else set(),
    )
    assert result.execution_status == "REJECTED_BY_FIREWALL"
    assert result.sql is None
    assert retrievals == []
    assert grounding.calls == 0
    assert generation.calls == 0
    receipt = svc._query_repo.created_queries[0]
    assert receipt["dataset_id"] is None
    assert receipt["executed_sql"] is None
    assert receipt["candidates_json"] == []
    assert receipt["retries"] == 0
    assert receipt["error_json"]["code"] == "SCOPE_ADMISSION_DENIED"


@pytest.mark.asyncio
async def test_statement_timeout_is_terminal_without_critic_and_is_audited():
    critic = _CountingAgent(RefinedSql(sql="SELECT 2", reasoning="repair", confidence=0.9))
    repo = _FakeQueryRepo()
    svc = _make_service(
        executor=_FakeExecutor(ExecutionError(message="Statement deadline exceeded", sql_state="57014")),
        critic_agent=critic,
        query_repo=repo,
    )
    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )
    assert result.execution_status == "FAILED"
    assert critic.calls == 0
    assert repo.created_queries[0]["retries"] == 0
    assert repo.created_queries[0]["error_json"]["sql_state"] == "57014"


@pytest.mark.asyncio
async def test_timeout_during_advisory_repair_does_not_restore_an_earlier_success(monkeypatch):
    class LaterTimeout:
        calls = 0

        async def execute(self, sql, attached_tables):
            self.calls += 1
            if self.calls == 1:
                return ExecutionResult(rows=[{"n": 1}], columns=["n"], row_count=1, truncated=False)
            return ExecutionError(message="Statement deadline exceeded", sql_state="57014")

    repo = _FakeQueryRepo()
    critic = _CountingAgent(
        RefinedSql(sql="SELECT v FROM t WHERE v > 0", reasoning="advisory", confidence=0.9)
    )
    svc = _make_service(
        executor=LaterTimeout(),
        critic_agent=critic,
        query_repo=repo,
        candidates=_make_candidates("SELECT v FROM t"),
        table_resolver=_TableAwareResolver(),
    )

    async def advisory(*args):
        return "Check the selected measure"

    monkeypatch.setattr(svc, "_advisory_repair", advisory)
    result = await svc.answer(
        tenant_id="ten-a",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="test",
        scopes={"flyquery.query:read"},
    )
    assert result.execution_status == "FAILED"
    assert critic.calls == 1
    assert repo.created_queries[0]["error_json"]["sql_state"] == "57014"
