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

"""Async SQLAlchemy repository for flyquery_tables.

Read-side companion to the ingestion stages (which write tables +
snapshots through their own SQL). Surfaces the queries the
``TablesController`` historically inlined:

* :meth:`list_for_dataset` -- bound to one dataset, default
  ``is_active=true``, JOIN-enriched with snapshot column count.
* :meth:`search`            -- workspace-scoped search with q / name /
  kind / dataset / is_active filters and ``(rows, total)`` semantics.
* :meth:`get`               -- single fetch by id, tenant/workspace-scoped.
* :meth:`get_by_name`       -- resolve by ``(workspace, name [, dataset])``.

All reads carry the snapshot ``n_columns`` so the controller can
populate ``TableRead.n_columns`` in one round-trip.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pyfly.container import repository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _read_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    # The retained pointer alone does not prove that the snapshot is in this scope.
    data["current_snapshot_id"] = data.pop("_scoped_snapshot_id")
    return data


@repository
class TableRepository:
    """Repository over ``flyquery_tables`` + the snapshot join."""

    def __init__(self, session: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session

    async def list_for_dataset(
        self,
        dataset_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT t.*,
                           ss.n_columns, ss.id AS _scoped_snapshot_id
                    FROM flyquery_tables t
                    LEFT JOIN flyquery_schema_snapshots ss
                        ON ss.id = t.current_snapshot_id
                       AND ss.table_id = t.id
                       AND ss.tenant_id = t.tenant_id
                       AND ss.workspace_id = t.workspace_id
                       AND ss.dataset_id = t.dataset_id
                    WHERE t.dataset_id = :ds_id
                      AND t.tenant_id = :tenant
                      AND t.workspace_id = :workspace
                      AND t.is_active = true
                    ORDER BY t.created_at
                    """
                ),
                {"ds_id": dataset_id, "tenant": tenant_id, "workspace": workspace_id},
            )
            return [_read_row(r) for r in result.mappings().all()]

    async def search(
        self,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        q: str | None = None,
        name: str | None = None,
        dataset_id: uuid.UUID | None = None,
        kind: str | None = None,
        is_active: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search/filter + paginate tables. Returns ``(rows, total_unpaginated)``."""
        like = f"%{q}%" if q else None
        clamped_limit = max(1, min(1000, int(limit)))
        clamped_offset = max(0, int(offset))
        params: dict[str, Any] = {
            "tenant": tenant_id,
            "workspace": workspace_id,
            "q": like,
            "name": name,
            "ds_id": dataset_id,
            "kind": kind,
            "active": is_active,
            "limit": clamped_limit,
            "offset": clamped_offset,
        }
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT t.*,
                           ss.n_columns, ss.id AS _scoped_snapshot_id,
                           COUNT(*) OVER () AS _total
                    FROM flyquery_tables t
                    LEFT JOIN flyquery_schema_snapshots ss
                        ON ss.id = t.current_snapshot_id
                       AND ss.table_id = t.id
                       AND ss.tenant_id = t.tenant_id
                       AND ss.workspace_id = t.workspace_id
                       AND ss.dataset_id = t.dataset_id
                    WHERE t.tenant_id = :tenant
                      AND t.workspace_id = :workspace
                      AND t.is_active = :active
                      AND (CAST(:ds_id AS uuid) IS NULL OR t.dataset_id = CAST(:ds_id AS uuid))
                      AND (CAST(:kind AS text) IS NULL OR t.kind = CAST(:kind AS text))
                      AND (CAST(:name AS text) IS NULL OR t.name = CAST(:name AS text))
                      AND (CAST(:q AS text) IS NULL
                           OR t.name ILIKE CAST(:q AS text)
                           OR t.qualified_name ILIKE CAST(:q AS text))
                    ORDER BY t.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
            rows = [_read_row(r) for r in result.mappings().all()]
        if rows:
            total = int(rows[0].pop("_total"))
            for r in rows[1:]:
                r.pop("_total", None)
            return rows, total
        return [], await self._count(params)

    async def _count(self, params: dict[str, Any]) -> int:
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT COUNT(*) AS n
                    FROM flyquery_tables t
                    WHERE t.tenant_id = :tenant
                      AND t.workspace_id = :workspace
                      AND t.is_active = :active
                      AND (CAST(:ds_id AS uuid) IS NULL OR t.dataset_id = CAST(:ds_id AS uuid))
                      AND (CAST(:kind AS text) IS NULL OR t.kind = CAST(:kind AS text))
                      AND (CAST(:name AS text) IS NULL OR t.name = CAST(:name AS text))
                      AND (CAST(:q AS text) IS NULL
                           OR t.name ILIKE CAST(:q AS text)
                           OR t.qualified_name ILIKE CAST(:q AS text))
                    """
                ),
                params,
            )
            return int(result.scalar_one())

    async def get(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT t.*,
                           ss.n_columns, ss.id AS _scoped_snapshot_id
                    FROM flyquery_tables t
                    LEFT JOIN flyquery_schema_snapshots ss
                        ON ss.id = t.current_snapshot_id
                       AND ss.table_id = t.id
                       AND ss.tenant_id = t.tenant_id
                       AND ss.workspace_id = t.workspace_id
                       AND ss.dataset_id = t.dataset_id
                    WHERE t.id = :tid AND t.tenant_id = :tenant
                      AND t.workspace_id = :workspace
                    """
                ),
                {"tid": table_id, "tenant": tenant_id, "workspace": workspace_id},
            )
            row = result.mappings().one_or_none()
            return _read_row(row) if row else None

    async def list_kinds_for_dataset_by_names(
        self,
        dataset_id: uuid.UUID,
        names: list[str],
    ) -> list[dict[str, Any]]:
        """Return ``[{name, kind}]`` for every active table in ``dataset_id``
        whose name appears in ``names``.

        Used by the SQL execute path to decide which referenced tables
        are DERIVED (and therefore writable via DML). Does not filter
        by tenant_id because the caller has already authenticated +
        scope-gated the request -- the dataset_id binds tenancy
        transitively through the ``flyquery_datasets`` row.
        """
        if not names:
            return []
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT name, kind FROM flyquery_tables
                    WHERE dataset_id = :ds
                      AND name = ANY(:names)
                      AND is_active = true
                    """
                ),
                {"ds": dataset_id, "names": list(names)},
            )
            return [dict(r) for r in result.mappings().all()]

    async def find_by_name(
        self,
        name: str,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        dataset_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return rows matching ``(tenant, workspace, name [, dataset])``.

        Returns at most two rows -- the controller uses cardinality to
        distinguish 0 (404), 1 (success), and 2+ (ambiguous -> ask the
        caller to disambiguate via dataset_id).
        """
        async with self._factory() as s:
            result = await s.execute(
                sa.text(
                    """
                    SELECT t.*, ss.n_columns, ss.id AS _scoped_snapshot_id
                    FROM flyquery_tables t
                    LEFT JOIN flyquery_schema_snapshots ss
                        ON ss.id = t.current_snapshot_id
                       AND ss.table_id = t.id
                       AND ss.tenant_id = t.tenant_id
                       AND ss.workspace_id = t.workspace_id
                       AND ss.dataset_id = t.dataset_id
                    WHERE t.tenant_id = :tenant
                      AND t.workspace_id = :workspace
                      AND t.name = :name
                      AND t.is_active = true
                      AND (CAST(:ds_id AS uuid) IS NULL OR t.dataset_id = CAST(:ds_id AS uuid))
                    LIMIT 2
                    """
                ),
                {
                    "tenant": tenant_id,
                    "workspace": workspace_id,
                    "name": name,
                    "ds_id": dataset_id,
                },
            )
            return [_read_row(r) for r in result.mappings().all()]
