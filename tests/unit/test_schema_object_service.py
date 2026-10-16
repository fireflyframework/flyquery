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

"""Unit tests for SchemaObjectService -- focuses on the source-tagging policy."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from flyquery.core.services.schema_objects.schema_object_service import (
    SchemaObjectService,
)
from flyquery.interfaces.files import SchemaObjectUpdate


class _CapturingRepo:
    def __init__(self) -> None:
        self.last_get: tuple[uuid.UUID, str] | None = None
        self.last_workspace: uuid.UUID | None = None
        self.last_update: dict[str, Any] | None = None
        self.row: dict[str, Any] | None = None

    async def get(
        self, object_id: uuid.UUID, *, tenant_id: str, workspace_id: uuid.UUID
    ) -> dict[str, Any] | None:
        self.last_get = (object_id, tenant_id)
        self.last_workspace = workspace_id
        return self.row

    async def update(
        self,
        object_id: uuid.UUID,
        *,
        tenant_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        self.last_update = {"object_id": object_id, "tenant_id": tenant_id, "fields": fields}
        return self.row


@pytest.mark.asyncio
async def test_get_forwards_to_repo() -> None:
    repo = _CapturingRepo()
    repo.row = {"id": uuid.uuid4()}
    svc = SchemaObjectService(repo)  # type: ignore[arg-type]
    oid = uuid.uuid4()
    workspace = uuid.uuid4()
    out = await svc.get(oid, tenant_id="acme", workspace_id=workspace)
    assert out is repo.row
    assert repo.last_get == (oid, "acme")
    assert repo.last_workspace == workspace


@pytest.mark.asyncio
async def test_update_flips_description_source_to_HUMAN_on_explicit_description() -> None:
    repo = _CapturingRepo()
    repo.row = {"id": uuid.uuid4()}
    svc = SchemaObjectService(repo)  # type: ignore[arg-type]
    oid = uuid.uuid4()
    await svc.update(
        oid,
        tenant_id="acme",
        body=SchemaObjectUpdate(description="Total revenue, USD"),
    )
    assert repo.last_update is not None
    fields = repo.last_update["fields"]
    assert fields["description"] == "Total revenue, USD"
    assert fields["description_source"] == "HUMAN"


@pytest.mark.asyncio
async def test_update_flips_pii_source_to_HUMAN_on_explicit_pii_tag() -> None:
    repo = _CapturingRepo()
    repo.row = {"id": uuid.uuid4()}
    svc = SchemaObjectService(repo)  # type: ignore[arg-type]
    oid = uuid.uuid4()
    await svc.update(
        oid,
        tenant_id="acme",
        body=SchemaObjectUpdate(pii_tag="EMAIL"),
    )
    fields = repo.last_update["fields"]
    assert fields["pii_tag"] == "EMAIL"
    assert fields["pii_source"] == "HUMAN"


@pytest.mark.asyncio
async def test_update_omits_source_flags_when_description_not_set() -> None:
    """If the caller only updates business_owner, source flags stay untouched."""
    repo = _CapturingRepo()
    repo.row = {"id": uuid.uuid4()}
    svc = SchemaObjectService(repo)  # type: ignore[arg-type]
    oid = uuid.uuid4()
    await svc.update(
        oid,
        tenant_id="acme",
        body=SchemaObjectUpdate(business_owner="finance-team"),
    )
    fields = repo.last_update["fields"]
    assert fields == {"business_owner": "finance-team"}


@pytest.mark.asyncio
async def test_update_returns_none_when_repo_returns_none() -> None:
    """Repo returning None (row missing for tenant) propagates so the controller can 404."""
    repo = _CapturingRepo()
    repo.row = None
    svc = SchemaObjectService(repo)  # type: ignore[arg-type]
    out = await svc.update(
        uuid.uuid4(),
        tenant_id="acme",
        body=SchemaObjectUpdate(description="x"),
    )
    assert out is None
