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

"""Stage 5 — profile.

For each active COLUMN in the snapshot, compute via a single DuckDB query:
  - null_fraction
  - approx_count_distinct (via approx_count_distinct())
  - min / max (numeric + temporal columns only)
  - full distinct value set, capped at 100 (low-cardinality only:
    distinct_estimate ≤ 100) -- surfaced into the NL→SQL prompts so
    filter/CASE literals are copied verbatim from real values

Skips the whole column if the snapshot's n_rows_actual exceeds
FLYQUERY_PROFILE_ROW_THRESHOLD (default 10M rows).

Persists to flyquery_schema_objects.profile_json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# Generic, language-agnostic markers for pre-aggregated subtotal / rollup
# values that can coexist with detail rows in a categorical dimension.
# This is a CURATED set of common total markers (English + Spanish), NOT
# tied to any specific dataset/column name. A value matching this is flagged
# as a likely subtotal so the query prompt can avoid mixing subtotal + detail
# rows (summing across all rows double-counts; filtering to it drops detail).
# Token boundary is a string edge or a non-alphanumeric separator (space,
# underscore, hyphen, etc.) so labels like "Total_Department" are caught while
# words that merely embed a marker (e.g. "allocation", "North America") are not.
_SUBTOTAL_MARKERS = (
    r"sub[ _-]?total|grand[ _-]?total|gran[ _-]?total|totals?|totales|"
    r"all|todos|todas|suma|consolidad[oa]s?|overall"
)
# A value is flagged ONLY when it is essentially a total *marker by itself*
# (the whole value is the marker), OR a machine-generated pivot label where the
# marker is joined to another token by ``_``/``-`` (e.g. ``Total_Department``,
# ``Department-Total``). This deliberately does NOT match space-separated
# natural-language line items like ``Total Revenue`` / ``Total Nexium`` -- those
# are legitimate measure values the agent must keep, not pre-aggregated rows.
_SUBTOTAL_EXACT = re.compile(rf"^(?:{_SUBTOTAL_MARKERS})$", re.IGNORECASE)
_SUBTOTAL_JOINED = re.compile(
    rf"(?:^|[_-])(?:{_SUBTOTAL_MARKERS})(?=[_-])|(?<=[_-])(?:{_SUBTOTAL_MARKERS})$",
    re.IGNORECASE,
)
_BLANK_PLACEHOLDERS = {"(blank)", "(empty)", "(null)", "(en blanco)", "(vacío)", "(vacio)"}


def _looks_like_subtotal(value: str) -> bool:
    """Heuristic: True only for unambiguous total/rollup pivot labels.

    Conservative + side-effect free: matches a standalone total marker, a
    separator-joined pivot label (``Total_Department``), or a blank-ish
    placeholder -- but NOT space-separated natural-language values such as
    ``Total Revenue``. Consumed downstream as a prompt hint only.
    """
    if value is None:
        return False
    stripped = value.strip()
    if stripped == "" or stripped.lower() in _BLANK_PLACEHOLDERS:
        return True
    return bool(_SUBTOTAL_EXACT.match(stripped) or _SUBTOTAL_JOINED.search(stripped))


# Data-type compatibility groups
_NUMERIC_TYPES = frozenset(
    {
        "integer",
        "int",
        "int4",
        "int8",
        "bigint",
        "smallint",
        "tinyint",
        "float",
        "double",
        "real",
        "decimal",
        "numeric",
        "hugeint",
        "ubigint",
    }
)
_TEMPORAL_TYPES = frozenset(
    {
        "date",
        "timestamp",
        "timestamp with time zone",
        "timestamptz",
        "time",
        "interval",
    }
)


def _is_numeric(data_type: str) -> bool:
    return data_type.lower().split("(")[0].strip() in _NUMERIC_TYPES


def _is_temporal(data_type: str) -> bool:
    return data_type.lower().split("(")[0].strip() in _TEMPORAL_TYPES


async def run_profile(
    *,
    tenant_id: str,
    snapshot_id: uuid.UUID,
    parquet_key: str,
    n_rows_actual: int,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Any,  # FlyquerySettings
) -> dict[str, Any]:
    """Execute Stage 5: profile."""
    if n_rows_actual > settings.profile_row_threshold:
        logger.info(
            "stage=profile skip snapshot_id=%s n_rows=%d threshold=%d",
            snapshot_id,
            n_rows_actual,
            settings.profile_row_threshold,
        )
        return {"snapshot_id": str(snapshot_id), "skipped": True, "reason": "row_threshold"}

    columns = await _load_columns(tenant_id, snapshot_id, session_factory)
    profiled = 0

    # Collect profiles first so a second pass can detect self-referencing
    # hierarchy columns (manager->report) before persisting.
    computed: dict[str, tuple[uuid.UUID, str, dict[str, Any]]] = {}
    for col in columns:
        col_id: uuid.UUID = col["id"]
        col_name: str = col["qualified_name"].rsplit(".", 1)[-1]
        data_type: str = col["data_type"] or ""

        profile = await asyncio.to_thread(
            _profile_column_sync, parquet_key, col_name, data_type, n_rows_actual
        )
        if profile is not None:
            computed[col_name] = (col_id, data_type, profile)

    # Self-reference detection: annotate columns whose values are mostly
    # contained in a higher-cardinality "entity" column of the same table
    # (e.g. a manager/owner column whose values are people from the employee
    # column). Purely structural (value containment) -- no name/vocabulary
    # heuristics -- so it generalises to any self-referencing hierarchy.
    try:
        refs = await asyncio.to_thread(_detect_self_references, parquet_key, computed, n_rows_actual)
        for ref_col, entity_col in refs.items():
            computed[ref_col][2]["references_column"] = entity_col
    except Exception as exc:  # noqa: BLE001 -- detection is best-effort
        logger.warning("stage=profile self-reference detection failed snapshot=%s err=%s", snapshot_id, exc)

    for col_id, _dt, profile in computed.values():
        await _persist_profile(col_id, profile, tenant_id, session_factory)
        profiled += 1

    logger.info(
        "stage=profile snapshot_id=%s columns_profiled=%d",
        snapshot_id,
        profiled,
    )
    return {"snapshot_id": str(snapshot_id), "columns_profiled": profiled}


def _detect_self_references(
    parquet_key: str,
    computed: dict[str, tuple[uuid.UUID, str, dict[str, Any]]],
    n_rows: int,
) -> dict[str, str]:
    """Find columns that reference a higher-cardinality entity column.

    A reference (foreign-key-like, including a self-referencing org
    hierarchy) is detected purely structurally: a text column ``R`` whose
    distinct values are mostly a SUBSET of another, higher-cardinality text
    column ``E`` in the same table. ``R`` must be on the many-to-one side
    (meaningfully fewer distinct values than ``E``) so two near-duplicate
    name columns are not flagged as a hierarchy.

    Returns ``{ref_col: entity_col}``. No names/keywords are inspected --
    this generalises to any dataset's manager/owner/parent columns.
    """
    import duckdb

    text_cols = {
        name: prof["distinct_estimate"]
        for name, (_cid, dt, prof) in computed.items()
        if not _is_numeric(dt) and not _is_temporal(dt) and prof.get("distinct_estimate")
    }
    if len(text_cols) < 2:
        return {}
    # Entity columns: high-cardinality name/id columns (the "one" side).
    entity_cols = [c for c, d in text_cols.items() if d >= max(8, 0.2 * n_rows)]
    if not entity_cols:
        return {}

    refs: dict[str, str] = {}
    con = duckdb.connect()
    try:
        for ref_col, d_ref in text_cols.items():
            if d_ref < 3:
                continue
            for ent_col in entity_cols:
                if ent_col == ref_col or d_ref > 0.7 * text_cols[ent_col]:
                    continue  # ref must be the many-to-one (smaller) side
                s_ref = '"' + ref_col.replace('"', '""') + '"'
                s_ent = '"' + ent_col.replace('"', '""') + '"'
                try:
                    row = con.execute(
                        f"SELECT count(DISTINCT {s_ref}), "
                        f"count(DISTINCT CASE WHEN {s_ref} IN "
                        f"(SELECT {s_ent} FROM read_parquet(?)) THEN {s_ref} END) "
                        f"FROM read_parquet(?) WHERE {s_ref} IS NOT NULL AND {s_ref} <> ''",
                        [parquet_key, parquet_key],
                    ).fetchone()
                except Exception:  # noqa: BLE001 -- skip uncomparable columns
                    continue
                if row and row[0] and (row[1] / row[0]) >= 0.6:
                    # Discriminate a genuine cross-reference (the value is a
                    # DIFFERENT entity than the row's own -- a manager, owner,
                    # parent) from a row-wise DUPLICATE of the entity column (the
                    # SAME entity copied, e.g. a second name column). On a
                    # duplicate, ref == entity on most rows; on a real reference
                    # they differ. Skip duplicates.
                    eq = con.execute(
                        f"SELECT avg(CASE WHEN {s_ref} = {s_ent} THEN 1.0 ELSE 0.0 END) "
                        f"FROM read_parquet(?) WHERE {s_ref} IS NOT NULL AND {s_ent} IS NOT NULL",
                        [parquet_key],
                    ).fetchone()
                    if eq and eq[0] is not None and eq[0] > 0.5:
                        continue  # row-wise copy -> not a hierarchy reference
                    refs[ref_col] = ent_col
                    break
    finally:
        con.close()
    return refs


# ---------------------------------------------------------------------------
# DuckDB profiling (runs in thread)
# ---------------------------------------------------------------------------


def _profile_column_sync(
    parquet_key: str,
    col_name: str,
    data_type: str,
    n_rows_actual: int,
) -> dict[str, Any] | None:
    """Run a single DuckDB query to compute profile metrics for one column."""
    try:
        import duckdb

        conn = duckdb.connect()
        try:
            safe_col = '"' + col_name.replace('"', '""') + '"'

            # Base query: null_fraction + approx_count_distinct
            base_rows = conn.execute(
                f"SELECT "
                f"  count(*) AS total_rows, "
                f"  sum(CASE WHEN {safe_col} IS NULL THEN 1 ELSE 0 END) AS null_count, "
                f"  approx_count_distinct({safe_col}) AS distinct_estimate "
                f"FROM read_parquet(?)",
                [parquet_key],
            ).fetchone()

            if base_rows is None:
                return None

            total, null_count, distinct_estimate = base_rows
            null_fraction = (null_count / total) if total > 0 else 0.0

            profile: dict[str, Any] = {
                "null_fraction": null_fraction,
                "distinct_estimate": distinct_estimate,
                "n_rows": total,
            }

            # min / max for numeric + temporal
            if _is_numeric(data_type) or _is_temporal(data_type):
                minmax = conn.execute(
                    f"SELECT min({safe_col}), max({safe_col}) FROM read_parquet(?)",
                    [parquet_key],
                ).fetchone()
                if minmax:
                    col_min, col_max = minmax
                    profile["min"] = str(col_min) if col_min is not None else None
                    profile["max"] = str(col_max) if col_max is not None else None

            # Top values for low-cardinality columns (distinct ≤ 100).
            # We store the FULL distinct set (capped at 100) rather than
            # just the top 5: the NL→SQL grounding/generation agents copy
            # WHERE/CASE literals verbatim from these values, so a
            # truncated list silently breaks any filter on a value that
            # fell outside the top 5 (e.g. the P&L-line members of an
            # operating-profit formula, or a brand outside the 5 biggest).
            if distinct_estimate <= 100 and distinct_estimate > 0:
                top_rows = conn.execute(
                    f"SELECT {safe_col}, count(*) AS cnt "
                    f"FROM read_parquet(?) "
                    f"WHERE {safe_col} IS NOT NULL "
                    f"GROUP BY {safe_col} "
                    f"ORDER BY cnt DESC "
                    f"LIMIT 100",
                    [parquet_key],
                ).fetchall()
                profile["top_values"] = [{"value": str(r[0]), "count": r[1]} for r in top_rows]

                # Subtotal detection (heuristic hint, cheap + side-effect free).
                # For a low-cardinality TEXT dimension, flag values whose text
                # matches a generic total/aggregate marker (en/es) or a blank
                # placeholder. Such values are likely pre-aggregated rollup rows
                # coexisting with detail rows; the query prompt consumes this to
                # avoid mixing subtotal + detail (summing double-counts; filtering
                # to the subtotal drops detail). No measure join is available
                # here, so this stays purely structural/textual.
                if not _is_numeric(data_type) and not _is_temporal(data_type):
                    subtotal_values = [str(r[0]) for r in top_rows if _looks_like_subtotal(str(r[0]))]
                    if subtotal_values:
                        profile["subtotal_values"] = subtotal_values

            return profile

        finally:
            conn.close()

    except Exception as exc:
        logger.warning("stage=profile column_profile failed col=%s: %s", col_name, exc)
        return None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_columns(
    tenant_id: str,
    snapshot_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                """
                SELECT id, qualified_name, data_type
                FROM flyquery_schema_objects
                WHERE snapshot_id = :sid
                  AND tenant_id = :tenant
                  AND kind = 'COLUMN'
                  AND is_active = true
                ORDER BY qualified_name
                """
            ),
            {"sid": snapshot_id, "tenant": tenant_id},
        )
        return [dict(r) for r in result.mappings().all()]


async def _persist_profile(
    col_id: uuid.UUID,
    profile: dict[str, Any],
    tenant_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s, s.begin():
        await s.execute(
            sa.text(
                """
                UPDATE flyquery_schema_objects
                SET profile_json = CAST(:profile AS jsonb)
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {
                "id": col_id,
                "tenant": tenant_id,
                "profile": json.dumps(profile),
            },
        )
