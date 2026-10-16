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

"""Schema objects controller.

GET /api/v1/schema-objects/{object_id}
PUT /api/v1/schema-objects/{object_id}
  -- update description (sets description_source='HUMAN'), pii_tag (pii_source='HUMAN'),
     business_owner, governance_json, synonyms_json

The controller is a thin HTTP adapter -- all SQL + the source-tagging
policy live in :class:`SchemaObjectService`.
"""

from __future__ import annotations

import uuid

from pyfly.container import rest_controller
from pyfly.web import Body, PathVar, Valid, get_mapping, put_mapping, request_mapping
from starlette.requests import Request

from flyquery.core.services.schema_objects.schema_object_service import (
    SchemaObjectService,
)
from flyquery.interfaces.files import SchemaObjectRead, SchemaObjectUpdate
from flyquery.web.conventions import ResourceNotFound, tenant_context_from_request


@rest_controller
@request_mapping("/api/v1/schema-objects")
class SchemaObjectsController:
    """REST adapter for schema knowledge-base column/table objects."""

    def __init__(self, service: SchemaObjectService) -> None:
        self._service = service

    @get_mapping("/{object_id}")
    async def get_object(
        self,
        http_request: Request,
        object_id: PathVar[uuid.UUID],
    ) -> SchemaObjectRead:
        """Get a single schema object by ID."""
        ctx = tenant_context_from_request(http_request)
        row = await self._service.get(
            object_id, tenant_id=ctx.tenant_id, workspace_id=uuid.UUID(ctx.workspace_id)
        )
        if row is None:
            raise ResourceNotFound(f"schema object {object_id!r} not found")
        return _row_to_read(row)

    @put_mapping("/{object_id}", status_code=200)
    async def update_object(
        self,
        http_request: Request,
        object_id: PathVar[uuid.UUID],
        body: Valid[Body[SchemaObjectUpdate]],
    ) -> SchemaObjectRead:
        """Update human-set fields on a schema object.

        Sets description_source='HUMAN' when description is provided.
        Sets pii_source='HUMAN' when pii_tag is provided.
        """
        ctx = tenant_context_from_request(http_request)
        row = await self._service.update(
            object_id,
            tenant_id=ctx.tenant_id,
            body=body,
        )
        if row is None:
            raise ResourceNotFound(f"schema object {object_id!r} not found")
        return _row_to_read(row)


def _row_to_read(row: dict) -> SchemaObjectRead:
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
