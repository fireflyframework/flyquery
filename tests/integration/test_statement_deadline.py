# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0

"""Actual registered Parquet timeout persists through PostgreSQL query history.

The owned schema uses the test admin role for setup/persistence. Authorization
and PostgreSQL RLS are separate acceptance scopes, not claims of this probe.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from flyquery.core.services.query.query_repository import QueryRepository
from flyquery.core.services.tables.table_repository import TableRepository
from flyquery.interfaces.sql_execute import SqlExecuteRequest
from flyquery.models.entities import Base, Dataset, SchemaSnapshot, Table, Workspace
from flyquery.web.controllers.sql_execute_controller import SqlExecuteController
from flyquery.web.conventions import TenantContext


@pytest.mark.integration
@pytest.mark.parametrize("stream", [False, True])
async def test_native_deadline_records_failed_query_in_postgres(tmp_path, stream):
    path = tmp_path / "orders.parquet"
    pq.write_table(pa.table({"id": list(range(1000))}), path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    schema = "deadline_" + uuid.uuid4().hex
    url = os.environ["FLYQUERY_DATABASE_URL_ADMIN"].replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema + ",public"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant = "deadline-" + uuid.uuid4().hex
    workspace, dataset, table, snapshot = [uuid.uuid4() for _ in range(4)]
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            # Force creation in this owned schema: checkfirst would see public
            # tables through search_path and silently reuse another fixture.
            await connection.run_sync(Base.metadata.create_all, checkfirst=False)
            assert (await connection.execute(text("SELECT current_schema()"))).scalar_one() == schema
        async with sessions() as session, session.begin():
            session.add(Workspace(id=workspace, tenant_id=tenant, slug="deadline", name="Deadline"))
            await session.flush()
            session.add(Dataset(id=dataset, tenant_id=tenant, workspace_id=workspace, name="Synthetic"))
            await session.flush()
            session.add(
                Table(
                    id=table,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    dataset_id=dataset,
                    name="orders",
                    qualified_name="orders",
                    current_snapshot_id=snapshot,
                )
            )
            await session.flush()
            session.add(
                SchemaSnapshot(
                    id=snapshot,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    dataset_id=dataset,
                    table_id=table,
                    snapshot_hash=before,
                    n_columns=1,
                    n_rows_actual=1000,
                    parquet_object_key="orders.parquet",
                    status="READY",
                    triggered_by="USER",
                    created_by="deadline-fixture",
                )
            )

        class WorkspaceFlag:
            async def get(self, selected):
                assert selected == workspace
                return {"allow_direct_sql": True}

        class NoResultUpload:
            async def put(self, *args, **kwargs):
                pytest.fail("A timed-out query must not upload a result")

        settings = SimpleNamespace(
            duckdb_memory_limit="256MB",
            default_row_cap=10,
            default_statement_timeout_ms=100,
            object_store_base=str(tmp_path),
            result_preview_max_bytes=4096,
            result_ttl_hours=1,
        )
        api = SqlExecuteController(
            settings,
            sessions,
            NoResultUpload(),
            QueryRepository(sessions),
            WorkspaceFlag(),
            TableRepository(sessions),
            None,
        )
        body = SqlExecuteRequest(
            dataset_id=dataset,
            sql=(
                "SELECT SUM((a.id * b.id * c.id) % 997) AS n "
                "FROM orders a CROSS JOIN orders b CROSS JOIN orders c"
            ),
        )
        if stream:
            ctx = TenantContext(tenant_id=tenant, workspace_id=str(workspace), correlation_id="deadline")
            frames = [
                frame async for frame in api._stream_events(ctx=ctx, workspace_id=workspace, request=body)
            ]
            final = json.loads(frames[-1].decode().split("data: ", 1)[1])
            query_id = uuid.UUID(final["query_id"])
            assert final["execution_status"] == "FAILED" and final["preview"] is None
        else:
            request = Request(
                {
                    "type": "http",
                    "headers": [
                        (b"x-tenant-id", tenant.encode()),
                        (b"x-workspace-id", str(workspace).encode()),
                    ],
                }
            )
            result = await api.execute(request, body)
            query_id = result.query_id
            assert result.execution_status == "FAILED" and result.preview is None
        async with sessions() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT execution_status,error_json,retries FROM flyquery_queries WHERE id=:id"),
                        {"id": query_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["execution_status"] == "FAILED" and row["retries"] == 0
            assert row["error_json"]["sql_state"] == "57014"
            assert (
                await session.execute(
                    text("SELECT COUNT(*) FROM flyquery_query_results WHERE query_id=:id"), {"id": query_id}
                )
            ).scalar_one() == 0
            current = (
                await session.execute(
                    text("SELECT current_snapshot_id FROM flyquery_tables WHERE id=:id"), {"id": table}
                )
            ).scalar_one()
            assert current == snapshot
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
