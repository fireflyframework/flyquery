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

"""Tables controller.

GET  /api/v1/tables                         -- list + search/filter
GET  /api/v1/tables/by-name/{name}          -- resolve by dataset + name
GET  /api/v1/datasets/{dataset_id}/tables   -- list tables for a dataset
GET  /api/v1/tables/{table_id}              -- get single table
GET  /api/v1/tables/{table_id}/snapshots    -- list snapshots
GET  /api/v1/tables/{table_id}/objects      -- list schema_objects (cols+table)
GET  /api/v1/tables/{table_id}/changes      -- list schema changes

The controller is a thin HTTP adapter -- every read goes through
:class:`TableService`, which composes
:class:`TableRepository` + :class:`SchemaSnapshotRepository`. The
``/tables`` list takes ``q`` (free-text on name + qualified_name),
``name`` (exact), ``dataset_id``, ``kind`` (UPLOADED/VIEW/DERIVED),
``is_active``, ``limit``, ``offset``. Response is
:class:`Paginated[TableRead]`.
"""

from __future__ import annotations

import uuid

from pyfly.container import rest_controller
from pyfly.web import PathVar, QueryParam, get_mapping, request_mapping
from starlette.requests import Request

from flyquery.core.services.tables.table_service import TableNameAmbiguous, TableService
from flyquery.interfaces.files import (
    SchemaChangeRead,
    SchemaObjectRead,
    SnapshotRead,
    TableRead,
)
from flyquery.interfaces.pagination import Paginated
from flyquery.web.conventions import ResourceNotFound, tenant_context_from_request


