# Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0
"""Read projection of an owned table with an inconsistent retained snapshot pointer."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from flyquery.core.services.tables.table_repository import TableRepository
from flyquery.web.controllers.tables_controller import _table_row_to_read
from tests.unit.test_agent_table_scope import DATASET, SNAPSHOT, TABLE, WORKSPACE, row

METHODS = ("list_for_dataset", "get", "search", "find_by_name")


class Session:
    def __init__(self, snapshot):
        self.parent = {**row(), "id": TABLE}
        self.snapshot, self.calls = snapshot, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def execute(self, statement, params):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params))
        assert params["tenant"] == self.parent["tenant_id"]
        assert params["workspace"] == self.parent["workspace_id"]
        joined = self.snapshot is not None and self.snapshot["id"] == self.parent["current_snapshot_id"]
        for child, parent in (
            ("tenant_id", "tenant_id"),
            ("workspace_id", "workspace_id"),
            ("dataset_id", "dataset_id"),
            ("table_id", "id"),
        ):
            if f"ss.{child} = t.{parent}" in sql:
                joined = joined and self.snapshot[child] == self.parent[parent]
        result = {**deepcopy(self.parent), "n_columns": self.snapshot["n_columns"] if joined else None}
        if "AS _scoped_snapshot_id" in sql:
            result["_scoped_snapshot_id"] = self.snapshot["id"] if joined else None
        if "AS _total" in sql:
            result["_total"] = 1
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(all=lambda: [result], one_or_none=lambda: result)
        )


def snapshot():
    return {
        "id": SNAPSHOT,
        "table_id": TABLE,
        "dataset_id": DATASET,
        "tenant_id": "tenant-a",
        "workspace_id": WORKSPACE,
        "n_columns": 777,
    }


async def read(method, session):
    def factory():
        return session

    repo = TableRepository(factory)
    scope = {"tenant_id": "tenant-a", "workspace_id": WORKSPACE}
    if method == "get":
        return await repo.get(TABLE, **scope)
    if method == "list_for_dataset":
        return (await repo.list_for_dataset(DATASET, **scope))[0]
    if method == "find_by_name":
        return (await repo.find_by_name("checks", dataset_id=DATASET, **scope))[0]
    rows, total = await repo.search(dataset_id=DATASET, **scope)
    assert total == 1
    return rows[0]


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("boundary", ("tenant_id", "workspace_id", "dataset_id", "table_id"))
async def test_owned_table_never_projects_foreign_snapshot_metadata(method, boundary):
    foreign = snapshot()
    foreign[boundary] = "tenant-b" if boundary == "tenant_id" else UUID(int=100)
    session = Session(foreign)
    result = await read(method, session)
    assert result["id"] == TABLE and result["description"] == "Private scope canary"
    assert result["n_columns"] is None
    assert result["current_snapshot_id"] is None
    assert session.parent["current_snapshot_id"] == SNAPSHOT  # No repair/write of retained data.
    expected = {**session.parent, "n_columns": None, "current_snapshot_id": None}
    assert _table_row_to_read(result).model_dump(mode="json") == _table_row_to_read(expected).model_dump(
        mode="json"
    )
    for sql, _ in session.calls:
        assert "LEFT JOIN flyquery_schema_snapshots ss" in sql
        for child, parent in (
            ("tenant_id", "tenant_id"),
            ("workspace_id", "workspace_id"),
            ("dataset_id", "dataset_id"),
            ("table_id", "id"),
        ):
            assert f"ss.{child} = t.{parent}" in sql


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("columns", (0, 4))
async def test_owned_snapshot_keeps_complete_positive_dto(method, columns):
    own = {**snapshot(), "n_columns": columns}
    session = Session(own)
    result = await read(method, session)
    assert result == {**session.parent, "n_columns": columns}
    expected = {**session.parent, "n_columns": columns}
    assert _table_row_to_read(result).model_dump(mode="json") == _table_row_to_read(expected).model_dump(
        mode="json"
    )


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("pointer", (None, SNAPSHOT))
async def test_missing_snapshot_stays_absent_without_dropping_parent(method, pointer):
    session = Session(None)
    session.parent["current_snapshot_id"] = pointer
    result = await read(method, session)
    assert result == {**session.parent, "n_columns": None, "current_snapshot_id": None}
    assert session.parent["current_snapshot_id"] == pointer
