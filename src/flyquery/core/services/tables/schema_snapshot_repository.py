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

"""Async SQLAlchemy repository for flyquery_schema_snapshots.

Snapshots are immutable; the only operation the public REST surface
needs is the read side:

* :meth:`list_for_table`   -- chronological list of every snapshot.
* :meth:`list_objects_for_current_snapshot` -- columns + table row
  of the table's *current* snapshot.
* :meth:`list_changes_for_table` -- rename / add / drop history.

Writes (insert + flip current_snapshot_id) stay inside the reconcile
ingestion stage -- they're tightly coupled to the per-table sample +
column-naming logic that lives there.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pyfly.container import repository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@repository
class SchemaSnapshotRepository:
    """Repository over ``flyquery_schema_snapshots`` + companion reads."""

    def __init__(self, session: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session

    async def list_for_table(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    "SELECT ss.* FROM flyquery_schema_snapshots ss "
                    "JOIN flyquery_tables t ON t.id = ss.table_id "
                    "WHERE t.id = :tid AND t.tenant_id = :tenant AND t.workspace_id = :workspace "
                    "AND ss.tenant_id = :tenant AND ss.workspace_id = :workspace "
                    "ORDER BY ss.taken_at"
                ),
                {"tid": table_id, "tenant": tenant_id, "workspace": workspace_id},
            )
            return [dict(r) for r in result.mappings().all()]

    async def list_objects_for_current_snapshot(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """List schema_objects bound to the table's *current* snapshot.

        Returns column rows + the table-level row (kind='TABLE' /
        kind='COLUMN'), sorted with the table row first.
        """
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT so.*
                    FROM flyquery_schema_objects so
                    JOIN flyquery_tables t ON t.current_snapshot_id = so.snapshot_id AND t.id = so.table_id
                    WHERE t.id = :tid AND t.tenant_id = :tenant
                      AND t.workspace_id = :workspace
                      AND so.tenant_id = :tenant AND so.workspace_id = :workspace
                    ORDER BY so.kind DESC, so.qualified_name
                    """
                ),
                {"tid": table_id, "tenant": tenant_id, "workspace": workspace_id},
            )
            return [dict(r) for r in result.mappings().all()]

    async def list_changes_for_table(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    "SELECT sc.* FROM flyquery_schema_changes sc "
                    "JOIN flyquery_tables t ON t.id = sc.table_id "
                    "WHERE t.id = :tid AND t.tenant_id = :tenant AND t.workspace_id = :workspace "
                    "AND sc.tenant_id = :tenant AND sc.workspace_id = :workspace "
                    "ORDER BY sc.created_at"
                ),
                {"tid": table_id, "tenant": tenant_id, "workspace": workspace_id},
            )
            return [dict(r) for r in result.mappings().all()]

    async def get_current_snapshot_for_dataset_table(
        self,
        *,
        dataset_id: uuid.UUID,
        table_name: str,
    ) -> dict[str, Any] | None:
        """Look up the current snapshot key for a (dataset, table_name).

        Returns ``{table_id, current_snapshot_id, parquet_object_key}``
        or ``None`` if no active row matches. Used by the SQL execute
        DML mutation path to find the bytes it must copy-on-write.
        """
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT t.id AS table_id,
                           t.current_snapshot_id,
                           ss.parquet_object_key
                    FROM flyquery_tables t
                    LEFT JOIN flyquery_schema_snapshots ss
                        ON ss.id = t.current_snapshot_id
                    WHERE t.dataset_id = :ds
                      AND t.name = :name
                      AND t.is_active = true
                    """
                ),
                {"ds": dataset_id, "name": table_name},
            )
            row = result.mappings().one_or_none()
            return dict(row) if row else None

    async def create_snapshot_and_promote(
        self,
        *,
        snapshot_id: uuid.UUID,
        tenant_id: str,
        workspace_id: uuid.UUID,
        dataset_id: uuid.UUID,
        table_id: uuid.UUID,
        snapshot_hash: str,
        n_rows_actual: int,
        parquet_object_key: str,
        parquet_byte_size: int,
        triggered_by: str = "USER",
        created_by: str = "agent",
    ) -> None:
        """Insert a new snapshot row and flip the table's current_snapshot_id.

        Atomic: both writes happen inside the same transaction so a
        crash between INSERT and UPDATE never leaves the table pointing
        at a non-existent snapshot. Used by the DML copy-on-write path
        on ``POST /sql:execute`` for DERIVED tables.
        """
        async with self._factory() as s, s.begin():
            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_snapshots
                        (id, tenant_id, workspace_id, dataset_id, table_id,
                         snapshot_hash, n_columns, n_rows_actual,
                         parquet_object_key, parquet_byte_size,
                         status, triggered_by, created_by)
                    VALUES
                        (:id, :tenant_id, :workspace_id, :dataset_id, :table_id,
                         :hash, 0, :n_rows,
                         :object_key, :byte_size,
                         'READY', :triggered_by, :created_by)
                    """
                ),
                {
                    "id": snapshot_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "dataset_id": dataset_id,
                    "table_id": table_id,
                    "hash": snapshot_hash,
                    "n_rows": n_rows_actual,
                    "object_key": parquet_object_key,
                    "byte_size": parquet_byte_size,
                    "triggered_by": triggered_by,
                    "created_by": created_by,
                },
            )
            await s.execute(
                sa.text(
                    "UPDATE flyquery_tables "
                    "SET current_snapshot_id = :sid, updated_at = now() "
                    "WHERE id = :tid"
                ),
                {"sid": snapshot_id, "tid": table_id},
            )
