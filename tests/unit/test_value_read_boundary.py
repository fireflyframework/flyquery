# Copyright 2024-2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Native value reads use synthetic owned Parquet, never models or a database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flyquery.core.services.execution.ast_classifier import AstClassifier
from flyquery.core.services.execution.duckdb_executor import DuckDBExecutor, ExecutionError
from flyquery.core.services.query.query_service import QueryService


class _Settings:
    duckdb_memory_limit = "256MB"
    default_row_cap = 3
    default_statement_timeout_ms = 5000
    entity_resolution_max_literals = 8
    group_coverage_repair_enabled = False
    signed_measure_repair_enabled = True
    entity_resolution_enabled = True
    group_resolution_enabled = True


class _Executor(DuckDBExecutor):
    def __init__(self, *, deny=False):
        super().__init__(_Settings())
        self.calls = []
        self.deny = deny

    async def execute(self, sql, attached_tables, derived_tables=None):
        self.calls.append((sql, dict(attached_tables)))
        if self.deny:
            return ExecutionError("synthetic executor denial")
        return await super().execute(sql, attached_tables, derived_tables)


class _Resolver:
    def __init__(self, snapshots, current="old"):
        self.snapshots = snapshots
        self.current = current
        self.captures = []
        self.resolutions = []

    async def current_snapshots(self, dataset_id, table_names):
        self.captures.append(list(table_names))
        return dict.fromkeys(table_names, self.current)

    async def resolve(self, dataset_id, table_names, pins=None):
        self.resolutions.append(dict(pins or {}))
        return {name: str(self.snapshots[(pins or {}).get(name, self.current)]) for name in table_names}


def _write(path, rows):
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _service(resolver, executor=None):
    service = object.__new__(QueryService)
    service._table_resolver = resolver
    service._executor = executor or _Executor()
    service._settings = _Settings()
    return service


def _bundle(catalog, *, table="orders", pins=None):
    return {
        "schema_inventory": [SimpleNamespace(metadata={"kind": "TABLE", "qualified_name": table})],
        "column_catalog": catalog,
        "snapshot_pins": dict(pins or {}),
    }


def _column(name, **metadata):
    return {"qualified_name": name, "data_type": "VARCHAR", **metadata}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [{"value_access": False}, {}, {"value_access": True, "sample_values_json": []}],
    ids=["redacted", "missing-authorization", "redaction-marker"],
)
async def test_live_scan_excludes_columns_without_affirmative_value_access(tmp_path, metadata):
    path = _write(tmp_path / "owned.parquet", [{"name": "Synthetic Restricted Value"}])
    resolver = _Resolver({"old": path})
    service = _service(resolver)
    bundle = _bundle([_column("orders.name", **metadata)])

    found = await service._scan_columns_for_values(uuid.uuid4(), ["Synthetic Restricted Value"], bundle)

    assert found == []
    assert service._executor.calls == []
    assert resolver.resolutions == []


@pytest.mark.asyncio
async def test_live_scan_reads_only_catalog_authorized_columns(tmp_path):
    path = _write(
        tmp_path / "owned.parquet",
        [
            {
                "public_name": "Synthetic Value",
                "redacted": "Synthetic Value",
                "unregistered": "Synthetic Value",
            }
        ],
    )
    service = _service(_Resolver({"old": path}))
    bundle = _bundle(
        [_column("orders.public_name", value_access=True), _column("orders.redacted", value_access=False)]
    )

    found = await service._scan_columns_for_values(uuid.uuid4(), ["Synthetic Value"], bundle)

    assert [entry["column"] for entry in found] == ["orders.public_name"]
    assert service._executor.calls
    assert all("redacted" not in sql and "unregistered" not in sql for sql, _ in service._executor.calls)


@pytest.mark.asyncio
async def test_live_scan_uses_executor_denial_without_unfenced_fallback(tmp_path):
    path = _write(tmp_path / "owned.parquet", [{"name": "Synthetic Value"}])
    service = _service(_Resolver({"old": path}), _Executor(deny=True))

    found = await service._scan_columns_for_values(
        uuid.uuid4(), ["Synthetic Value"], _bundle([_column("orders.name", value_access=True)])
    )

    assert found == []
    assert len(service._executor.calls) == 1


