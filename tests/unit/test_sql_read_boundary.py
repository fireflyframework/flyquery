# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0

"""Direct-handler contract fixtures with native DuckDB and owned Parquet.

Repository doubles represent registered metadata; these cases do not qualify PostgreSQL RLS.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from starlette.requests import Request

from flyquery.interfaces.sql_execute import SqlExecuteRequest
from flyquery.web.controllers.sql_execute_controller import SqlExecuteController
from flyquery.web.conventions import TenantContext


def controller(tmp_path):
    dataset = uuid.uuid4()
    workspace = uuid.uuid4()
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 25}]), tmp_path / "orders.parquet")

    class Rows:
        def mappings(self):
            return [{"name": "orders", "parquet_object_key": "orders.parquet"}]

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement, params):
            assert params == {"ds": dataset, "names": ["orders"], "pins": "{}"}
            return Rows()

    class TableRepository:
        async def list_kinds_for_dataset_by_names(self, selected, names):
            if selected != dataset:
                return []
            return [{"name": "orders", "kind": "UPLOADED"}] if "orders" in names else []

    class QueryRepository:
        async def create_query(self, **kwargs):
            return uuid.uuid4()

        async def upsert_result(self, **kwargs):
            pass

    class Store:
        async def put(self, key, value, **kwargs):
            assert key.startswith("flyquery/fixture/")

    class WorkspaceService:
        async def get(self, selected):
            return {"allow_direct_sql": selected == workspace}

    settings = SimpleNamespace(
        duckdb_memory_limit="256MB",
        default_row_cap=100,
        default_statement_timeout_ms=5000,
        object_store_base=str(tmp_path),
        result_preview_max_bytes=4096,
        result_ttl_hours=1,
    )
    api = SqlExecuteController(
        settings, Session, Store(), QueryRepository(), WorkspaceService(), TableRepository(), None
    )
    ctx = TenantContext(tenant_id="fixture", workspace_id=str(workspace), correlation_id="fixture")
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-tenant-id", b"fixture"), (b"x-workspace-id", str(workspace).encode())],
        }
    )
    return api, request, dataset, workspace, ctx


@pytest.mark.parametrize(
    "sql", ["SELECT total FROM orders", "WITH x AS (SELECT total FROM orders) SELECT total FROM x"]
)
@pytest.mark.asyncio
async def test_registered_direct_sql_preserves_native_results(tmp_path, sql):
    api, request, dataset, _, _ = controller(tmp_path)
    result = await api.execute(request, SqlExecuteRequest(dataset_id=dataset, sql=sql))
    assert result.execution_status == "OK"
    assert result.preview == [{"total": 25}]


@pytest.mark.asyncio
async def test_stream_uses_registered_metadata_before_returning_native_rows(tmp_path):
    api, _, dataset, workspace, ctx = controller(tmp_path)
    frames = [
        frame
        async for frame in api._stream_events(
            ctx=ctx,
            workspace_id=workspace,
            request=SqlExecuteRequest(dataset_id=dataset, sql="SELECT total FROM orders"),
        )
    ]
    final = json.loads(frames[-1].decode().split("data: ", 1)[1])
    assert final["execution_status"] == "OK"
    assert final["preview"] == [{"total": 25}]


@pytest.mark.asyncio
async def test_unregistered_dataset_cannot_get_a_fabricated_table_registration(tmp_path):
    api, request, _, _, _ = controller(tmp_path)
    result = await api.execute(
        request, SqlExecuteRequest(dataset_id=uuid.uuid4(), sql="SELECT total FROM orders")
    )
    assert result.execution_status == "REJECTED_BY_FIREWALL"
    assert result.preview is None


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_native_statement_deadline_persists_failed_audit_without_result(tmp_path, stream):
    from flyquery.core.services.execution.duckdb_executor import DuckDBExecutor

    api, request, dataset, workspace, ctx = controller(tmp_path)
    pq.write_table(pa.table({"id": list(range(1000))}), tmp_path / "orders.parquet")
    api._settings.default_statement_timeout_ms = 100
    api._executor = DuckDBExecutor(api._settings)
    audit = []
    original = api._query_repo.create_query

    async def record(**kwargs):
        audit.append(kwargs)
        return await original(**kwargs)

    api._query_repo.create_query = record
    body = SqlExecuteRequest(
        dataset_id=dataset,
        sql=(
            "SELECT SUM((a.id * b.id * c.id) % 997) AS n "
            "FROM orders a CROSS JOIN orders b CROSS JOIN orders c"
        ),
    )
    if stream:
        frames = [frame async for frame in api._stream_events(ctx=ctx, workspace_id=workspace, request=body)]
        final = json.loads(frames[-1].decode().split("data: ", 1)[1])
        assert final["execution_status"] == "FAILED" and final["preview"] is None
    else:
        result = await api.execute(request, body)
        assert result.execution_status == "FAILED" and result.preview is None
    assert len(audit) == 1
    assert audit[0]["execution_status"] == "FAILED"
    assert audit[0]["error_json"]["sql_state"] == "57014"
