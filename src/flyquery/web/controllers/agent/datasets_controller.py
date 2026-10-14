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

"""Agent-tier datasets controller (read-only).

``/api/v1/agent/datasets`` -- agent-token-gated read mirror of the
user-tier datasets surface. Lets an agent discover what datasets exist
before composing a query / ingest payload, without granting it write
authority.

Write paths (create / update / archive) are intentionally **not**
mirrored on the agent surface: dataset lifecycle is operator policy.
If a future agent workflow needs to create datasets, add a separate
controller gated by ``flyquery.datasets:write``.

Path conventions and scopes:
* ``GET /api/v1/agent/datasets``                  -- list. Scope: ``flyquery.datasets:read``.
* ``GET /api/v1/agent/datasets/by-name/{name}``   -- resolve by name. Scope: ``flyquery.datasets:read``.
* ``GET /api/v1/agent/datasets/{id}``             -- fetch single. Scope: ``flyquery.datasets:read``.
"""

from __future__ import annotations

import uuid

from pyfly.container import rest_controller
from pyfly.web import PathVar, QueryParam, get_mapping, request_mapping
from starlette.requests import Request

from flyquery.core.services.auth.agent_token_service import AgentTokenService
from flyquery.interfaces.datasets import DatasetRead
from flyquery.interfaces.pagination import Paginated
from flyquery.web.controllers.datasets_controller import (
    DatasetsController as _UserDatasetsController,
)
from flyquery.web.conventions import (
    HEADER_AGENT_TOKEN,
    FireflyHTTPException,
    tenant_context_from_request,
)

_SCOPE_DATASETS_READ = "flyquery.datasets:read"


class MissingAgentToken(FireflyHTTPException):
    status = 401
    code = "missing_agent_token"
    title = "Missing X-Agent-Token header"


@rest_controller
@request_mapping("/api/v1/agent")
class AgentDatasetsController:
    """Agent-tier read mirror of :class:`DatasetsController`."""

    def __init__(
        self,
        user_datasets_controller: _UserDatasetsController,
        agent_token_service: AgentTokenService,
    ) -> None:
        self._delegate = user_datasets_controller
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
            scope=_SCOPE_DATASETS_READ,
        )

    @get_mapping("/datasets")
    async def list_datasets(
        self,
        http_request: Request,
        q: QueryParam[str] = None,
        name: QueryParam[str] = None,
        status: QueryParam[str] = None,
        workspace_id: QueryParam[uuid.UUID] = None,
        limit: QueryParam[int] = 100,
        offset: QueryParam[int] = 0,
    ) -> Paginated[DatasetRead]:
        """Search / filter datasets visible to this agent's tenant."""
        await self._verify(http_request)
        return await self._delegate.list_datasets(
            http_request,
            q=q,
            name=name,
            status=status,
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )

    @get_mapping("/datasets/by-name/{name}")
    async def read_by_name(
        self,
        http_request: Request,
        name: PathVar[str],
    ) -> DatasetRead:
        """Resolve a dataset by ``(tenant, workspace, name)``."""
        await self._verify(http_request)
        return await self._delegate.read_by_name(http_request, name)

    @get_mapping("/datasets/{dataset_id}")
    async def read(
        self,
        http_request: Request,
        dataset_id: PathVar[uuid.UUID],
    ) -> DatasetRead:
        """Fetch a single dataset by id."""
        await self._verify(http_request)
        return await self._delegate.read(http_request, dataset_id)


__all__ = ["AgentDatasetsController"]