@pytest.mark.asyncio
async def test_live_scan_handles_real_quoted_registered_paths_and_identifiers(tmp_path):
    path = _write(tmp_path / "owned'quoted.parquet", [{'name"column': "Synthetic Value"}])
    service = _service(_Resolver({"old": path}))
    table = 'orders"table'

    found = await service._scan_columns_for_values(
        uuid.uuid4(),
        ["Synthetic Value"],
        _bundle([_column(f'{table}.name"column', value_access=True)], table=table),
    )

    assert [entry["column"] for entry in found] == [f'{table}.name"column']
    assert service._executor.calls[0][1] == {table: str(path)}


@pytest.mark.asyncio
async def test_live_scan_cannot_expand_registered_glob_to_unregistered_files(tmp_path):
    _write(tmp_path / "allowed.parquet", [{"name": "Synthetic Allowed"}])
    _write(tmp_path / "unregistered.parquet", [{"name": "Synthetic Outside"}])
    service = _service(_Resolver({"old": tmp_path / "*.parquet"}))

    found = await service._scan_columns_for_values(
        uuid.uuid4(), ["Synthetic Outside"], _bundle([_column("orders.name", value_access=True)])
    )

    assert found == []
    assert service._executor.calls


@pytest.mark.asyncio
async def test_live_scan_cannot_interpret_registered_path_as_a_sql_join(tmp_path):
    allowed = _write(tmp_path / "allowed.parquet", [{"public_name": "Synthetic Allowed"}])
    outside = _write(tmp_path / "unregistered.parquet", [{"secret_label": "Synthetic Outside"}])
    hostile = f"{allowed}') CROSS JOIN read_parquet('{outside}"
    service = _service(_Resolver({"old": hostile}))

    found = await service._scan_columns_for_values(
        uuid.uuid4(), ["Synthetic Outside"], _bundle([_column("orders.secret_label", value_access=True)])
    )

    assert found == []
    assert service._executor.calls


@pytest.mark.asyncio
async def test_conflicting_value_metadata_cannot_restore_a_blocked_column(tmp_path):
    path = _write(tmp_path / "owned.parquet", [{"name": "Synthetic Restricted"}])
    service = _service(_Resolver({"old": path}))
    bundle = _bundle(
        [
            _column("orders.name", value_access=False),
            _column("orders.name", value_access=True),
        ]
    )

    assert await service._scan_columns_for_values(uuid.uuid4(), ["Synthetic Restricted"], bundle) == []
    assert service._executor.calls == []


@pytest.mark.asyncio
async def test_entity_catalog_does_not_override_denied_value_access(tmp_path):
    path = _write(tmp_path / "owned.parquet", [{"name": "Synthetic Restricted"}])
    service = _service(_Resolver({"old": path}))
    catalog = [_column("orders.name", value_access=False, values=["Synthetic Restricted"])]

    resolution = await service._resolve_entities(
        uuid.uuid4(), "Find 'Synthetic Restricted'", catalog, _bundle(catalog)
    )

    assert resolution["entities"] == []
    assert resolution["groups"] == []
    assert service._executor.calls == []


@pytest.mark.asyncio
async def test_live_scan_reuses_captured_snapshot_after_reingestion(tmp_path):
    old = _write(tmp_path / "old.parquet", [{"name": "Synthetic Original"}])
    new = _write(tmp_path / "new.parquet", [{"name": "Synthetic Replacement"}])
    resolver = _Resolver({"old": old, "new": new})
    service = _service(resolver)
    bundle = _bundle([_column("orders.name", value_access=True)])
    dataset_id = uuid.uuid4()

    first = await service._scan_columns_for_values(dataset_id, ["Synthetic Original"], bundle)
    resolver.current = "new"
    second = await service._scan_columns_for_values(
        dataset_id, ["Synthetic Original", "Synthetic Replacement"], bundle
    )

    assert first == second
    assert first[0]["value"] == "Synthetic Original"
    assert bundle["snapshot_pins"] == {"orders": "old"}
    assert len(resolver.captures) == 1
    assert resolver.resolutions == [{"orders": "old"}, {"orders": "old"}]


_SIGNED_SQL = (
    "SELECT SUM(CASE WHEN line = 'Revenue' THEN amount ELSE 0 END) "
    "- SUM(CASE WHEN line = 'Cost' THEN amount ELSE 0 END) FROM orders"
)


