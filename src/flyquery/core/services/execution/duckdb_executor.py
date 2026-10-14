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

"""DuckDB in-process executor for flyquery query pipeline.

Opens a fresh DuckDB :memory: connection per request, ATTACHes parquet
files for all AST-referenced tables as VIEWs, runs the user SQL wrapped
in a LIMIT row_cap+1 query to detect overflow, and returns an
``ExecutionResult`` or ``ExecutionError``.

Design choices
--------------
- Fresh :memory: per call: no shared state, no connection pool needed.
- ``asyncio.to_thread``: DuckDB's Python API is synchronous; offload to a
  thread pool so the event loop stays unblocked.
- LIMIT row_cap+1: detect overflow without reading all rows into memory.
- SQL errors return ``ExecutionError``; deadline state ``57014`` is terminal.
  Unexpected cleanup failures propagate. Cancellation preserves its own
  exception with a cleanup failure chained as the cause.

DML on DERIVED tables (copy-on-write)
--------------------------------------
When ``execute()`` is called with a DML statement (INSERT/UPDATE/DELETE)
against a DERIVED table, the executor applies a copy-on-write strategy:

1. Read the current Parquet into a DuckDB temp table (``_cow_<name>``).
2. Create a mutable ``TABLE <name>`` from the temp data (so DML lands on it).
3. Execute the DML statement against the in-memory table.
4. Write the mutated table back to a **new** Parquet byte string via
   ``COPY <name> TO '<tempfile>' (FORMAT PARQUET)``.
5. Return the new Parquet bytes as ``DmlMutationResult`` so the caller
   (``SqlExecuteController``) can upload a new versioned snapshot and bump
   ``flyquery_tables.current_snapshot_id``.

The upstream scope guard ensures DML only reaches here when the token
carries ``flyquery.derived:write`` and all table_refs are DERIVED.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from dataclasses import dataclass

from flyquery.core.services.execution.ast_classifier import AstClassifier


@dataclass(frozen=True)
class ExecutionResult:
    """A successful SELECT query result."""

    rows: list[dict]
    columns: list[str]
    row_count: int
    truncated: bool


@dataclass(frozen=True)
class DmlMutationResult:
    """Result of a DML (INSERT/UPDATE/DELETE) on a DERIVED table.

    Copy-on-write: the caller must upload ``new_parquet_bytes`` as a
    new versioned snapshot and bump ``flyquery_tables.current_snapshot_id``.

    :param table_name: the DERIVED table name that was mutated
    :param rows_affected: approximate count of rows in the mutated table
    :param new_parquet_bytes: full Parquet content of the mutated table
    """

    table_name: str
    rows_affected: int
    new_parquet_bytes: bytes


@dataclass(frozen=True)
class ExecutionError:
    """A failed query execution."""

    message: str
    sql_state: str | None = None


class _ExecutionStopped(Exception):
    pass


class _ExecutionControl:
    """Own one connection; interrupt repeatedly until its worker has stopped.

    An interrupt can arrive between setup, SQL, and export statements. Repeat
    until cleanup finishes so a statement started in that gap is also stopped.
    Monotonic checkpoints prevent a late successful result from being published.
    """

    def __init__(self, timeout_ms: int) -> None:
        self._deadline_ns = time.monotonic_ns() + timeout_ms * 1_000_000
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._wake = threading.Event()
        self._connection = None
        self._cancelled = False
        self._interrupt_error: Exception | None = None
        self._watcher = threading.Thread(target=self._watch, name="flyquery-statement-deadline", daemon=True)
        self._watcher.start()

    def _interrupt(self) -> None:
        if self._connection is not None:
            try:
                self._connection.interrupt()
            except Exception as exc:
                # Retain the failure and retry; a watchdog must not die silently.
                self._interrupt_error = exc

    def _watch(self) -> None:
        while not self._finished.is_set():
            remaining = self._deadline_ns - time.monotonic_ns()
            if not self._cancelled and remaining > 0:
                # Convert only a bounded chunk; even huge valid integer budgets
                # must not overflow threading.TIMEOUT_MAX or float conversion.
                self._wake.wait(min(remaining, 60_000_000_000) / 1_000_000_000)
                continue
            with self._lock:
                self._interrupt()
            self._finished.wait(0.01)

    def bind(self, connection) -> None:
        with self._lock:
            self._connection = connection
        self.check()

    def check(self) -> None:
        if self._cancelled or time.monotonic_ns() >= self._deadline_ns:
            raise _ExecutionStopped

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._interrupt()
        # Wake the watchdog so cancellation is re-applied between statements.
        self._wake.set()

    def close(self, connection) -> None:
        # Close and interrupt must never race on a detached native connection.
        with self._lock:
            if self._connection is connection:
                self._connection = None
            connection.close()

    def finish(self) -> None:
        self._finished.set()
        self._wake.set()
        self._watcher.join()

    def error(self) -> ExecutionError:
        message = "Statement deadline exceeded"
        if self._interrupt_error is not None:
            message += f"; native interruption failed: {type(self._interrupt_error).__name__}"
        return ExecutionError(message=message, sql_state="57014")


class DuckDBExecutor:
    """Executes SQL against DuckDB with parquet-backed views.

    SELECT
    ~~~~~~
    Each call opens a fresh ``:memory:`` DuckDB connection, creates a VIEW
    for every entry in ``attached_tables``, runs the SQL wrapped in a
    ``SELECT * FROM (...) LIMIT row_cap+1`` envelope, then closes the
    connection.

    DML on DERIVED tables
    ~~~~~~~~~~~~~~~~~~~~~
    When ``derived_tables`` is non-empty (mapping: name → current parquet path),
    and the SQL is a DML statement, the executor applies copy-on-write:

    1. Read the existing Parquet into ``CREATE TABLE _cow_<name> AS SELECT ...``.
    2. Run ``INSERT/UPDATE/DELETE`` against the in-memory table (renamed to ``<name>``).
    3. Export the mutated table to a temp Parquet file via ``COPY ... TO ... (FORMAT PARQUET)``.
    4. Return a :class:`DmlMutationResult` with the new Parquet bytes.

    :param settings: :class:`FlyquerySettings` — reads ``duckdb_memory_limit``,
        ``default_row_cap`` and the positive ``default_statement_timeout_ms``.
        Each call has a cooperative native deadline, not an operating-system budget.
    """

    def __init__(self, settings) -> None:
        self._memory_limit = settings.duckdb_memory_limit
        self._row_cap = settings.default_row_cap
        self._timeout_ms = settings.default_statement_timeout_ms
        if self._timeout_ms <= 0:
            raise ValueError("default_statement_timeout_ms must be positive")

    async def execute(
        self,
        sql: str,
        attached_tables: dict[str, str],
        derived_tables: dict[str, str] | None = None,
    ) -> ExecutionResult | DmlMutationResult | ExecutionError:
        """Run ``sql`` asynchronously against the provided parquet views.

        :param sql: SQL statement to execute
        :param attached_tables: mapping of unqualified table name → absolute parquet path
            (used as read-only VIEWs for SELECT; source data for DML copy-on-write)
        :param derived_tables: when provided, these table names are treated as mutable
            DERIVED tables; DML runs copy-on-write and returns :class:`DmlMutationResult`
        :return: :class:`ExecutionResult` for SELECT, :class:`DmlMutationResult` for DML,
            or :class:`ExecutionError` on failure
        """
        control = _ExecutionControl(self._timeout_ms)
        worker = asyncio.create_task(
            asyncio.to_thread(
                self._controlled_sync, sql, dict(attached_tables), dict(derived_tables or {}), control
            )
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError as cancelled:
            control.cancel()
            # Cancellation must not abandon the native worker or COW scratch file.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    control.cancel()
                except Exception as cleanup_failure:
                    raise cancelled from cleanup_failure
            try:
                worker.result()
            except Exception as cleanup_failure:
                raise cancelled from cleanup_failure
            raise

    def _controlled_sync(self, sql, attached_tables, derived_tables, control):
        try:
            control.check()
            result = self._sync(sql, attached_tables, derived_tables, control)
            control.check()
            return result
        except _ExecutionStopped:
            return control.error()
        finally:
            control.finish()

    def _sync(
        self,
        sql: str,
        attached_tables: dict[str, str],
        derived_tables: dict[str, str],
        control: _ExecutionControl,
    ) -> ExecutionResult | DmlMutationResult | ExecutionError:
        """Synchronous execution body run in a thread pool worker."""
        classification = AstClassifier().classify(sql)
        if any(attached_tables.get(name) != path for name, path in derived_tables.items()):
            return ExecutionError(message="DERIVED snapshot is not registered for this execution")
        # Actor scopes remain upstream; this boundary confines SQL to the supplied registered snapshots.
        if (
            not classification.single_statement
            or classification.classification not in {"SELECT", "INSERT", "UPDATE", "DELETE"}
            or classification.unsupported_sql
        ):
            return ExecutionError(message="unsupported SQL statement, function, or table source")
        if any(name not in attached_tables for name in classification.table_refs):
            return ExecutionError(message="SQL source is not a registered table")
        if classification.classification != "SELECT" and any(
            name not in derived_tables for name in classification.table_refs
        ):
            return ExecutionError(message="DML source is not a registered DERIVED table")
        try:
            import duckdb
        except ImportError as exc:
            return ExecutionError(message=f"duckdb not installed: {exc}")

        if classification.classification in {"INSERT", "UPDATE", "DELETE"}:
            if len(derived_tables) != 1:
                return ExecutionError(message="DML requires exactly one registered DERIVED target")
            return self._sync_dml(sql, attached_tables, derived_tables, duckdb, control)
        return self._sync_select(sql, attached_tables, duckdb, control)

    def _connection(self, duckdb, paths: list[str], control: _ExecutionControl):
        conn = duckdb.connect(
            ":memory:", config={"autoload_known_extensions": False, "autoinstall_known_extensions": False}
        )
        try:
            control.bind(conn)
            # DuckDB freezes allowed_paths when external access is disabled, so finish the exact allowlist first.
            conn.execute("SET allowed_paths = ?", [sorted(set(paths))])
            conn.execute("SET enable_external_access=false")
            conn.execute("SET memory_limit = ?", [self._memory_limit])
            conn.execute("SET threads=2")
            conn.execute("SET lock_configuration=true")
            return conn
        except Exception:
            control.close(conn)
            raise

    @staticmethod
    def _identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @staticmethod
    def _literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _sync_select(
        self,
        sql: str,
        attached_tables: dict[str, str],
        duckdb,  # noqa: ANN001
        control: _ExecutionControl,
    ) -> ExecutionResult | ExecutionError:
        """Execute a SELECT and return rows."""
        conn = None
        try:
            conn = self._connection(duckdb, list(attached_tables.values()), control)

            # Create a VIEW for each parquet-backed table.
            for name, parquet_path in attached_tables.items():
                conn.execute(
                    f"CREATE VIEW {self._identifier(name)} AS SELECT * FROM read_parquet({self._literal(parquet_path)})"
                )

            # Wrap in LIMIT row_cap+1 to detect truncation.
            wrapped = f"SELECT * FROM ({sql.rstrip(';')}) AS q LIMIT {self._row_cap + 1}"
            control.check()
            cursor = conn.execute(wrapped)
            cols = [d[0] for d in cursor.description]
            rows = cursor.fetchall()

            truncated = len(rows) > self._row_cap
            if truncated:
                rows = rows[: self._row_cap]

            control.check()
            return ExecutionResult(
                rows=[dict(zip(cols, r, strict=False)) for r in rows],
                columns=cols,
                row_count=len(rows),
                truncated=truncated,
            )
        except Exception as exc:  # noqa: BLE001
            control.check()
            return ExecutionError(message=str(exc))
        finally:
            if conn is not None:
                control.close(conn)

    def _sync_dml(
        self,
        sql: str,
        attached_tables: dict[str, str],
        derived_tables: dict[str, str],
        duckdb,  # noqa: ANN001
        control: _ExecutionControl,
    ) -> DmlMutationResult | ExecutionError:
        """Execute DML on DERIVED tables using copy-on-write.

        Steps:
        1. Read existing Parquet into a mutable DuckDB TABLE.
        2. Execute the DML statement.
        3. Export the mutated table back to a temp Parquet.
        4. Return new Parquet bytes via DmlMutationResult.

        Only the first DERIVED table name found in ``derived_tables`` is
        treated as the mutation target; all other attached_tables are
        available as read-only VIEWs.
        """
        # For now, support exactly one DERIVED target per DML statement.
        target_name = next(iter(derived_tables))
        current_parquet_path = derived_tables[target_name]

        conn = None
        tmp_path: str | None = None

        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".parquet")
            os.close(fd)
            conn = self._connection(
                duckdb, [*attached_tables.values(), current_parquet_path, tmp_path], control
            )

            # Provide read-only views for all non-target tables.
            for name, path in attached_tables.items():
                if name == target_name:
                    continue
                conn.execute(
                    f"CREATE VIEW {self._identifier(name)} AS SELECT * FROM read_parquet({self._literal(path)})"
                )

            # Load the DERIVED table as a mutable TABLE (not a VIEW).
            conn.execute(
                f"CREATE TABLE {self._identifier(target_name)} AS SELECT * FROM read_parquet({self._literal(current_parquet_path)})"
            )

            # Execute the DML statement.
            control.check()
            conn.execute(sql.rstrip(";"))

            # Count rows in the mutated table.
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM {self._identifier(target_name)}")
            rows_affected: int = count_cursor.fetchone()[0]  # type: ignore[index]

            # Export the mutated table to a temp Parquet file.
            # The destination is a new owned scratch file, so no extra atomic-replacement path is needed.
            conn.execute(
                f"COPY {self._identifier(target_name)} TO {self._literal(tmp_path)} (FORMAT PARQUET, COMPRESSION SNAPPY, USE_TMP_FILE false)"
            )

            with open(tmp_path, "rb") as fh:
                new_parquet_bytes = fh.read()

            control.check()
            return DmlMutationResult(
                table_name=target_name,
                rows_affected=rows_affected,
                new_parquet_bytes=new_parquet_bytes,
            )

        except Exception as exc:  # noqa: BLE001
            control.check()
            return ExecutionError(message=str(exc))
        finally:
            if conn is not None:
                control.close(conn)
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
