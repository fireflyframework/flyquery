# Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0
"""Actual read controllers/services against captured SQL, without a database."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from flyquery.core.services.schema_objects.schema_object_repository import SchemaObjectRepository
from flyquery.core.services.schema_objects.schema_object_service import SchemaObjectService
from flyquery.core.services.tables.schema_snapshot_repository import SchemaSnapshotRepository
from flyquery.core.services.tables.table_repository import TableRepository
from flyquery.core.services.tables.table_service import TableService
from flyquery.web.controllers.agent.tables_controller import AgentTablesController
from flyquery.web.controllers.schema_objects_controller import SchemaObjectsController
from flyquery.web.controllers.tables_controller import TablesController
from flyquery.web.conventions import ResourceNotFound

WORKSPACE = UUID(int=1)
OTHER_WORKSPACE = UUID(int=2)
DATASET = UUID(int=3)
TABLE = UUID(int=4)
OBJECT = UUID(int=5)
SNAPSHOT = UUID(int=6)
ROUTES = ("list_tables", "get_table", "list_snapshots", "list_objects", "list_changes", "get_schema_object")
CHILDREN = ("list_snapshots", "list_objects", "list_changes", "get_schema_object")


def row():
    stamp = datetime(2026, 10, 16, tzinfo=UTC)
    return {
        "id": OBJECT,
        "tenant_id": "tenant-a",
        "workspace_id": WORKSPACE,
        "dataset_id": DATASET,
        "table_id": TABLE,
        "snapshot_id": SNAPSHOT,
        "current_snapshot_id": SNAPSHOT,
        "name": "checks",
        "qualified_name": "checks.result",
        "kind": "COLUMN",
        "description": "Private scope canary",
        "is_active": True,
        "created_at": stamp,
        "updated_at": stamp,
        "last_changed_at": stamp,
        "taken_at": stamp,
        "n_columns": 1,
        "status": "READY",
        "triggered_by": "upload",
        "data_type": "TEXT",
        "is_nullable": False,
        "description_source": "HUMAN",
        "pii_tag": None,
        "pii_source": None,
        "business_owner": None,
        "next_snapshot_id": SNAPSHOT,
        "prev_snapshot_id": None,
        "column_name": "result",
        "change": "ADDED",
        "before_json": None,
        "after_json": {"data_type": "TEXT"},
        "llm_rationale": None,
    }


class Session:
    """Evaluate only the explicit bound scope predicates in these read queries."""

    def __init__(self, parent, child):
        self.parent, self.child, self.calls = parent, child, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def execute(self, statement, params):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, deepcopy(params)))
        direct_table = "FROM flyquery_tables t" in sql
        value = self.parent if direct_table else self.child
        allowed = value["tenant_id"] == params["tenant"]
        alias = (
            "t"
            if direct_table
            else "ss"
            if "FROM flyquery_schema_snapshots ss" in sql
            else "sc"
            if "FROM flyquery_schema_changes sc" in sql
            else "so"
        )
        if alias + ".workspace_id = :workspace" in sql:
            allowed = allowed and value["workspace_id"] == params["workspace"]
        if not direct_table and "JOIN flyquery_tables t" in sql:
            allowed = allowed and self.parent["tenant_id"] == params["tenant"]
            if "t.workspace_id = :workspace" in sql:
                allowed = allowed and self.parent["workspace_id"] == params["workspace"]
        values = [deepcopy(value)] if allowed else []
        if direct_table and "AS _scoped_snapshot_id" in sql:
            for item in values:
                item["_scoped_snapshot_id"] = item["current_snapshot_id"]
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(
                all=lambda: values,
                one_or_none=lambda: values[0] if values else None,
            )
        )


class Verifier:
    def __init__(self, denied=False):
        self.calls, self.denied = [], denied

    async def verify(self, token, **scope):
        self.calls.append((token, scope))
        if self.denied:
            raise PermissionError("Token scope denied")


def setup(parent=None, child=None, *, denied=False):
    parent = deepcopy(parent or row())
    parent["id"] = TABLE
    session = Session(parent, deepcopy(child or parent))

    def factory():
        return session

    tables = TablesController(TableService(TableRepository(factory), SchemaSnapshotRepository(factory)))
    objects = SchemaObjectsController(SchemaObjectService(SchemaObjectRepository(factory)))
    verifier = Verifier(denied)
    controller = AgentTablesController(tables, objects, verifier)
    request = SimpleNamespace(
        headers={
            "X-Tenant-Id": "tenant-a",
            "X-Workspace-Id": str(WORKSPACE),
            "X-Agent-Token": "fixture-agent",
        }
    )
    return controller, request, session, verifier


async def invoke(controller, request, route):
    identity = DATASET if route == "list_tables" else OBJECT if route == "get_schema_object" else TABLE
    return await getattr(controller, route)(request, identity)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("boundary", ("workspace", "tenant"))
async def test_agent_read_denies_foreign_scope(route, boundary):
    foreign = row()
    foreign[boundary + "_id"] = OTHER_WORKSPACE if boundary == "workspace" else "tenant-b"
    controller, request, session, verifier = setup(foreign, foreign)
    if route in {"get_table", "get_schema_object"}:
        with pytest.raises(ResourceNotFound):
            await invoke(controller, request, route)
    else:
        result = await invoke(controller, request, route)
        assert result.items == [] and result.total == 0
    assert len(verifier.calls) == 1 and session.calls
    assert verifier.calls[0][1] == {
        "tenant_id": "tenant-a",
        "workspace_id": str(WORKSPACE),
        "scope": "flyquery.schema:read",
    }


@pytest.mark.parametrize("route", ROUTES)
async def test_agent_own_scope_keeps_existing_response_fields(route):
    controller, request, session, _ = setup()
    result = await invoke(controller, request, route)
    value = result if route in {"get_table", "get_schema_object"} else result.items[0]
    assert value.id == TABLE
    if route in {"list_tables", "get_table", "list_objects", "get_schema_object"}:
        assert value.tenant_id == "tenant-a" and value.workspace_id == WORKSPACE
        assert value.description == "Private scope canary"
    if route in {"list_snapshots", "list_changes"}:
        assert value.table_id == TABLE
    assert session.calls
    for sql, params in session.calls:
        assert params["workspace"] == WORKSPACE
        assert "workspace_id = :workspace" in sql


@pytest.mark.parametrize("route", CHILDREN)
async def test_agent_child_cannot_escape_foreign_parent_workspace(route):
    parent, child = row(), row()
    parent["workspace_id"] = OTHER_WORKSPACE
    controller, request, session, _ = setup(parent, child)
    if route == "get_schema_object":
        with pytest.raises(ResourceNotFound):
            await invoke(controller, request, route)
    else:
        assert (await invoke(controller, request, route)).items == []
    assert all(
        "JOIN flyquery_tables t" in sql and "t.workspace_id = :workspace" in sql for sql, _ in session.calls
    )


@pytest.mark.parametrize("route", CHILDREN)
async def test_agent_child_cannot_escape_its_own_workspace(route):
    parent, child = row(), row()
    child["workspace_id"] = OTHER_WORKSPACE
    controller, request, _, _ = setup(parent, child)
    if route == "get_schema_object":
        with pytest.raises(ResourceNotFound):
            await invoke(controller, request, route)
    else:
        assert (await invoke(controller, request, route)).items == []


@pytest.mark.parametrize("route", ROUTES)
async def test_agent_token_refusal_precedes_repository_read(route):
    controller, request, session, _ = setup(denied=True)
    with pytest.raises(PermissionError, match="Token scope denied"):
        await invoke(controller, request, route)
    assert session.calls == []
