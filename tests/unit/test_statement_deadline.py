# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0

"""Deadline and cancellation probes execute actual DuckDB over owned Parquet."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flyquery.config import FlyquerySettings
from flyquery.core.services.execution.duckdb_executor import (
    DuckDBExecutor,
    ExecutionError,
    ExecutionResult,
)


class Settings:
    duckdb_memory_limit = "256MB"
    default_row_cap = 10
    default_statement_timeout_ms = 100


SLOW_SQL = "SELECT SUM((a.id * b.id * c.id) % 997) AS n FROM orders a CROSS JOIN orders b CROSS JOIN orders c"


@pytest.fixture
def parquet(tmp_path):
    path = tmp_path / "orders.parquet"
    pq.write_table(pa.table({"id": list(range(1000))}), path)
    return path


@pytest.fixture
def native_connections(monkeypatch):
    original = duckdb.connect
    connections = []

    class ObservedConnection:
        def __init__(self, conn):
            self.conn = conn
            self.started = threading.Event()
            self.closed = threading.Event()
            self.interrupts = 0
            connections.append(self)

        def execute(self, sql, *args):
            if "CROSS JOIN" in sql:
                self.started.set()
            return self.conn.execute(sql, *args)

        def interrupt(self):
            self.interrupts += 1
            return self.conn.interrupt()

        def close(self):
            self.conn.close()
            self.closed.set()

    monkeypatch.setattr(duckdb, "connect", lambda *a, **kw: ObservedConnection(original(*a, **kw)))
    return connections


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_deadline_interrupts_native_query_and_closes_owned_connection(parquet, native_connections):
    before = hashlib.sha256(parquet.read_bytes()).digest()
    started = time.monotonic()
    result = await DuckDBExecutor(Settings()).execute(SLOW_SQL, {"orders": str(parquet)})
    assert isinstance(result, ExecutionError)
    assert result.sql_state == "57014"
    assert time.monotonic() - started < 3
    assert native_connections[0].started.is_set()
    assert native_connections[0].interrupts > 0
    assert native_connections[0].closed.is_set()
    assert hashlib.sha256(parquet.read_bytes()).digest() == before


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_cancellation_interrupts_worker_before_propagating_and_other_request_succeeds(
    parquet, native_connections
):
    class LongSettings(Settings):
        default_statement_timeout_ms = 10000

    executor = DuckDBExecutor(LongSettings())
    slow = asyncio.create_task(executor.execute(SLOW_SQL, {"orders": str(parquet)}))
    while not native_connections or not native_connections[0].started.is_set():
        await asyncio.sleep(0.001)
    fast = asyncio.create_task(executor.execute("SELECT SUM(id) AS n FROM orders", {"orders": str(parquet)}))
    slow.cancel()
    with pytest.raises(asyncio.CancelledError):
        await slow
    assert native_connections[0].closed.is_set()
    assert native_connections[0].interrupts > 0
    result = await fast
    assert isinstance(result, ExecutionResult)
    assert result.rows == [{"n": 499500}]
    assert native_connections[1].interrupts == 0
    again = await executor.execute("SELECT 7 AS n", {})
    assert isinstance(again, ExecutionResult) and again.rows == [{"n": 7}]


@pytest.mark.parametrize("value", [0, -1, 1.5])
def test_statement_deadline_must_be_positive(value):
    with pytest.raises(ValueError):
        FlyquerySettings(default_statement_timeout_ms=value)


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_deadline_never_publishes_copy_on_write_and_removes_scratch(
    parquet, monkeypatch, native_connections
):
    from flyquery.core.services.execution import duckdb_executor

    paths = []
    original = duckdb_executor.tempfile.mkstemp

    def owned_temp(*args, **kwargs):
        fd, path = original(*args, **kwargs)
        paths.append(path)
        return fd, path

    monkeypatch.setattr(duckdb_executor.tempfile, "mkstemp", owned_temp)
    before = parquet.read_bytes()
    sql = "UPDATE orders SET id = (SELECT SUM((a.id * b.id * c.id) % 997) FROM orders a CROSS JOIN orders b CROSS JOIN orders c)"
    result = await DuckDBExecutor(Settings()).execute(sql, {"orders": str(parquet)}, {"orders": str(parquet)})
    assert isinstance(result, ExecutionError) and result.sql_state == "57014"
    assert native_connections[0].started.is_set() and native_connections[0].interrupts > 0
    assert parquet.read_bytes() == before
    assert paths and all(not duckdb_executor.os.path.exists(path) for path in paths)


@pytest.fixture(autouse=True)
def no_watchdog_survives_call():
    previous = set(threading.enumerate())
    yield
    assert not [
        t for t in threading.enumerate() if t not in previous and t.name == "flyquery-statement-deadline"
    ]


@pytest.mark.asyncio
async def test_expired_queued_attempt_never_opens_a_native_connection(monkeypatch, native_connections):
    executor = DuckDBExecutor(Settings())
    original = executor._controlled_sync

    def late_worker(*args):
        time.sleep(0.15)
        return original(*args)

    monkeypatch.setattr(executor, "_controlled_sync", late_worker)
    result = await executor.execute("SELECT 1", {})
    assert isinstance(result, ExecutionError) and result.sql_state == "57014"
    assert native_connections == []


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_cancelling_copy_on_write_cleans_scratch_and_preserves_snapshot(
    parquet, native_connections, monkeypatch
):
    from flyquery.core.services.execution import duckdb_executor

    paths = []
    original = duckdb_executor.tempfile.mkstemp

    def track_temp(*args, **kwargs):
        fd, path = original(*args, **kwargs)
        paths.append(path)
        return fd, path

    monkeypatch.setattr(duckdb_executor.tempfile, "mkstemp", track_temp)

    class LongSettings(Settings):
        default_statement_timeout_ms = 10000

    sql = "UPDATE orders SET id = (SELECT SUM((a.id * b.id * c.id) % 997) FROM orders a CROSS JOIN orders b CROSS JOIN orders c)"
    before = parquet.read_bytes()
    task = asyncio.create_task(
        DuckDBExecutor(LongSettings()).execute(sql, {"orders": str(parquet)}, {"orders": str(parquet)})
    )
    while not native_connections or not native_connections[0].started.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert native_connections[0].closed.is_set() and native_connections[0].interrupts > 0
    assert parquet.read_bytes() == before
    assert paths and all(not duckdb_executor.os.path.exists(path) for path in paths)


@pytest.mark.asyncio
async def test_large_integer_budget_does_not_overflow_native_watchdog(native_connections):
    settings = FlyquerySettings(default_statement_timeout_ms=10**400)
    result = await DuckDBExecutor(settings).execute("SELECT 7 AS n", {})
    assert isinstance(result, ExecutionResult) and result.rows == [{"n": 7}]
    assert native_connections[0].closed.is_set()


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_native_interrupt_failure_is_retained_and_retried(parquet, native_connections):
    executor = DuckDBExecutor(Settings())
    task = asyncio.create_task(executor.execute(SLOW_SQL, {"orders": str(parquet)}))
    while not native_connections or not native_connections[0].started.is_set():
        await asyncio.sleep(0.001)
    connection = native_connections[0]
    original = connection.interrupt
    attempted = 0

    def transient_failure():
        nonlocal attempted
        attempted += 1
        if attempted == 1:
            raise RuntimeError("synthetic native interruption failure")
        return original()

    connection.interrupt = transient_failure
    result = await task
    assert isinstance(result, ExecutionError) and result.sql_state == "57014"
    assert "native interruption failed: RuntimeError" in result.message
    assert attempted >= 2 and connection.closed.is_set()


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_cancellation_keeps_cleanup_failure_as_cause(parquet, native_connections):
    class LongSettings(Settings):
        default_statement_timeout_ms = 10000

    task = asyncio.create_task(DuckDBExecutor(LongSettings()).execute(SLOW_SQL, {"orders": str(parquet)}))
    while not native_connections or not native_connections[0].started.is_set():
        await asyncio.sleep(0.001)
    connection = native_connections[0]
    original = connection.close

    def close_with_failure():
        original()
        raise RuntimeError("synthetic post-close cleanup failure")

    connection.close = close_with_failure
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "post-close cleanup" in str(caught.value.__cause__)
    assert task.cancelled() and connection.closed.is_set()


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_cancelled_copy_on_write_unlinks_scratch_even_when_close_raises(
    parquet, native_connections, monkeypatch
):
    from pathlib import Path

    from flyquery.core.services.execution import duckdb_executor

    paths = []
    original_temp = duckdb_executor.tempfile.mkstemp

    def track_temp(*args, **kwargs):
        kwargs["dir"] = parquet.parent
        fd, path = original_temp(*args, **kwargs)
        paths.append(path)
        return fd, path

    monkeypatch.setattr(duckdb_executor.tempfile, "mkstemp", track_temp)

    class LongSettings(Settings):
        default_statement_timeout_ms = 10000

    sql = "UPDATE orders SET id = (SELECT SUM((a.id * b.id * c.id) % 997) FROM orders a CROSS JOIN orders b CROSS JOIN orders c)"
    before = parquet.read_bytes()
    task = asyncio.create_task(
        DuckDBExecutor(LongSettings()).execute(sql, {"orders": str(parquet)}, {"orders": str(parquet)})
    )
    while not native_connections or not native_connections[0].started.is_set():
        await asyncio.sleep(0.001)
    connection = native_connections[0]
    original_close = connection.close

    def close_with_failure():
        original_close()
        raise RuntimeError("synthetic COW post-close failure")

    connection.close = close_with_failure
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "COW post-close" in str(caught.value.__cause__)
        assert task.cancelled() and connection.closed.is_set()
        assert parquet.read_bytes() == before
        assert paths and all(not Path(path).exists() for path in paths)
    finally:
        # A failing RED run must not leave its own scratch fixture behind.
        for path in paths:
            Path(path).unlink(missing_ok=True)
