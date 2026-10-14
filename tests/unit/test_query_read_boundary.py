# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0

"""Native read-boundary regressions using only owned fictional files."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flyquery.core.services.execution.ast_classifier import AstClassification, AstClassifier
from flyquery.core.services.execution.duckdb_executor import (
    DmlMutationResult,
    DuckDBExecutor,
    ExecutionError,
    ExecutionResult,
)
from flyquery.core.services.execution.scope_guard import ScopeGuard, ScopeGuardError


class Settings:
    duckdb_memory_limit = "256MB"
    default_row_cap = 100
    default_statement_timeout_ms = 5000


def check(sql: str, kinds=None, allowlist=None, datasets=None) -> None:
    ScopeGuard().check(
        classification=AstClassifier().classify(sql),
        scopes={"flyquery.query:read", "flyquery.derived:write"},
        table_kinds_by_name=kinds or {},
        dataset_allowlist=allowlist,
        dataset_of_table=datasets or {},
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv_auto('/owned/unregistered.csv')",
        "SELECT * FROM read_csv('/owned/unregistered.csv')",
        "SELECT * FROM read_parquet('/owned/unregistered.parquet')",
        "SELECT * FROM read_json_auto('/owned/unregistered.json')",
        "SELECT * FROM read_blob('/owned/unregistered.txt')",
        "SELECT * FROM glob('/owned/*')",
        "SELECT * FROM query('SELECT 1')",
        "SELECT * FROM query_table('orders')",
        "SELECT * FROM read_csv_auto('http://127.0.0.1:49152/unregistered.csv')",
        "SELECT current_setting('s3_secret_access_key')",
        "SELECT getenv('SYNTHETIC_FIXTURE_VALUE')",
        "SELECT * FROM duckdb_secrets()",
        "SELECT * FROM (SELECT * FROM read_csv_auto('/owned/unregistered.csv')) x",
        "WITH x AS (SELECT * FROM read_csv_auto('/owned/unregistered.csv')) SELECT * FROM x",
        "SELECT 1 UNION ALL SELECT * FROM read_csv_auto('/owned/unregistered.csv')",
    ],
)
def test_unadmitted_sources_fail_closed_before_execution(sql: str) -> None:
    with pytest.raises(ScopeGuardError):
        check(sql, {"orders": "UPLOADED"}, {"owned"}, {"orders": "owned"})


@pytest.mark.parametrize(
    "sql", ["PRAGMA version", "SET threads=4", "SELECT * FROM '/owned/unregistered.parquet'"]
)
def test_unknown_statements_and_unregistered_tables_have_no_read_authority(sql: str) -> None:
    with pytest.raises(ScopeGuardError):
        check(sql)


def test_missing_dataset_mapping_cannot_bypass_an_empty_allowlist() -> None:
    with pytest.raises(ScopeGuardError):
        check("SELECT * FROM orders", {"orders": "UPLOADED"}, set(), {})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(total) FROM orders",
        "WITH x AS (SELECT SUM(total) AS total FROM orders) SELECT total FROM x",
        "SELECT o.total FROM orders o JOIN orders p ON o.id=p.id",
    ],
)
def test_registered_sources_keep_actual_dataset_authority(sql: str) -> None:
    check(sql, {"orders": "UPLOADED"}, {"owned"}, {"orders": "owned"})
    with pytest.raises(ScopeGuardError):
        check(sql, {"orders": "UPLOADED"}, {"other"}, {"orders": "owned"})


def test_constant_cte_does_not_invent_a_dataset_grant() -> None:
    ast = AstClassifier().classify("WITH x AS (SELECT 1 AS n) SELECT n FROM x")
    assert ast.table_refs == ()
    check("WITH x AS (SELECT 1 AS n) SELECT n FROM x", allowlist=set())


@pytest.mark.asyncio
async def test_executor_itself_refuses_an_unregistered_owned_csv(tmp_path: Path) -> None:
    file = tmp_path / "unregistered.csv"
    file.write_text("evidence\nsynthetic-unregistered-file\n")
    result = await DuckDBExecutor(Settings()).execute(f"SELECT * FROM read_csv_auto('{file}')", {})
    assert isinstance(result, ExecutionError)


@pytest.mark.asyncio
async def test_executor_itself_refuses_implicit_file_tables(tmp_path: Path) -> None:
    file = tmp_path / "unregistered.parquet"
    pq.write_table(pa.Table.from_pylist([{"evidence": "synthetic-unregistered-file"}]), file)
    result = await DuckDBExecutor(Settings()).execute(f"SELECT * FROM '{file}'", {})
    assert isinstance(result, ExecutionError)


@pytest.mark.asyncio
async def test_native_path_fence_survives_a_parser_omission(tmp_path: Path, monkeypatch) -> None:
    file = tmp_path / "unregistered.csv"
    file.write_text("evidence\nsynthetic-unregistered-file\n")
    monkeypatch.setattr(
        AstClassifier, "classify", lambda self, sql: AstClassification("SELECT", True, (), (), False)
    )
    result = await DuckDBExecutor(Settings()).execute(f"SELECT * FROM read_csv_auto('{file}')", {})
    assert isinstance(result, ExecutionError)


@pytest.mark.asyncio
async def test_registered_apostrophe_path_and_quoted_identifier_are_data_not_bootstrap_sql(
    tmp_path: Path,
) -> None:
    file = tmp_path / "registered's snapshot.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 25}]), file)
    result = await DuckDBExecutor(Settings()).execute(
        'SELECT total FROM "orders""qa"', {'orders"qa': str(file)}
    )
    assert isinstance(result, ExecutionResult)
    assert result.rows == [{"total": 25}]


@pytest.mark.asyncio
async def test_registered_cte_and_reviewed_pure_builtins_preserve_rows(tmp_path: Path) -> None:
    file = tmp_path / "orders.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 10}, {"id": 2, "total": 20}]), file)
    result = await DuckDBExecutor(Settings()).execute(
        "WITH x AS (SELECT id, total FROM orders) SELECT SUM(total) AS total, COUNT(*) AS n, ROUND(AVG(total)) AS average FROM x",
        {"orders": str(file)},
    )
    assert isinstance(result, ExecutionResult)
    assert result.rows == [{"total": 30, "n": 2, "average": 15.0}]


@pytest.mark.asyncio
async def test_derived_copy_on_write_stays_scoped_and_preserves_original(tmp_path: Path) -> None:
    file = tmp_path / "derived.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 10}]), file)
    original = file.read_bytes()
    result = await DuckDBExecutor(Settings()).execute(
        "INSERT INTO derived VALUES (2, 20)",
        {"derived": str(file)},
        {"derived": str(file)},
    )
    assert isinstance(result, DmlMutationResult)
    assert pq.read_table(pa.BufferReader(result.new_parquet_bytes)).to_pylist() == [
        {"id": 1, "total": 10},
        {"id": 2, "total": 20},
    ]
    assert file.read_bytes() == original


@pytest.mark.asyncio
async def test_derived_mutation_cannot_import_an_unregistered_file(tmp_path: Path) -> None:
    file = tmp_path / "derived.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 10}]), file)
    other = tmp_path / "unregistered.csv"
    other.write_text("id,total\n2,20\n")
    result = await DuckDBExecutor(Settings()).execute(
        f"INSERT INTO derived SELECT * FROM read_csv_auto('{other}')",
        {"derived": str(file)},
        {"derived": str(file)},
    )
    assert isinstance(result, ExecutionError)


@pytest.mark.asyncio
async def test_selecting_a_derived_snapshot_is_read_only(tmp_path: Path) -> None:
    file = tmp_path / "derived.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 10}]), file)
    result = await DuckDBExecutor(Settings()).execute(
        "SELECT * FROM derived", {"derived": str(file)}, {"derived": str(file)}
    )
    assert isinstance(result, ExecutionResult)
    assert result.rows == [{"id": 1, "total": 10}]


@pytest.mark.asyncio
async def test_reviewed_boolean_aggregate_is_not_mistaken_for_an_external_function(tmp_path: Path) -> None:
    file = tmp_path / "orders.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 10}, {"id": 2, "total": 20}]), file)
    result = await DuckDBExecutor(Settings()).execute(
        "SELECT bool_and(total > 0) AS positive FROM orders", {"orders": str(file)}
    )
    assert isinstance(result, ExecutionResult)
    assert result.rows == [{"positive": True}]


@pytest.mark.asyncio
async def test_unregistered_loopback_url_is_denied_without_an_http_request() -> None:
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"evidence\nsynthetic-unregistered-network-file\n")

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            sql = f"SELECT * FROM read_csv_auto('http://127.0.0.1:{server.server_port}/unregistered.csv')"
            result = await DuckDBExecutor(Settings()).execute(sql, {})
        finally:
            server.shutdown()
            worker.join()
    assert isinstance(result, ExecutionError)
    assert requests == []


@pytest.mark.asyncio
async def test_correlated_exists_preserves_registered_parquet_authority(tmp_path: Path) -> None:
    file = tmp_path / "orders.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 25}]), file)
    sql = "SELECT total FROM orders WHERE EXISTS (SELECT 1 FROM orders p WHERE p.id=orders.id)"
    result = await DuckDBExecutor(Settings()).execute(sql, {"orders": str(file)})
    assert isinstance(result, ExecutionResult)
    assert result.rows == [{"total": 25}]
    ast = AstClassifier().classify(sql)
    assert ast.table_refs == ("orders",)
    assert not ast.unsupported_sql
    check(sql, {"orders": "UPLOADED"}, {"owned"}, {"orders": "owned"})
    with pytest.raises(ScopeGuardError):
        check(sql, {"orders": "UPLOADED"}, {"other"}, {"orders": "owned"})


@pytest.mark.parametrize("nested_source", ["read_csv_auto", "unregistered"])
@pytest.mark.asyncio
async def test_exists_does_not_admit_nested_unregistered_sources(tmp_path: Path, nested_source: str) -> None:
    file = tmp_path / "orders.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 1, "total": 25}]), file)
    unregistered = tmp_path / "unregistered.csv"
    unregistered.write_text("id\n1\n")
    source = f"read_csv_auto('{unregistered}')" if nested_source == "read_csv_auto" else nested_source
    sql = f"SELECT total FROM orders WHERE EXISTS (SELECT 1 FROM {source} p WHERE p.id=orders.id)"
    ast = AstClassifier().classify(sql)
    if nested_source == "read_csv_auto":
        assert ast.unsupported_sql
    else:
        assert not ast.unsupported_sql
        assert ast.table_refs == ("orders", "unregistered")
    with pytest.raises(ScopeGuardError):
        check(sql, {"orders": "UPLOADED"}, {"owned"}, {"orders": "owned"})
    result = await DuckDBExecutor(Settings()).execute(sql, {"orders": str(file)})
    assert isinstance(result, ExecutionError)
