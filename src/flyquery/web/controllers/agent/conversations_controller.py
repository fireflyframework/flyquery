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

"""Agent-tier conversations controller.

``/api/v1/agent/conversations`` — agent-token-gated mirror of the
user-tier conversations surface. Without this surface, agents that
call ``/api/v1/agent/query`` cannot drill down: the user-tier
``/api/v1/conversations`` endpoints reject agent-token requests upstream.

Path conventions and scopes:
* ``POST /api/v1/agent/conversations``           -- create (201). Scope: ``flyquery.conversations:write``.
* ``GET  /api/v1/agent/conversations``           -- list. Scope: ``flyquery.conversations:read``.
* ``GET  /api/v1/agent/conversations/{id}``      -- fetch with turns. Scope: ``flyquery.conversations:read``.
* ``POST /api/v1/agent/conversations/{id}/turn`` -- drill-down turn. Scopes:
  ``flyquery.conversations:write`` + ``flyquery.query:read``.

Mutating endpoints require ``Idempotency-Key`` per the agent-tier
replay-dedup contract -- a retried turn would otherwise re-run the
4-agent pipeline and burn budget.
"""

from __future__ import annotations

import uuid

from pyfly.container import rest_controller
from pyfly.web import Body, PathVar, Valid, get_mapping, post_mapping, request_mapping
from starlette.requests import Request

from flyquery.core.services.auth.agent_token_service import AgentTokenService
from flyquery.core.services.query.conversation_service import ConversationService
from flyquery.interfaces.conversations import (
    ConversationCreate,
    ConversationRead,
    ConversationTurnRequest,
)
from flyquery.interfaces.pagination import Paginated
from flyquery.interfaces.query import AnswerResponse
from flyquery.web.controllers.conversations_controller import (
    ConversationsController as _UserConversationsController,
)
from flyquery.web.conventions import (
    HEADER_AGENT_TOKEN,
    FireflyHTTPException,
    IdempotencyStore,
    tenant_context_from_request,
)
from flyquery.web.idempotent_handler import replay_dedup

_SCOPE_CONV_READ = "flyquery.conversations:read"
_SCOPE_CONV_WRITE = "flyquery.conversations:write"


class MissingAgentToken(FireflyHTTPException):
    status = 401
    code = "missing_agent_token"
    title = "Missing X-Agent-Token header"


@rest_controller
@request_mapping("/api/v1/agent")
class AgentConversationsController:
    """Agent-tier mirror of :class:`ConversationsController`.

    Delegates the heavy lifting (turn pipeline) to the user-tier
    controller by composition -- mirrors the pattern already used by
    :class:`AgentSqlExecuteController`. Token + scope verification is
    enforced per-route here.
    """

    def __init__(
        self,
        user_conversations_controller: _UserConversationsController,
        conversation_service: ConversationService,
        agent_token_service: AgentTokenService,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._delegate = user_conversations_controller
        self._conversation_service = conversation_service
        self._token_service = agent_token_service
        self._idempotency_store = idempotency_store

    async def _verify(self, http_request: Request, scope: str) -> None:
        """Verify ``X-Agent-Token`` carries the required scope."""
        token = http_request.headers.get(HEADER_AGENT_TOKEN)
        if not token:
            raise MissingAgentToken("X-Agent-Token header is required for /api/v1/agent/* routes.")
        ctx = tenant_context_from_request(http_request)
        await self._token_service.verify(
            token,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            scope=scope,
        )

    # ------------------------------------------------------------------
    # POST /api/v1/agent/conversations  (create)
    # ------------------------------------------------------------------

    @post_mapping("/conversations", status_code=201)
    async def create(
        self,
        http_request: Request,
        body: Valid[Body[ConversationCreate]],
    ) -> ConversationRead:
        """Create a conversation owned by the calling agent.

        Replay-dedup'd via ``Idempotency-Key`` (required). A retried
        create otherwise allocates duplicate empty conversations the
        agent has no way to clean up.
        """
        await self._verify(http_request, _SCOPE_CONV_WRITE)
        ctx = tenant_context_from_request(http_request)

        async def _do_create() -> ConversationRead:
            return await self._delegate.create(http_request, body)

        return await replay_dedup(
            request=http_request,
            store=self._idempotency_store,
            tenant_id=ctx.tenant_id,
            route="POST /api/v1/agent/conversations",
            handler=_do_create,
            status_code=201,
            require_key=True,
        )

    # ------------------------------------------------------------------
    # GET /api/v1/agent/conversations  (list)
    # ------------------------------------------------------------------

    @get_mapping("/conversations")
    async def list_conversations(self, http_request: Request) -> Paginated[ConversationRead]:
        """List conversations for the agent's workspace (newest first)."""
        await self._verify(http_request, _SCOPE_CONV_READ)
        return await self._delegate.list_conversations(http_request)

    # ------------------------------------------------------------------
    # GET /api/v1/agent/conversations/{id}  (fetch with turns)
    # ------------------------------------------------------------------

    @get_mapping("/conversations/{conversation_id}")
    async def read(
        self,
        http_request: Request,
        conversation_id: PathVar[uuid.UUID],
    ) -> ConversationRead:
        """Fetch a conversation with its turns."""
        await self._verify(http_request, _SCOPE_CONV_READ)
        return await self._delegate.read(conversation_id)

    # ------------------------------------------------------------------
    # POST /api/v1/agent/conversations/{id}/turn  (drill-down)
    # ------------------------------------------------------------------

    @post_mapping("/conversations/{conversation_id}/turn")
    async def post_turn(
        self,
        http_request: Request,
        conversation_id: PathVar[uuid.UUID],
        body: Valid[Body[ConversationTurnRequest]],
    ) -> AnswerResponse:
        """Run a drill-down turn through the full query pipeline.

        Two scopes are required at the agent layer:
        ``flyquery.conversations:write`` (this is a mutating turn
        write) and the underlying ``flyquery.query:read`` (the pipeline
        executes a query). We verify the conversations scope here and
        delegate the query-tier check to the pipeline's scope guard.

        Replay-dedup'd via ``Idempotency-Key`` (required) -- the
        4-agent pipeline is the costliest endpoint in the API.
        """
        await self._verify(http_request, _SCOPE_CONV_WRITE)
        ctx = tenant_context_from_request(http_request)

        async def _do_turn() -> AnswerResponse:
            return await self._delegate.post_turn(http_request, conversation_id, body)

        return await replay_dedup(
            request=http_request,
            store=self._idempotency_store,
            tenant_id=ctx.tenant_id,
            route=f"POST /api/v1/agent/conversations/{conversation_id}/turn",
            handler=_do_turn,
            status_code=200,
            require_key=True,
        )


__all__ = ["AgentConversationsController"]
