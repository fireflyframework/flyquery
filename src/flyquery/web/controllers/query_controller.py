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

"""Query pipeline REST controller.

``/api/v1/query`` — sync NL → SQL → result endpoint.

Path conventions:
* ``POST /api/v1/query``          -- full pipeline (sync): Grounding → Gen → AST → Exec → Explainer
* ``POST /api/v1/query:explain``  -- Grounding + Generation only (no execution)
* ``POST /api/v1/query:validate`` -- Grounding + Generation + AST + ScopeGuard (no execution)
* ``POST /api/v1/query/stream``   -- SSE event stream
  (schema_linked → sql_generated → executed → explained → final)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pyfly.container import rest_controller
from pyfly.web import Body, Valid, post_mapping, request_mapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import StreamingResponse

from flyquery.config import FlyquerySettings
from flyquery.core.agents.critic_agent import build_critic_agent
from flyquery.core.agents.explainer_agent import build_explainer_agent
from flyquery.core.agents.generation_agent import build_generation_agent
from flyquery.core.agents.grounding_agent import build_grounding_agent
from flyquery.core.services.examples.auto_learner import AutoLearner
from flyquery.core.services.examples.examples_service import ExamplesService
from flyquery.core.services.execution.ast_classifier import AstClassifier
from flyquery.core.services.execution.duckdb_executor import DuckDBExecutor
from flyquery.core.services.execution.scope_guard import ScopeGuard, ScopeGuardError
from flyquery.core.services.execution.table_resolver import TableResolver
from flyquery.core.services.query.query_repository import QueryRepository
from flyquery.core.services.query.query_service import (
    QueryService,
    _render_critic_prompt,
    _render_generation_prompt,
    _render_grounding_prompt,
)
from flyquery.core.services.query.result_uploader import ResultUploader
from flyquery.core.services.retrieval.embedder import Embedder
from flyquery.core.services.retrieval.hybrid_retriever import HybridRetriever
from flyquery.core.services.retrieval.reranker import build_reranker
from flyquery.core.services.retrieval.search_index import SearchIndex
from flyquery.core.services.semantic.semantic_repository import SemanticRepository
from flyquery.core.services.storage.object_store import ObjectStore
from flyquery.interfaces.query import (
    AnswerResponse,
    BatchQueryItem,
    BatchQueryRequest,
    BatchQueryResponse,
    BatchQueryResultItem,
    ClarificationFrame,
    ExplainResponse,
    QueryRequest,
    ValidateResponse,
)
from flyquery.web.conventions import (
    IdempotencyStore,
    InvalidRequest,
    tenant_context_from_request,
)
from flyquery.web.idempotent_handler import replay_dedup

logger = logging.getLogger(__name__)

# Default caller scopes for the user-tier endpoints (no token gate in Phase D;
# agent-tier mirrors in Phase F will enforce token scopes).
_DEFAULT_USER_SCOPES: set[str] = {"flyquery.query:read"}


def _sse_frame(event: str, payload: Any) -> bytes:
    """Format one SSE frame: ``event: <name>\\ndata: <json>\\n\\n``."""
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n".encode()


@rest_controller
@request_mapping("/api/v1/query")
class QueryController:
    """REST adapter for the NL → SQL query pipeline.

    Per-request QueryService construction
    ======================================
    ``QueryService`` depends on request-scoped objects (``SearchIndex`` +
    ``TableResolver`` both need a live ``AsyncSession``). The controller
    therefore builds a fresh ``QueryService`` inside each handler by opening
    a new session from the injected ``async_sessionmaker``.

    The singleton dependencies (``DuckDBExecutor``, ``AstClassifier``,
    ``ScopeGuard``, ``ObjectStore``, ``QueryRepository``) are wired by the
    DI container at startup and held on ``self``.
    """

    def __init__(
        self,
        settings: FlyquerySettings,
        session: async_sessionmaker[AsyncSession],
        object_store: ObjectStore,
        query_repository: QueryRepository,
        semantic_repository: SemanticRepository,
        examples_service: ExamplesService,
        embedder: Embedder,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._settings = settings
        self._session_factory = session
        self._object_store = object_store
        self._query_repo = query_repository
        self._semantic_repo = semantic_repository
        self._examples_service = examples_service
        self._embedder = embedder
        self._idempotency_store = idempotency_store

        # Singletons that don't need a session
        self._ast_classifier = AstClassifier()
        self._scope_guard = ScopeGuard()
        self._executor = DuckDBExecutor(settings)

    async def _guarded_execute(
        self,
        sql: str,
        ast: Any,
        table_kinds: dict[str, str],
        resolver: TableResolver,
        dataset_id: uuid.UUID,
        bundle: dict,
    ) -> Any:
        """Apply ScopeGuard + bad-tables firewall, then execute.

        Mirrors the guards in ``QueryService.answer`` so the streaming path
        enforces the same dataset isolation and table-existence checks.
        Returns an ``ExecutionResult`` or an ``ExecutionError`` (which the
        caller's critic loop can attempt to refine).
        """
        from flyquery.core.services.execution.duckdb_executor import ExecutionError

        try:
            self._scope_guard.check(
                classification=ast,
                scopes=_DEFAULT_USER_SCOPES,
                table_kinds_by_name=table_kinds,
                dataset_allowlist=None,
                dataset_of_table={t: str(dataset_id) for t in ast.table_refs},
            )
        except ScopeGuardError as exc:
            return ExecutionError(message=f"Rejected by firewall: {exc}")

        ref_set = {t for t in ast.table_refs if t}
        bad_tables = sorted(ref_set - set(table_kinds.keys()))
        if bad_tables:
            real_tables = sorted(table_kinds.keys()) + [
                (getattr(h, "metadata", {}) or {}).get("qualified_name", "").rsplit(".", 1)[-1]
                for h in (bundle.get("schema_inventory") or [])
                if (getattr(h, "metadata", {}) or {}).get("kind") == "TABLE"
            ]
            real_tables = [t for t in dict.fromkeys(real_tables) if t]
            return ExecutionError(
                message=(
                    f"Table(s) {bad_tables!r} do not exist in this dataset. "
                    f"Pick ONLY from: {real_tables[:80]!r}."
                )
            )

        attached = await resolver.resolve(dataset_id, list(ast.table_refs))
        return await self._executor.execute(sql, attached)

    def _build_service(self, db_session: AsyncSession) -> QueryService:
        """Build a per-request QueryService around the provided session."""
        index = SearchIndex(db_session)
        retriever = HybridRetriever(
            index=index,
            embedder=self._embedder,
            rrf_k=self._settings.rrf_k,
        )

        # Build a NoopReranker here; the actual reranker bean is injected via
        # configuration in production but for the controller we use the same
        # factory pattern as the configuration.py bean.
        reranker = build_reranker(self._settings)

        table_resolver = TableResolver(session=db_session, settings=self._settings)
        uploader = ResultUploader(
            object_store=self._object_store,
            query_repo=self._query_repo,
            settings=self._settings,
        )
        auto_learner = AutoLearner(examples_service=self._examples_service)

        return QueryService(
            retriever=retriever,
            reranker=reranker,
            grounding_agent=build_grounding_agent(self._settings),
            generation_agent=build_generation_agent(self._settings),
            critic_agent=build_critic_agent(self._settings),
            explainer_agent=build_explainer_agent(self._settings),
            ast_classifier=self._ast_classifier,
            scope_guard=self._scope_guard,
            table_resolver=table_resolver,
            executor=self._executor,
            query_repo=self._query_repo,
            settings=self._settings,
            result_uploader=uploader,
            auto_learner=auto_learner,
            semantic_repo=self._semantic_repo,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/query (sync full pipeline)
    # ------------------------------------------------------------------

    @post_mapping("")
    async def query(
        self,
        http_request: Request,
        body: Valid[Body[QueryRequest]],
    ) -> AnswerResponse:
        """Run the full NL → SQL → result pipeline and return a synchronous answer.

        :param http_request: Starlette request (provides tenant context headers)
        :param body: validated QueryRequest
        :return: AnswerResponse with SQL, preview rows, chart hint, and explanation
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)

        async with self._session_factory() as db_session:
            svc = self._build_service(db_session)
            result = await svc.answer(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=body.dataset_id,
                question=body.question,
                scopes=_DEFAULT_USER_SCOPES,
                conversation_id=body.conversation_id,
            )

        return AnswerResponse(
            query_id=result.query_id,
            sql=result.sql,
            execution_status=result.execution_status,
            preview=result.preview,
            row_count=result.row_count,
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
            chart_hint=result.chart_hint,
            explanation=result.explanation,
            clarification=result.clarification,
            grounded_summary=result.grounded_summary,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/query:batch (parallel multi-question)
    # ------------------------------------------------------------------

    @post_mapping(":batch")
    async def batch(
        self,
        http_request: Request,
        body: Valid[Body[BatchQueryRequest]],
    ) -> BatchQueryResponse:
        """Run multiple NL questions in parallel through the full pipeline.

        Each item runs the same pipeline as ``POST /api/v1/query``, fanned
        out via ``asyncio.gather`` with a Semaphore-style concurrency cap
        (mirrors the bulk-file endpoint). Per-question failures do NOT
        abort the batch -- failed items carry ``status="FAILED"`` +
        ``error`` and the response aggregates ``succeeded`` / ``failed``
        counts.

        Use this for dashboard refreshes (one batch with N panel queries),
        comparison reports (same question against M datasets), or SDK
        callers that want to amortise auth + tenant context across many
        questions.

        Replay-dedup'd via ``Idempotency-Key`` when present (optional on
        the user tier). A retried batch with the same key returns the
        cached aggregate without re-running any question -- important
        when a single batch represents tens of LLM calls.
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)

        async def _ask(idx: int, item: BatchQueryItem) -> BatchQueryResultItem:
            try:
                async with self._session_factory() as db_session:
                    svc = self._build_service(db_session)
                    r = await svc.answer(
                        tenant_id=ctx.tenant_id,
                        workspace_id=workspace_id,
                        dataset_id=item.dataset_id,
                        question=item.question,
                        scopes=_DEFAULT_USER_SCOPES,
                        conversation_id=item.conversation_id,
                    )
                return BatchQueryResultItem(
                    index=idx,
                    status="OK",
                    query_id=r.query_id,
                    sql=r.sql,
                    execution_status=r.execution_status,
                    preview=r.preview,
                    row_count=r.row_count,
                    elapsed_ms=r.elapsed_ms,
                    chart_hint=r.chart_hint,
                    explanation=r.explanation,
                    grounded_summary=r.grounded_summary,
                )
            except Exception as exc:  # noqa: BLE001
                return BatchQueryResultItem(
                    index=idx,
                    status="FAILED",
                    error=str(exc),
                )

        async def _do_batch() -> BatchQueryResponse:
            results = await asyncio.gather(*[_ask(i, item) for i, item in enumerate(body.queries)])
            succeeded = sum(1 for r in results if r.status == "OK")
            return BatchQueryResponse(
                results=list(results),
                total_queries=len(results),
                succeeded=succeeded,
                failed=len(results) - succeeded,
            )

        return await replay_dedup(
            request=http_request,
            store=self._idempotency_store,
            tenant_id=ctx.tenant_id,
            route="POST /api/v1/query:batch",
            handler=_do_batch,
            status_code=200,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/query:explain (Grounding + Generation only)
    # ------------------------------------------------------------------

    @post_mapping(":explain")
    async def explain(
        self,
        http_request: Request,
        body: Valid[Body[QueryRequest]],
    ) -> ExplainResponse:
        """Run Grounding + Generation but stop before AST/execution.

        Useful for previewing the generated SQL without paying execution costs.

        :param http_request: Starlette request
        :param body: validated QueryRequest
        :return: ExplainResponse with candidate SQL and reasoning
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)

        async with self._session_factory() as db_session:
            index = SearchIndex(db_session)
            retriever = HybridRetriever(index=index, embedder=self._embedder, rrf_k=self._settings.rrf_k)
            reranker = build_reranker(self._settings)

            bundle = await retriever.retrieve(
                body.question,
                dataset_id=body.dataset_id,
                workspace_id=workspace_id,
                top_k_schema=self._settings.top_k_schema * 3,
            )
            schema_hits = bundle.get("schema_objects", [])
            reranked = await reranker.rerank(body.question, schema_hits, top_n=self._settings.top_k_schema)
            bundle["schema_objects"] = reranked

            grounding_agent = build_grounding_agent(self._settings)
            grounded_run = await grounding_agent.run(
                _render_grounding_prompt(question=body.question, bundle=bundle, starting_point_sql=None)
            )
            grounded = getattr(grounded_run, "output", grounded_run)

            generation_agent = build_generation_agent(self._settings)
            gen_run = await generation_agent.run(
                _render_generation_prompt(
                    body.question, grounded, None, schema_inventory=bundle.get("schema_inventory")
                )
            )
            gen_out = getattr(gen_run, "output", gen_run)
            candidate = gen_out.candidates[0] if gen_out.candidates else None

        clarification: ClarificationFrame | None = None
        if grounded.confidence < self._settings.grounding_min_confidence and grounded.missing_info:
            clarification = ClarificationFrame(questions=grounded.missing_info, reasons=[])

        return ExplainResponse(
            sql=candidate.sql if candidate else "",
            reasoning=candidate.reasoning if candidate else "generation produced no candidate",
            confidence=candidate.confidence if candidate else 0.0,
            grounded_summary={
                "path": grounded.path,
                "confidence": grounded.confidence,
                "table_count": len(grounded.tables),
            },
            clarification=clarification,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/query:validate (Grounding + Generation + AST + scope check)
    # ------------------------------------------------------------------

    @post_mapping(":validate")
    async def validate(
        self,
        http_request: Request,
        body: Valid[Body[QueryRequest]],
    ) -> ValidateResponse:
        """Run Grounding + Generation + AST classification + ScopeGuard check.

        Returns the classification and any scope error without executing the SQL.

        :param http_request: Starlette request
        :param body: validated QueryRequest
        :return: ValidateResponse with AST classification and optional scope_error
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)

        async with self._session_factory() as db_session:
            index = SearchIndex(db_session)
            retriever = HybridRetriever(index=index, embedder=self._embedder, rrf_k=self._settings.rrf_k)
            reranker = build_reranker(self._settings)

            bundle = await retriever.retrieve(
                body.question,
                dataset_id=body.dataset_id,
                workspace_id=workspace_id,
                top_k_schema=self._settings.top_k_schema * 3,
            )
            schema_hits = bundle.get("schema_objects", [])
            reranked = await reranker.rerank(body.question, schema_hits, top_n=self._settings.top_k_schema)
            bundle["schema_objects"] = reranked

            grounding_agent = build_grounding_agent(self._settings)
            grounded_run = await grounding_agent.run(
                _render_grounding_prompt(question=body.question, bundle=bundle, starting_point_sql=None)
            )
            grounded = getattr(grounded_run, "output", grounded_run)

            generation_agent = build_generation_agent(self._settings)
            gen_run = await generation_agent.run(
                _render_generation_prompt(
                    body.question, grounded, None, schema_inventory=bundle.get("schema_inventory")
                )
            )
            gen_out = getattr(gen_run, "output", gen_run)
            chosen_sql = gen_out.candidates[0].sql if gen_out.candidates else ""

        ast = self._ast_classifier.classify(chosen_sql)

        scope_error: str | None = None
        try:
            self._scope_guard.check(
                classification=ast,
                scopes=_DEFAULT_USER_SCOPES,
                table_kinds_by_name={},
                dataset_allowlist=None,
                dataset_of_table={},
            )
        except ScopeGuardError as exc:
            scope_error = str(exc)

        clarification: ClarificationFrame | None = None
        if grounded.confidence < self._settings.grounding_min_confidence and grounded.missing_info:
            clarification = ClarificationFrame(questions=grounded.missing_info, reasons=[])

        return ValidateResponse(
            sql=chosen_sql,
            ast_classification=ast.classification,
            table_refs=list(ast.table_refs),
            single_statement=ast.single_statement,
            scope_error=scope_error,
            clarification=clarification,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/query/stream (SSE event stream)
    # ------------------------------------------------------------------

    @post_mapping("/stream")
    async def stream(
        self,
        http_request: Request,
        body: Valid[Body[QueryRequest]],
    ) -> StreamingResponse:
        """Run the full pipeline as a Server-Sent Events stream.

        Event sequence:
        1. ``schema_linked``   — after grounding completes
        2. ``clarification``   — (optional) when confidence < threshold + missing_info
        3. ``sql_generated``   — after generation
        4. ``executed``        — after DuckDB execution
        5. ``explained``       — after ExplainerAgent
        6. ``final``           — full AnswerResponse JSON

        :param http_request: Starlette request
        :param body: validated QueryRequest (body already consumed by pyfly)
        :return: StreamingResponse with ``text/event-stream`` content type
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)

        return StreamingResponse(
            self._stream_events(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                request=body,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    async def _stream_events(
        self,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        request: QueryRequest,
    ) -> AsyncIterator[bytes]:
        """Async generator that yields SSE frames for each pipeline stage."""

        from flyquery.core.services.execution.duckdb_executor import ExecutionError, ExecutionResult

        start_ms = _now_ms()

        async with self._session_factory() as db_session:
            index = SearchIndex(db_session)
            retriever = HybridRetriever(index=index, embedder=self._embedder, rrf_k=self._settings.rrf_k)
            reranker = build_reranker(self._settings)

            # Stage 1: retrieve + ground (same retrieval params + rendered
            # prompt as the sync POST /query path, so the streaming path is
            # not blind to the column-value catalogue, examples, metrics).
            bundle = await retriever.retrieve(
                request.question,
                dataset_id=request.dataset_id,
                workspace_id=workspace_id,
                top_k_schema=self._settings.top_k_schema * 3,
                top_k_examples=self._settings.top_k_examples,
                top_k_metrics=self._settings.top_k_metrics,
            )
            schema_hits = bundle.get("schema_objects", [])
            reranked = await reranker.rerank(request.question, schema_hits, top_n=self._settings.top_k_schema)
            bundle["schema_objects"] = reranked

            grounding_agent = build_grounding_agent(self._settings)
            grounded_run = await grounding_agent.run(
                _render_grounding_prompt(question=request.question, bundle=bundle, starting_point_sql=None)
            )
            grounded = getattr(grounded_run, "output", grounded_run)

            yield _sse_frame(
                "schema_linked",
                {
                    "semantic_path": grounded.path,
                    "confidence": grounded.confidence,
                    "candidate_table_count": len(grounded.tables),
                    "missing_info": grounded.missing_info,
                    "grounded_summary": {
                        "path": grounded.path,
                        "confidence": grounded.confidence,
                        "table_count": len(grounded.tables),
                    },
                },
            )

            # Stage 2 (optional): clarification
            if grounded.confidence < self._settings.grounding_min_confidence and grounded.missing_info:
                yield _sse_frame(
                    "clarification",
                    {
                        "questions": grounded.missing_info,
                        "reasons": [],
                    },
                )

            # Stage 3: generate SQL
            generation_agent = build_generation_agent(self._settings)
            gen_run = await generation_agent.run(
                _render_generation_prompt(
                    request.question, grounded, None, schema_inventory=bundle.get("schema_inventory")
                )
            )
            gen_out = getattr(gen_run, "output", gen_run)
            candidates = gen_out.candidates
            chosen_sql = candidates[0].sql if candidates else ""

            yield _sse_frame(
                "sql_generated",
                {
                    "candidate_count": len(candidates),
                    "chosen_index": 0,
                    "candidate_summaries": [
                        {"sql_preview": c.sql[:120], "confidence": c.confidence} for c in candidates
                    ],
                },
            )

            # Stage 4: AST + firewall/scope guards + execute (with critic loop).
            # _guarded_execute applies the SAME ScopeGuard + bad-tables firewall
            # the sync path enforces, so streaming callers cannot bypass dataset
            # isolation or run SQL against a non-existent/cross-dataset table.
            ast = self._ast_classifier.classify(chosen_sql)
            table_resolver = TableResolver(session=db_session, settings=self._settings)
            table_kinds = await table_resolver.table_kinds_by_name(request.dataset_id, list(ast.table_refs))
            exec_result = await self._guarded_execute(
                chosen_sql, ast, table_kinds, table_resolver, request.dataset_id, bundle
            )
            retries = 0

            while isinstance(exec_result, ExecutionError) and retries < self._settings.max_refine_retries:
                critic_agent = build_critic_agent(self._settings)
                refined_run = await critic_agent.run(
                    _render_critic_prompt(
                        question=request.question,
                        failing_sql=chosen_sql,
                        error_message=exec_result.message,
                        grounded=grounded,
                        schema_inventory=bundle.get("schema_inventory"),
                    )
                )
                refined = getattr(refined_run, "output", refined_run)
                chosen_sql = refined.sql
                ast = self._ast_classifier.classify(chosen_sql)
                table_kinds = await table_resolver.table_kinds_by_name(
                    request.dataset_id, list(ast.table_refs)
                )
                exec_result = await self._guarded_execute(
                    chosen_sql, ast, table_kinds, table_resolver, request.dataset_id, bundle
                )
                retries += 1

            snapshot_pins: dict = {}
            if isinstance(exec_result, ExecutionResult):
                yield _sse_frame(
                    "executed",
                    {
                        "row_count": exec_result.row_count,
                        "elapsed_ms": _now_ms() - start_ms,
                        "retried_after_error": retries > 0,
                        "truncated": exec_result.truncated,
                        "snapshot_pins": snapshot_pins,
                    },
                )
            else:
                yield _sse_frame(
                    "executed",
                    {
                        "error": exec_result.message,
                        "retried_after_error": retries > 0,
                        "snapshot_pins": snapshot_pins,
                    },
                )

            # Stage 5: explain
            explanation_obj = None
            if isinstance(exec_result, ExecutionResult):
                explainer_agent = build_explainer_agent(self._settings)
                explanation_obj = await explainer_agent.run(
                    {
                        "question": request.question,
                        "sql": chosen_sql,
                        "row_count": exec_result.row_count,
                        "preview_rows": exec_result.rows[:50],
                    }
                )
                yield _sse_frame(
                    "explained",
                    {
                        "summary": explanation_obj.summary,
                        "chart_hint": explanation_obj.chart_hint,
                    },
                )

            # Persist + upload
            uploader = ResultUploader(
                object_store=self._object_store,
                query_repo=self._query_repo,
                settings=self._settings,
            )
            auto_learner = AutoLearner(examples_service=self._examples_service)
            elapsed = _now_ms() - start_ms

            execution_status = (
                "OK"
                if isinstance(exec_result, ExecutionResult) and retries == 0
                else "REFINED_OK"
                if isinstance(exec_result, ExecutionResult)
                else "FAILED"
            )

            query_id = await self._query_repo.create_query(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                dataset_id=request.dataset_id,
                question=request.question,
                semantic_path_taken=grounded.path,
                candidates_json=[c.model_dump() for c in candidates],
                chosen_candidate_index=0,
                executed_sql=chosen_sql,
                ast_classification=ast.classification,
                execution_status=execution_status,
                retries=retries,
                row_count=exec_result.row_count if isinstance(exec_result, ExecutionResult) else None,
                elapsed_ms=elapsed,
                clarification_emitted=grounded.confidence < self._settings.grounding_min_confidence
                and bool(grounded.missing_info),
                clarification_json=None,
                pii_findings_json=None,
                error_json={"message": exec_result.message}
                if isinstance(exec_result, ExecutionError)
                else None,
                model_grounding=self._settings.grounding_model,
                model_generation=self._settings.generation_model,
            )

            if isinstance(exec_result, ExecutionResult):
                await uploader.upload(
                    query_id=query_id,
                    result=exec_result,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    dataset_id=request.dataset_id,
                )
                if execution_status == "OK":
                    await auto_learner.maybe_propose(
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        dataset_id=request.dataset_id,
                        question=request.question,
                        generated_sql=chosen_sql,
                        retries=retries,
                        pii_findings=[],
                        query_id=query_id,
                    )

            # Stage 6: final
            answer = AnswerResponse(
                query_id=query_id,
                sql=chosen_sql,
                execution_status=execution_status,  # type: ignore[arg-type]
                preview=exec_result.rows[:10] if isinstance(exec_result, ExecutionResult) else None,
                row_count=exec_result.row_count if isinstance(exec_result, ExecutionResult) else None,
                truncated=exec_result.truncated if isinstance(exec_result, ExecutionResult) else False,
                elapsed_ms=elapsed,
                chart_hint=explanation_obj.chart_hint if explanation_obj else None,
                explanation=explanation_obj.summary if explanation_obj else None,
                clarification=ClarificationFrame(questions=grounded.missing_info or [], reasons=[])
                if grounded.confidence < self._settings.grounding_min_confidence and grounded.missing_info
                else None,
                grounded_summary={
                    "path": grounded.path,
                    "confidence": grounded.confidence,
                    "table_count": len(grounded.tables),
                },
            )
            yield _sse_frame("final", answer.model_dump(mode="json"))


def _now_ms() -> int:
    """Return current monotonic time in milliseconds."""
    import time

    return time.monotonic_ns() // 1_000_000


def _parse_workspace_id(workspace_id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(workspace_id_str))
    except (ValueError, AttributeError) as exc:
        raise InvalidRequest(f"workspace_id header {workspace_id_str!r} is not a valid UUID") from exc
