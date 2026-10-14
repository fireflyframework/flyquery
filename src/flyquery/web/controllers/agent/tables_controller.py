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

"""Agent-tier tables + schema-objects read mirror.

``/api/v1/agent/tables`` + ``/api/v1/agent/schema-objects/{id}`` --
agent-token-gated read mirrors of the user-tier tables and
schema-objects surfaces. Agents that compose queries need to introspect
the schema knowledge base, but write paths (PUT schema_object, derive
table) are operator-curated -- not exposed on the agent surface here.

Path conventions and scopes -- all read endpoints require
``flyquery.schema:read``:

* ``GET /api/v1/agent/datasets/{dataset_id}/tables``
* ``GET /api/v1/agent/tables``
* ``GET /api/v1/agent/tables/by-name/{name}``
* ``GET /api/v1/agent/tables/{table_id}``
* ``GET /api/v1/agent/tables/{table_id}/snapshots``
* ``GET /api/v1/agent/tables/{table_id}/objects``
* ``GET /api/v1/agent/tables/{table_id}/changes``
* ``GET /api/v1/agent/schema-objects/{object_id}``
"""

from __future__ import annotations

import uuid

from pyfly.container import rest_controller
from pyfly.web import PathVar, QueryParam, get_mapping, request_mapping
from starlette.requests import Request

from flyquery.core.services.auth.agent_token_service import AgentTokenService
from flyquery.interfaces.files import SchemaChangeRead, SchemaObjectRead, SnapshotRead, TableRead
from flyquery.interfaces.pagination import Paginated
from flyquery.web.controllers.schema_objects_controller import (
    SchemaObjectsController as _UserSchemaObjectsController,
)
from flyquery.web.controllers.tables_controller import (
    TablesController as _UserTablesController,
)
from flyquery.web.conventions import (
    HEADER_AGENT_TOKEN,
    FireflyHTTPException,
    tenant_context_from_request,
)

_SCOPE_SCHEMA_READ = "flyquery.schema:read"


class MissingAgentToken(FireflyHTTPException):
    status = 401
    code = "missing_agent_token"
    title = "Missing X-Agent-Token header"


@rest_controller
@request_mapping("/api/v1/agent")
class AgentTablesController:
    """Agent-tier read mirror of TablesController + SchemaObjectsController.

    One controller covers both resource families so the agent surface
    keeps the same top-level ``/api/v1/agent/*`` shape without bouncing
    between sibling files.
    """

    def __init__(
        self,
        user_tables_controller: _UserTablesController,
        user_schema_objects_controller: _UserSchemaObjectsController,
        agent_token_service: AgentTokenService,
    ) -> None:
        self._tables = user_tables_controller
        self._schema_objects = user_schema_objects_controller
        self._token_service = agent_token_service

    async def _verify(self, http_request: Request) -> None:
        token = http_request.headers.get(HEADER_AGENT_TOKEN)
        if not token:
            raise MissingAgentToken("X-Agent-Token header is required for /api/v1/agent/* routes.")
        ctx = tenant_context_from_request(http_request)
        await self._token_service.verify(
            token,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            scope=_SCOPE_SCHEMA_READ,
        )

    # ------------------------------------------------------------------
    # Tables under a dataset
    # ------------------------------------------------------------------

    @get_mapping("/datasets/{dataset_id}/tables")
    async def list_tables(
        self,
        http_request: Request,
        dataset_id: PathVar[uuid.UUID],
    ) -> Paginated[TableRead]:
        await self._verify(http_request)
        return await self._tables.list_tables(http_request, dataset_id)

    # ------------------------------------------------------------------
    # Tables search + single fetch
    # ------------------------------------------------------------------

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
        await self._verify(http_request)
        return await self._tables.search_tables(
            http_request,
            q=q,
            name=name,
            dataset_id=dataset_id,
            kind=kind,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    @get_mapping("/tables/by-name/{name}")
    async def get_table_by_name(
        self,
        http_request: Request,
        name: PathVar[str],
        dataset_id: QueryParam[uuid.UUID] = None,
    ) -> TableRead:
        await self._verify(http_request)
        return await self._tables.get_table_by_name(http_request, name, dataset_id=dataset_id)

    @get_mapping("/tables/{table_id}")
    async def get_table(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> TableRead:
        await self._verify(http_request)
        return await self._tables.get_table(http_request, table_id)

    @get_mapping("/tables/{table_id}/snapshots")
    async def list_snapshots(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> Paginated[SnapshotRead]:
        await self._verify(http_request)
        return await self._tables.list_snapshots(http_request, table_id)

    @get_mapping("/tables/{table_id}/objects")
    async def list_objects(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> Paginated[SchemaObjectRead]:
        await self._verify(http_request)
        return await self._tables.list_objects(http_request, table_id)

    @get_mapping("/tables/{table_id}/changes")
    async def list_changes(
        self,
        http_request: Request,
        table_id: PathVar[uuid.UUID],
    ) -> Paginated[SchemaChangeRead]:
        await self._verify(http_request)
        return await self._tables.list_changes(http_request, table_id)

    # ------------------------------------------------------------------
    # Schema object detail
    # ------------------------------------------------------------------

    @get_mapping("/schema-objects/{object_id}")
    async def get_schema_object(
        self,
        http_request: Request,
        object_id: PathVar[uuid.UUID],
    ) -> SchemaObjectRead:
        await self._verify(http_request)
        return await self._schema_objects.get_object(http_request, object_id)


__all__ = ["AgentTablesController"]