@rest_controller
@request_mapping("/api/v1")
class TablesController:
    """REST adapter for schema knowledge-base tables."""

    def __init__(self, service: TableService) -> None:
        self._service = service

    # ------------------------------------------------------------------ #
    # List tables for a dataset                                           #
    # ------------------------------------------------------------------ #

    @get_mapping("/datasets/{dataset_id}/tables")
    async def list_tables(
        self,
        http_request: Request,
        dataset_id: PathVar[uuid.UUID],
    ) -> Paginated[TableRead]:
        ctx = tenant_context_from_request(http_request)
        rows = await self._service.list_for_dataset(
            dataset_id, tenant_id=ctx.tenant_id, workspace_id=uuid.UUID(ctx.workspace_id)
        )
        items = [_table_row_to_read(r) for r in rows]
        return Paginated.of(items, total=len(items))

    # ------------------------------------------------------------------ #
    # Search/filter tables across one or all datasets                     #
    # ------------------------------------------------------------------ #

    @get_mapping("/tables")
    async def search_tables(
        self,
        http_request: Request,
        q: QueryParam[str] = None,
        name: QueryParam[str] = None,
        dataset_id: QueryParam[uuid.UUID] = None,
        kind: QueryParam[str] = None,
        is_active: QueryParam[bool] = None,
        limit: QueryParam[int] = 100,
        offset: QueryParam[int] = 0,
    ) -> Paginated[TableRead]:
        """Search/filter tables across the caller's workspace.

        Query parameters
        ----------------
        * ``q``          -- substring match on ``name`` or ``qualified_name``
                            (case-insensitive ``ILIKE``).
        * ``name``       -- exact match on ``name``.
        * ``dataset_id`` -- restrict to a single dataset.
        * ``kind``       -- ``UPLOADED`` / ``VIEW`` / ``DERIVED``.
        * ``is_active``  -- default ``true``; pass ``false`` to include
                            archived tables.
        * ``limit``      -- page size, clamped to [1, 1000]. Default 100.
        * ``offset``     -- starting offset. Default 0.

        Response envelope: ``Paginated[TableRead]``.
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = uuid.UUID(ctx.workspace_id) if isinstance(ctx.workspace_id, str) else ctx.workspace_id
        rows, total = await self._service.search(
            tenant_id=ctx.tenant_id,
            workspace_id=workspace_id,
            q=q,
            name=name,
            dataset_id=dataset_id,
            kind=kind,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        items = [_table_row_to_read(r) for r in rows]
        # Use service-clamped values for the envelope so the
        # consumer sees the actual paging applied.
        clamped_limit = max(1, min(1000, int(limit)))
        clamped_offset = max(0, int(offset))
        return Paginated.of(
            items,
            total=total,
            limit=clamped_limit,
            offset=clamped_offset,
        )

    # ------------------------------------------------------------------ #
    # Resolve a table by (dataset_id, name)                               #
    # ------------------------------------------------------------------ #

    @get_mapping("/tables/by-name/{name}")
    async def get_table_by_name(
        self,
        http_request: Request,
        name: PathVar[str],
        dataset_id: QueryParam[uuid.UUID] = None,
    ) -> TableRead:
        """Resolve a table by ``name`` within the caller's workspace.

        Pass ``?dataset_id=...`` to scope the lookup to a single dataset.
        Returns 404 if the name is ambiguous (matches multiple datasets)
        or no match is found.
        """
        ctx = tenant_context_from_request(http_request)
        workspace_id = uuid.UUID(ctx.workspace_id) if isinstance(ctx.workspace_id, str) else ctx.workspace_id
        try:
            row = await self._service.find_by_name(
                name,
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                dataset_id=dataset_id,
            )
        except TableNameAmbiguous as exc:
            raise ResourceNotFound(str(exc)) from exc
        if row is None:
            raise ResourceNotFound(f"table with name {name!r} not found")
        return _table_row_to_read(row)

    # ------------------------------------------------------------------ #
    # Get single table                                                    #
    # ------------------------------------------------------------------ #

    @get_mapping("/tables/{table_id}")
    async def get_table(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> TableRead:
        ctx = tenant_context_from_request(http_request)
        row = await self._service.get(
            table_id, tenant_id=ctx.tenant_id, workspace_id=uuid.UUID(ctx.workspace_id)
        )
        if row is None:
            raise ResourceNotFound(f"table {table_id!r} not found")
        return _table_row_to_read(row)

    # ------------------------------------------------------------------ #
    # List snapshots                                                      #
    # ------------------------------------------------------------------ #

    @get_mapping("/tables/{table_id}/snapshots")
    async def list_snapshots(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> Paginated[SnapshotRead]:
        ctx = tenant_context_from_request(http_request)
        rows = await self._service.list_snapshots(
            table_id, tenant_id=ctx.tenant_id, workspace_id=uuid.UUID(ctx.workspace_id)
        )
        items = [_snapshot_row_to_read(r) for r in rows]
        return Paginated.of(items, total=len(items))

    # ------------------------------------------------------------------ #
    # List schema objects for current snapshot                            #
    # ------------------------------------------------------------------ #

    @get_mapping("/tables/{table_id}/objects")
    async def list_objects(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> Paginated[SchemaObjectRead]:
        """List schema_objects for the table's current snapshot."""
        ctx = tenant_context_from_request(http_request)
        rows = await self._service.list_objects(
            table_id, tenant_id=ctx.tenant_id, workspace_id=uuid.UUID(ctx.workspace_id)
        )
        items = [_object_row_to_read(r) for r in rows]
        return Paginated.of(items, total=len(items))

    # ------------------------------------------------------------------ #
    # List schema changes                                                 #
    # ------------------------------------------------------------------ #

    @get_mapping("/tables/{table_id}/changes")
    async def list_changes(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> Paginated[SchemaChangeRead]:
        ctx = tenant_context_from_request(http_request)
        rows = await self._service.list_changes(
            table_id, tenant_id=ctx.tenant_id, workspace_id=uuid.UUID(ctx.workspace_id)
        )
        items = [_change_row_to_read(r) for r in rows]
        return Paginated.of(items, total=len(items))


# ------------------------------------------------------------------ #
# Row -> DTO helpers                                                   #
# ------------------------------------------------------------------ #


def _table_row_to_read(row: dict) -> TableRead:
    return TableRead(
        id=row["id"],
        tenant_id=row["tenant_id"],
        workspace_id=row["workspace_id"],
        dataset_id=row["dataset_id"],
        source_file_id=row.get("source_file_id"),
        name=row["name"],
        qualified_name=row["qualified_name"],
        kind=row.get("kind", "UPLOADED"),
        sheet_or_json_path=row.get("sheet_or_json_path"),
        current_snapshot_id=row.get("current_snapshot_id"),
        description=row.get("description"),
        description_source=row.get("description_source"),
        business_owner=row.get("business_owner"),
        is_active=row.get("is_active", True),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        n_columns=row.get("n_columns"),
    )


def _snapshot_row_to_read(row: dict) -> SnapshotRead:
    return SnapshotRead(
        id=row["id"],
        table_id=row["table_id"],
        taken_at=row["taken_at"],
        n_columns=row["n_columns"],
        n_rows_actual=row.get("n_rows_actual"),
        n_rows_estimate=row.get("n_rows_estimate"),
        parquet_byte_size=row.get("parquet_byte_size"),
        status=row["status"],
        triggered_by=row["triggered_by"],
    )


def _object_row_to_read(row: dict) -> SchemaObjectRead:
    return SchemaObjectRead(
        id=row["id"],
        tenant_id=row["tenant_id"],
        workspace_id=row["workspace_id"],
        table_id=row["table_id"],
        snapshot_id=row["snapshot_id"],
        kind=row["kind"],
        qualified_name=row["qualified_name"],
        data_type=row.get("data_type"),
        is_nullable=row.get("is_nullable"),
        description=row.get("description"),
        description_source=row.get("description_source"),
        synonyms_json=row.get("synonyms_json"),
        pii_tag=row.get("pii_tag"),
        pii_source=row.get("pii_source"),
        business_owner=row.get("business_owner"),
        governance_json=row.get("governance_json"),
        is_active=row.get("is_active", True),
        created_at=row["created_at"],
        last_changed_at=row["last_changed_at"],
    )


def _change_row_to_read(row: dict) -> SchemaChangeRead:
    return SchemaChangeRead(
        id=row["id"],
        table_id=row["table_id"],
        prev_snapshot_id=row.get("prev_snapshot_id"),
        next_snapshot_id=row["next_snapshot_id"],
        column_name=row["column_name"],
        change=row["change"],
        before_json=row.get("before_json"),
        after_json=row.get("after_json"),
        llm_rationale=row.get("llm_rationale"),
        approved_by=row.get("approved_by"),
        approved_at=row.get("approved_at"),
        created_at=row["created_at"],
    )