def _signed_catalog(*, measure_access=True, dimension_access=True):
    return [
        _column("orders.line", value_access=dimension_access),
        _column(
            "orders.amount",
            data_type="DOUBLE",
            semantic_type="amount",
            mixed_sign=True,
            value_access=measure_access,
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["measure", "dimension"])
async def test_signed_probe_requires_both_columns_to_allow_values(tmp_path, blocked):
    path = _write(tmp_path / "owned.parquet", [{"line": "Cost", "amount": -7.0}])
    catalog = _signed_catalog(measure_access=blocked != "measure", dimension_access=blocked != "dimension")
    service = _service(_Resolver({"old": path}))

    hint = await service._advisory_repair(
        _SIGNED_SQL,
        AstClassifier().classify(_SIGNED_SQL),
        catalog,
        "Synthetic question",
        uuid.uuid4(),
        _bundle(catalog),
    )

    assert hint is None
    assert service._executor.calls == []


@pytest.mark.asyncio
async def test_signed_probe_uses_the_same_pinned_registered_snapshot(tmp_path):
    old = _write(tmp_path / "old'quoted.parquet", [{"line": "Cost", "amount": -7.0}])
    new = _write(tmp_path / "new.parquet", [{"line": "Cost", "amount": 7.0}])
    resolver = _Resolver({"old": old, "new": new}, current="new")
    service = _service(resolver)
    catalog = _signed_catalog()
    bundle = _bundle(catalog, pins={"orders": "old"})

    hint = await service._advisory_repair(
        _SIGNED_SQL,
        AstClassifier().classify(_SIGNED_SQL),
        catalog,
        "Synthetic question",
        uuid.uuid4(),
        bundle,
    )

    assert hint and "SIGN ERROR" in hint
    assert resolver.captures == []
    assert resolver.resolutions == [{"orders": "old"}]
    assert service._executor.calls
    assert all(attached == {"orders": str(old)} for _, attached in service._executor.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{}, {"value_access": True, "sample_values_json": []}])
async def test_signed_probe_does_not_infer_missing_or_redacted_access(tmp_path, metadata):
    path = _write(tmp_path / "owned.parquet", [{"line": "Cost", "amount": -7.0}])
    catalog = _signed_catalog()
    catalog[0].pop("value_access")
    catalog[0].update(metadata)
    service = _service(_Resolver({"old": path}))

    hint = await service._advisory_repair(
        _SIGNED_SQL,
        AstClassifier().classify(_SIGNED_SQL),
        catalog,
        "Synthetic question",
        uuid.uuid4(),
        _bundle(catalog),
    )

    assert hint is None
    assert service._executor.calls == []


@pytest.mark.asyncio
async def test_signed_probe_cannot_interpret_registered_path_as_a_sql_join(tmp_path):
    allowed = _write(tmp_path / "allowed.parquet", [{"line": "Cost"}])
    outside = _write(tmp_path / "unregistered.parquet", [{"amount": -7.0}])
    hostile = f"{allowed}') CROSS JOIN read_parquet('{outside}"
    service = _service(_Resolver({"old": hostile}))
    catalog = _signed_catalog()

    hint = await service._advisory_repair(
        _SIGNED_SQL,
        AstClassifier().classify(_SIGNED_SQL),
        catalog,
        "Synthetic question",
        uuid.uuid4(),
        _bundle(catalog),
    )

    assert hint is None
    assert service._executor.calls


@pytest.mark.asyncio
async def test_signed_probe_honors_executor_denial_without_fallback(tmp_path):
    path = _write(tmp_path / "owned.parquet", [{"line": "Cost", "amount": -7.0}])
    service = _service(_Resolver({"old": path}), _Executor(deny=True))
    catalog = _signed_catalog()

    hint = await service._advisory_repair(
        _SIGNED_SQL,
        AstClassifier().classify(_SIGNED_SQL),
        catalog,
        "Synthetic question",
        uuid.uuid4(),
        _bundle(catalog),
    )

    assert hint is None
    assert len(service._executor.calls) == 1


@pytest.mark.asyncio
async def test_signed_probe_never_reports_a_sum_from_a_truncated_literal_set(tmp_path):
    labels = [f"Synthetic Cost {i}" for i in range(26)]
    rows = [{"line": label, "amount": -1.0 if i < 25 else 30.0} for i, label in enumerate(labels)]
    path = _write(tmp_path / "owned.parquet", rows)
    service = _service(_Resolver({"old": path}))
    catalog = _signed_catalog()
    quoted = ", ".join(f"'{label}'" for label in labels)
    sql = _SIGNED_SQL.replace("line = 'Cost'", f"line IN ({quoted})")

    hint = await service._advisory_repair(
        sql, AstClassifier().classify(sql), catalog, "Synthetic question", uuid.uuid4(), _bundle(catalog)
    )

    assert hint is None
    assert service._executor.calls == []
