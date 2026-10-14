# Copyright 2024-2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Independent service admission checks use no model or repository I/O."""

import uuid
from types import SimpleNamespace

import pytest

from flyquery.core.services.query.query_service import QueryService


@pytest.mark.asyncio
async def test_write_only_scope_cannot_reach_read_retrieval():
    calls = []

    class Audit:
        async def create_query(self, **kwargs):
            calls.append("audit")
            assert kwargs["dataset_id"] is None
            assert kwargs["executed_sql"] is None
            return uuid.uuid4()

    class Retrieval:
        async def retrieve(self, *args, **kwargs):
            calls.append("retrieval")
            raise AssertionError("Write-only admission reached read retrieval")

    service = object.__new__(QueryService)
    service._query_repo = Audit()
    service._retriever = Retrieval()
    service._settings = SimpleNamespace(top_k_schema=2, top_k_examples=2, top_k_metrics=2)

    result = await service.answer(
        tenant_id="synthetic-review",
        workspace_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        question="Synthetic write-only request",
        scopes={"flyquery.derived:write"},
    )

    assert result.execution_status == "REJECTED_BY_FIREWALL"
    assert result.sql is None
    assert calls == ["audit"]
