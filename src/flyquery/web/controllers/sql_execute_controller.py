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

"""Direct SQL execution REST controller.

``/api/v1/sql:execute`` — execute raw SQL directly against the dataset's
Parquet snapshot, bypassing the agent pipeline entirely. Gated behind the
workspace flag ``allow_direct_sql=true``.

Path conventions:
* ``POST /api/v1/sql:execute``        -- sync execution (AST → scope → DuckDB)
* ``POST /api/v1/sql:execute/stream`` -- SSE stream (ast_classified → executed → final)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pyfly.container import rest_controller
from pyfly.web import Body, Valid, post_mapping, request_mapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import StreamingResponse

from flyquery.config import FlyquerySettings
from flyquery.core.services.execution.ast_classifier import AstClassifier
from flyquery.core.services.execution.duckdb_executor import (
    DmlMutationResult,
    DuckDBExecutor,
    ExecutionResult,
)
from flyquery.core.services.execution.scope_guard import ScopeGuard, ScopeGuardError
from flyquery.core.services.execution.table_resolver import TableResolver
from flyquery.core.services.query.query_repository import QueryRepository
from flyquery.core.services.query.result_uploader import ResultUploader
from flyquery.core.services.storage.object_store import ObjectStore
from flyquery.core.services.tables.schema_snapshot_repository import (
    SchemaSnapshotRepository,
)
from flyquery.core.services.tables.table_repository import TableRepository
from flyquery.core.services.workspaces.workspace_service import WorkspaceService
from flyquery.interfaces.sql_execute import SqlExecuteRequest, SqlExecuteResponse
from flyquery.web.conventions import (
    FireflyHTTPException,
    InvalidRequest,
    tenant_context_from_request,
)

logger = logging.getLogger(__name__)

_DEFAULT_SCOPES: set[str] = {"flyquery.sql:execute"}


class DirectSqlForbidden(FireflyHTTPException):
    status = 403
    code = "direct_sql_forbidden"
    title = "Direct SQL execution is not enabled for this workspace"


def _sse_frame(event: str, payload: Any) -> bytes:
    """Format one SSE frame."""
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n".encode()


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _parse_workspace_id(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(s))
    except (ValueError, AttributeError) as exc:
        raise InvalidRequest(f"workspace_id {s!r} is not a valid UUID") from exc


@rest_controller
@request_mapping("/api/v1")
class SqlExecuteController:
    """REST adapter for direct SQL execution.

    Workspace must have ``allow_direct_sql=true``. The SQL is classified
    by the AST classifier and checked by the scope guard before being
    executed against the dataset's Parquet snapshots via DuckDB. The agent
    pipeline (Grounding / Generation / Critic / Explainer) is skipped.

    :param settings: application settings
    :param session: async session factory
    :param object_store: blob store for result Parquet
    :param query_repository: repository for flyquery_queries
    :param workspace_service: used to check allow_direct_sql flag
    """

    def __init__(
        self,
        settings: FlyquerySettings,
        session: async_sessionmaker[AsyncSession],
        object_store: ObjectStore,
        query_repository: QueryRepository,
        workspace_service: WorkspaceService,
        table_repository: TableRepository,
        schema_snapshot_repository: SchemaSnapshotRepository,
    ) -> None:
        self._settings = settings
        self._session_factory = session
        self._object_store = object_store
        self._query_repo = query_repository
        self._workspace_service = workspace_service
        self._table_repo = table_repository
        self._snapshot_repo = schema_snapshot_repository

        self._ast_classifier = AstClassifier()
        self._scope_guard = ScopeGuard()
        self._executor = DuckDBExecutor(settings)

    # ------------------------------------------------------------------
    # POST /api/v1/sql:execute  (sync)
    # ------------------------------------------------------------------

    @post_mapping("/sql:execute")
    async def execute(
        self,
        http_request: Request,
        body: Valid[Body[SqlExecuteRequest]],
    ) -> SqlExecuteResponse:
        """Execute a SQL statement directly against the workspace's dataset Parquet.

        Requires the workspace flag ``allow_direct_sql=true``. The SQL is
        AST-classified and scope-checked; the agent pipeline is skipped.

        :param http_request: Starlette request
        :param body: validated SqlExecuteRequest
        :return: SqlExecuteResponse with preview rows and execution metadata
        :raises DirectSqlForbidden: when workspace.allow_direct_sql is False
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)
        start_ms = _now_ms()

        await self._assert_direct_sql_enabled(workspace_id)

        ast = self._ast_classifier.classify(body.sql)
        registered = await self._table_repo.list_kinds_for_dataset_by_names(
            body.dataset_id, list(ast.table_refs)
        )
        table_kinds = {row["name"]: row["kind"] for row in registered}
        dataset_of_table = {name: str(body.dataset_id) for name in table_kinds}

        scope_error: str | None = None
        try:
            self._scope_guard.check(
                classification=ast,
                scopes=_DEFAULT_SCOPES,
                table_kinds_by_name=table_kinds,
                dataset_allowlist=None,
                dataset_of_table=dataset_of_table,
            )
        except ScopeGuardError as exc:
            scope_error = str(exc)

        if scope_error:
            elapsed = _now_ms() - start_ms
            query_id = await self._query_repo.create_query(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=body.dataset_id,
                question=body.sql,
                semantic_path_taken=None,
                candidates_json=[],
                chosen_candidate_index=None,
                executed_sql=body.sql,
                ast_classification=ast.classification,
                execution_status="REJECTED_BY_FIREWALL",
                retries=0,
                row_count=None,
                elapsed_ms=elapsed,
                clarification_emitted=False,
                clarification_json=None,
                pii_findings_json=None,
                error_json={"scope_error": scope_error},
            )
            return SqlExecuteResponse(
                query_id=query_id,
                sql=body.sql,
                ast_classification=ast.classification,
                execution_status="REJECTED_BY_FIREWALL",
                preview=None,
                row_count=None,
                elapsed_ms=elapsed,
            )

        async with self._session_factory() as db_session:
            resolver = TableResolver(session=db_session, settings=self._settings)
            attached = await resolver.resolve(body.dataset_id, list(ast.table_refs))
        # For DML: identify which referenced tables are DERIVED.
        # Lives outside the resolver session because the repo owns its
        # own session boundary.
        derived_tables = await _resolve_derived_tables_via_repo(
            self._table_repo, body.dataset_id, ast.table_refs, attached
        )

        result = await self._executor.execute(body.sql, attached, derived_tables or None)
        elapsed = _now_ms() - start_ms

        # Handle DML copy-on-write result: upload new Parquet + bump snapshot.
        if isinstance(result, DmlMutationResult):
            await _apply_dml_mutation_via_repo(
                snapshot_repo=self._snapshot_repo,
                mutation=result,
                dataset_id=body.dataset_id,
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                object_store=self._object_store,
            )
            execution_status = "OK"
            error_json = None
            query_id = await self._query_repo.create_query(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=body.dataset_id,
                question=body.sql,
                semantic_path_taken=None,
                candidates_json=[],
                chosen_candidate_index=None,
                executed_sql=body.sql,
                ast_classification=ast.classification,
                execution_status="OK",
                retries=0,
                row_count=result.rows_affected,
                elapsed_ms=elapsed,
                clarification_emitted=False,
                clarification_json=None,
                pii_findings_json=None,
                error_json=None,
            )
            return SqlExecuteResponse(
                query_id=query_id,
                sql=body.sql,
                ast_classification=ast.classification,
                execution_status="OK",
                preview=None,
                row_count=result.rows_affected,
                truncated=False,
                elapsed_ms=elapsed,
            )

        if isinstance(result, ExecutionResult):
            execution_status = "OK"
            error_json = None
        else:
            execution_status = "FAILED"
            error_json = {"message": result.message}
            if result.sql_state is not None:
                error_json["sql_state"] = result.sql_state

        query_id = await self._query_repo.create_query(
            tenant_id=ctx.tenant_id,
            workspace_id=workspace_id,
            dataset_id=body.dataset_id,
            question=body.sql,
            semantic_path_taken=None,
            candidates_json=[],
            chosen_candidate_index=None,
            executed_sql=body.sql,
            ast_classification=ast.classification,
            execution_status=execution_status,
            retries=0,
            row_count=result.row_count if isinstance(result, ExecutionResult) else None,
            elapsed_ms=elapsed,
            clarification_emitted=False,
            clarification_json=None,
            pii_findings_json=None,
            error_json=error_json,
        )

        if isinstance(result, ExecutionResult) and result.rows:
            uploader = ResultUploader(
                object_store=self._object_store,
                query_repo=self._query_repo,
                settings=self._settings,
            )
            await uploader.upload(
                query_id=query_id,
                result=result,
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=body.dataset_id,
            )

        return SqlExecuteResponse(
            query_id=query_id,
            sql=body.sql,
            ast_classification=ast.classification,
            execution_status=execution_status,  # type: ignore[arg-type]
            preview=result.rows[:10] if isinstance(result, ExecutionResult) else None,
            row_count=result.row_count if isinstance(result, ExecutionResult) else None,
            truncated=result.truncated if isinstance(result, ExecutionResult) else False,
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/sql:execute/stream  (SSE)
    # ------------------------------------------------------------------

    @post_mapping("/sql:execute/stream")
    async def execute_stream(
        self,
        http_request: Request,
        body: Valid[Body[SqlExecuteRequest]],
    ) -> StreamingResponse:
        """Execute SQL and stream progress as Server-Sent Events.

        Event sequence:
        1. ``ast_classified`` — AST result + scope check outcome
        2. ``executed``       — DuckDB result
        3. ``final``          — full SqlExecuteResponse JSON

        :param http_request: Starlette request
        :param body: validated SqlExecuteRequest
        :return: StreamingResponse with ``text/event-stream``
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = _parse_workspace_id(ctx.workspace_id)

        return StreamingResponse(
            self._stream_events(
                ctx=ctx,
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
        ctx: Any,
        workspace_id: uuid.UUID,
        request: SqlExecuteRequest,
    ) -> AsyncIterator[bytes]:
        """Async generator yielding SSE frames for the sql:execute pipeline."""
        start_ms = _now_ms()

        await self._assert_direct_sql_enabled(workspace_id)

        ast = self._ast_classifier.classify(request.sql)
        registered = await self._table_repo.list_kinds_for_dataset_by_names(
            request.dataset_id, list(ast.table_refs)
        )
        table_kinds = {row["name"]: row["kind"] for row in registered}

        scope_error: str | None = None
        try:
            self._scope_guard.check(
                classification=ast,
                scopes=_DEFAULT_SCOPES,
                table_kinds_by_name=table_kinds,
                dataset_allowlist=None,
                dataset_of_table={name: str(request.dataset_id) for name in table_kinds},
            )
        except ScopeGuardError as exc:
            scope_error = str(exc)

        yield _sse_frame(
            "ast_classified",
            {
                "classification": ast.classification,
                "single_statement": ast.single_statement,
                "table_refs": list(ast.table_refs),
                "scope_error": scope_error,
            },
        )

        if scope_error:
            elapsed = _now_ms() - start_ms
            query_id = await self._query_repo.create_query(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=request.dataset_id,
                question=request.sql,
                semantic_path_taken=None,
                candidates_json=[],
                chosen_candidate_index=None,
                executed_sql=request.sql,
                ast_classification=ast.classification,
                execution_status="REJECTED_BY_FIREWALL",
                retries=0,
                row_count=None,
                elapsed_ms=elapsed,
                clarification_emitted=False,
                clarification_json=None,
                pii_findings_json=None,
                error_json={"scope_error": scope_error},
            )
            yield _sse_frame(
                "final",
                SqlExecuteResponse(
                    query_id=query_id,
                    sql=request.sql,
                    ast_classification=ast.classification,
                    execution_status="REJECTED_BY_FIREWALL",
                    preview=None,
                    row_count=None,
                    elapsed_ms=elapsed,
                ).model_dump(mode="json"),
            )
            return

        async with self._session_factory() as db_session:
            resolver = TableResolver(session=db_session, settings=self._settings)
            attached = await resolver.resolve(request.dataset_id, list(ast.table_refs))

        exec_result = await self._executor.execute(request.sql, attached)
        elapsed = _now_ms() - start_ms

        if isinstance(exec_result, ExecutionResult):
            yield _sse_frame(
                "executed",
                {
                    "row_count": exec_result.row_count,
                    "elapsed_ms": elapsed,
                    "truncated": exec_result.truncated,
                },
            )
            execution_status = "OK"
            error_json = None
        else:
            yield _sse_frame("executed", {"error": exec_result.message, "elapsed_ms": elapsed})
            execution_status = "FAILED"
            error_json = {"message": exec_result.message}
            if exec_result.sql_state is not None:
                error_json["sql_state"] = exec_result.sql_state

        query_id = await self._query_repo.create_query(
            tenant_id=ctx.tenant_id,
            workspace_id=workspace_id,
            dataset_id=request.dataset_id,
            question=request.sql,
            semantic_path_taken=None,
            candidates_json=[],
            chosen_candidate_index=None,
            executed_sql=request.sql,
            ast_classification=ast.classification,
            execution_status=execution_status,
            retries=0,
            row_count=exec_result.row_count if isinstance(exec_result, ExecutionResult) else None,
            elapsed_ms=elapsed,
            clarification_emitted=False,
            clarification_json=None,
            pii_findings_json=None,
            error_json=error_json,
        )

        if isinstance(exec_result, ExecutionResult) and exec_result.rows:
            uploader = ResultUploader(
                object_store=self._object_store,
                query_repo=self._query_repo,
                settings=self._settings,
            )
            await uploader.upload(
                query_id=query_id,
                result=exec_result,
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=request.dataset_id,
            )

        yield _sse_frame(
            "final",
            SqlExecuteResponse(
                query_id=query_id,
                sql=request.sql,
                ast_classification=ast.classification,
                execution_status=execution_status,  # type: ignore[arg-type]
                preview=exec_result.rows[:10] if isinstance(exec_result, ExecutionResult) else None,
                row_count=exec_result.row_count if isinstance(exec_result, ExecutionResult) else None,
                truncated=exec_result.truncated if isinstance(exec_result, ExecutionResult) else False,
                elapsed_ms=elapsed,
            ).model_dump(mode="json"),
        )

    async def _assert_direct_sql_enabled(self, workspace_id: uuid.UUID) -> None:
        """Raise DirectSqlForbidden when the workspace flag is off.

        :param workspace_id: workspace to check
        :raises DirectSqlForbidden: when allow_direct_sql is False or workspace missing
        """
        workspace = await self._workspace_service.get(workspace_id)
        if workspace is None or not workspace.get("allow_direct_sql", False):
            raise DirectSqlForbidden(f"workspace {workspace_id!r} does not have allow_direct_sql=true")


# ---------------------------------------------------------------------------
# Module-level helpers for DML copy-on-write
# ---------------------------------------------------------------------------


async def _resolve_derived_tables_via_repo(
    table_repo: TableRepository,
    dataset_id: uuid.UUID,
    table_refs: tuple[str, ...],
    attached: dict[str, str],
) -> dict[str, str]:
    """Return the subset of ``attached`` that corresponds to DERIVED tables.

    Delegates the SELECT to :meth:`TableRepository.list_kinds_for_dataset_by_names`
    so this module owns no SQL.
    """
    if not table_refs:
        return {}
    rows = await table_repo.list_kinds_for_dataset_by_names(dataset_id, list(table_refs))
    derived: dict[str, str] = {}
    for r in rows:
        if r["kind"] == "DERIVED" and r["name"] in attached:
            derived[r["name"]] = attached[r["name"]]
    return derived


async def _apply_dml_mutation_via_repo(
    *,
    snapshot_repo: SchemaSnapshotRepository,
    mutation: DmlMutationResult,
    dataset_id: uuid.UUID,
    tenant_id: str,
    workspace_id: uuid.UUID,
    object_store: Any,
) -> None:
    """Upload the mutated Parquet + bump snapshot via the snapshot repo.

    Copy-on-write finalisation:
    1. Fetch the current snapshot's object key and version number.
    2. Upload the new Parquet under ``v{n+1}.parquet``.
    3. Insert a new ``flyquery_schema_snapshots`` row + flip the table's
       ``current_snapshot_id`` atomically.

    All SQL lives in :class:`SchemaSnapshotRepository`; this module only
    handles the bytes layout + version arithmetic.
    """
    import hashlib

    table_row = await snapshot_repo.get_current_snapshot_for_dataset_table(
        dataset_id=dataset_id,
        table_name=mutation.table_name,
    )
    if table_row is None:
        raise RuntimeError(f"DERIVED table {mutation.table_name!r} not found after DML mutation")

    table_id: uuid.UUID = table_row["table_id"]
    current_key: str | None = table_row["parquet_object_key"]

    next_version = _next_version(current_key)
    base_prefix = _parquet_prefix(current_key, tenant_id, workspace_id, dataset_id, table_id)
    new_key = f"{base_prefix}/v{next_version}.parquet"

    await object_store.put(new_key, mutation.new_parquet_bytes, content_type="application/x-parquet")

    snapshot_hash = hashlib.sha256(mutation.new_parquet_bytes[:256]).hexdigest()[:16]

    await snapshot_repo.create_snapshot_and_promote(
        snapshot_id=uuid.uuid4(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        table_id=table_id,
        snapshot_hash=snapshot_hash,
        n_rows_actual=mutation.rows_affected,
        parquet_object_key=new_key,
        parquet_byte_size=len(mutation.new_parquet_bytes),
    )


def _next_version(current_key: str | None) -> int:
    """Extract the version number from a parquet key and return the next one.

    Expected pattern: ``…/v{N}.parquet``. Returns 2 when the pattern is not
    found (first mutation of a v1.parquet).

    :param current_key: current parquet object key from flyquery_schema_snapshots
    :return: next version integer
    """
    if not current_key:
        return 2
    import re

    match = re.search(r"/v(\d+)\.parquet$", current_key)
    if match:
        return int(match.group(1)) + 1
    return 2


def _parquet_prefix(
    current_key: str | None,
    tenant_id: str,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    table_id: uuid.UUID,
) -> str:
    """Return the directory prefix for the versioned Parquet files.

    Derived from the current key (strips the filename) or reconstructed
    from the standard layout when no current key exists.

    :param current_key: current parquet object key
    :param tenant_id: tenant identifier
    :param workspace_id: workspace UUID
    :param dataset_id: dataset UUID
    :param table_id: table UUID
    :return: prefix string without trailing slash
    """
    if current_key:
        import os

        return os.path.dirname(current_key)
    return f"flyquery/{tenant_id}/{workspace_id}/{dataset_id}/derived/{table_id}"
