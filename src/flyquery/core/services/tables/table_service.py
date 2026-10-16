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

"""Table service: read-side aggregate over flyquery_tables + snapshot joins.

Wraps :class:`TableRepository` + :class:`SchemaSnapshotRepository`
behind a single bean so the controller depends on one bean. The
service also enforces the workspace_id-as-UUID parse rule that used
to live inline in the controller.
"""

from __future__ import annotations

import uuid
from typing import Any

from pyfly.container import service as service_bean

from flyquery.core.services.tables.schema_snapshot_repository import (
    SchemaSnapshotRepository,
)
from flyquery.core.services.tables.table_repository import TableRepository


class TableNameAmbiguous(Exception):
    """Raised by :meth:`TableService.find_by_name` when the same name
    matches two tables across different datasets in the workspace.

    The controller maps this to a typed 404 with disambiguation hint.
    """


@service_bean
class TableService:
    """Domain operations for ``flyquery_tables`` (read-only)."""

    def __init__(
        self,
        tables: TableRepository,
        snapshots: SchemaSnapshotRepository,
    ) -> None:
        self._tables = tables
        self._snapshots = snapshots

    # -- Table reads ----------------------------------------------------

    async def list_for_dataset(
        self,
        dataset_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        return await self._tables.list_for_dataset(dataset_id, tenant_id=tenant_id, workspace_id=workspace_id)

    async def search(
        self,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        q: str | None = None,
        name: str | None = None,
        dataset_id: uuid.UUID | None = None,
        kind: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        effective_active = True if is_active is None else bool(is_active)
        return await self._tables.search(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            q=q,
            name=name,
            dataset_id=dataset_id,
            kind=kind,
            is_active=effective_active,
            limit=limit,
            offset=offset,
        )

    async def get(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        return await self._tables.get(table_id, tenant_id=tenant_id, workspace_id=workspace_id)

    async def find_by_name(
        self,
        name: str,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        dataset_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a table by name. Returns the row or ``None`` if missing.

        Raises :class:`TableNameAmbiguous` when the same name resolves
        across two datasets in the workspace -- the caller must pass
        ``dataset_id`` to disambiguate.
        """
        rows = await self._tables.find_by_name(
            name,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise TableNameAmbiguous(
                f"table name {name!r} matches multiple datasets; pass ?dataset_id= to disambiguate"
            )
        return rows[0]

    # -- Snapshot / objects / changes ----------------------------------

    async def list_snapshots(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        return await self._snapshots.list_for_table(table_id, tenant_id=tenant_id, workspace_id=workspace_id)

    async def list_objects(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        return await self._snapshots.list_objects_for_current_snapshot(
            table_id, tenant_id=tenant_id, workspace_id=workspace_id
        )

    async def list_changes(
        self,
        table_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        return await self._snapshots.list_changes_for_table(
            table_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
