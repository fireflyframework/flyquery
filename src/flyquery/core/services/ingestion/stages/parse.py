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

"""Stage 2 — parse: decompress → reader → enumerate tables → materialise Parquet.

For each ProposedTable:
- Materialise to Parquet under flyquery/{tenant}/{ws}/{ds}/tables/{table_id}/v{n}.parquet
- Insert flyquery_tables row (or look up existing row for re-upload)
- Return list of ParsedTable instances
"""

from __future__ import annotations

import logging
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flyquery.core.agents.column_name_proposer_agent import (
    build_column_name_proposer_agent,
    needs_proposal,
    render_proposal_prompt,
)
from flyquery.core.services.ingestion.compression import decompress_to_temp
from flyquery.core.services.ingestion.reader import (
    ColumnSchema,
    MaterialiseResult,
    TableExtractionRules,
)
from flyquery.core.services.ingestion.reader_factory import get_reader
from flyquery.core.services.storage.object_store import ObjectStore

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _sanitise_name(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name).strip("_") or "table"


def _period_name_from_header(header: str | None) -> str | None:
    """Deterministic column name for a header that IS a calendar period.

    ``'2024'`` / ``'FY2024'`` / ``'2024f'`` -> ``year_2024``;
    ``'2024-12-31'`` / ``'31/12/2024'`` -> ``period_2024_12_31``.
    Returns None for anything that is not clearly a year/date header (e.g.
    ``'Operating revenue'``), so only genuine period columns are stabilised.
    Generic — recognises the period from the source's own header, no domain rule.
    """
    if not header:
        return None
    s = str(header).strip()
    if not s or len(s) > 40:
        return None
    for pat, idx in (
        (r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", (1, 2, 3)),
        (r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", (3, 2, 1)),
    ):
        m = re.match(pat, s)
        if m:
            y, mo, d = int(m.group(idx[0])), int(m.group(idx[1])), int(m.group(idx[2]))
            if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                return f"period_{y}_{mo:02d}_{d:02d}"
    m = re.match(r"(?i)^(?:fy[\s_]*)?(\d{4})f?$", s)
    if m:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return f"year_{y}"
    return None


def _apply_deterministic_period_names(originals: list[str], proposed: list[str]) -> list[str]:
    """Override the LLM proposer for columns whose ORIGINAL header is a year/date,
    so period columns are named stably + correctly across re-ingests (round-2)."""
    out = list(proposed)
    changed = False
    for i, orig in enumerate(originals):
        nm = _period_name_from_header(orig)
        if nm and out[i] != nm:
            out[i] = nm
            changed = True
    if changed:
        out = _dedupe_names(out, fallback_prefix="period")
    return out


def _sanitise_proposed_name(name: str) -> str:
    """Best-effort enforcement of snake_case identifier rules on agent output."""
    cleaned = _SAFE_NAME_RE.sub("_", name).strip("_").lower()
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = "c_" + cleaned
    return cleaned[:50]


def _dedupe_names(names: list[str], fallback_prefix: str = "col") -> list[str]:
    """Ensure all names are unique by suffixing duplicates with _2, _3, ..."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for n in names:
        base = n or fallback_prefix
        if base not in seen:
            seen[base] = 1
            out.append(base)
        else:
            seen[base] += 1
            out.append(f"{base}_{seen[base]}")
    return out


async def _rename_parquet_columns(
    *,
    parquet_path: str,
    current_columns: list[str],
    proposed_columns: list[str],
) -> None:
    """Rewrite ``parquet_path`` in place with the columns renamed.

    Uses DuckDB's ``COPY (SELECT col0 AS new0, col1 AS new1, ...) TO file``
    so the type information from the materialise step is preserved.
    """
    import asyncio

    import duckdb

    def _sync() -> None:
        conn = duckdb.connect()
        try:
            select_clauses = []
            for old, new in zip(current_columns, proposed_columns, strict=True):
                select_clauses.append(f'"{old}" AS "{new}"')
            sel = ", ".join(select_clauses)
            tmp_path = parquet_path + ".rename.tmp"
            src = parquet_path.replace("'", "''")
            tgt = tmp_path.replace("'", "''")
            conn.execute(
                f"COPY (SELECT {sel} FROM read_parquet('{src}')) "
                f"TO '{tgt}' (FORMAT PARQUET, COMPRESSION 'snappy')"
            )
            Path(tmp_path).replace(parquet_path)
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def _read_parquet_sample(parquet_path: str, n_rows: int = 5) -> tuple[list[str], list[list[Any]]]:
    """Return (col_names, per-column sample values list).

    ``per_column`` is shaped as a list-of-lists, aligned with ``col_names``;
    each inner list has up to ``n_rows`` cell values pulled from the head
    of the Parquet.
    """
    import asyncio

    import duckdb

    def _sync() -> tuple[list[str], list[list[Any]]]:
        conn = duckdb.connect()
        try:
            src = parquet_path.replace("'", "''")
            rows = conn.execute(f"SELECT * FROM read_parquet('{src}') LIMIT {int(n_rows)}").fetchall()
            cols = [d[0] for d in conn.description]
            per_col: list[list[Any]] = [[] for _ in cols]
            for r in rows:
                for ci, val in enumerate(r):
                    per_col[ci].append(val)
            return cols, per_col
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def _propose_meaningful_column_names(
    *,
    section_label: str,
    mat_result: MaterialiseResult,
    parquet_path: str,
    settings: Any,
    logger_: logging.Logger,
) -> MaterialiseResult:
    """Detect synthetic ``columnNN`` names, propose better ones, rewrite Parquet.

    Returns the updated ``MaterialiseResult`` (column names changed; types
    + nullability + positions preserved). When the agent or its API key
    is unavailable, falls back to ``<section>_col_<n>`` so the names are
    at least scoped to the section.
    """
    current_names = [c.name for c in mat_result.columns]

    # Deterministically clean year/date headers FIRST -- before the
    # needs_proposal gate, which skips columns that already look "meaningful"
    # (a date column does). This turns '2024-12-31' -> period_2024_12_31 and
    # '2024' -> year_2024 stably across re-ingests, and renames the Parquet so
    # the stored column matches.
    period_named = _apply_deterministic_period_names(current_names, list(current_names))
    if period_named != current_names:
        await _rename_parquet_columns(
            parquet_path=parquet_path,
            current_columns=current_names,
            proposed_columns=period_named,
        )
        mat_result = _rebuild_mat_result(mat_result, period_named)
        current_names = period_named

    if not needs_proposal(current_names):
        return mat_result

    sample_cols, sample_values = await _read_parquet_sample(parquet_path, n_rows=5)
    if sample_cols != current_names:
        # Defensive -- if the Parquet header drifted, skip rename.
        return mat_result

    # Section-prefixed fallback name set. Used both as the "no API key"
    # path and as the safety net if the agent returns a malformed list.
    section_prefix = _sanitise_name(section_label).lower() or "col"
    section_prefix = section_prefix[:30]
    fallback = _dedupe_names([f"{section_prefix}_col_{i}" for i in range(len(current_names))])

    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger_.info(
            "stage=parse rename_skipped reason=no_api_key fallback_prefix=%s",
            section_prefix,
        )
        if fallback == current_names:
            return mat_result
        # Rewrite the physical Parquet so its column names match the
        # section-prefixed fallback we record in the MaterialiseResult --
        # otherwise the persisted schema_objects names diverge from the
        # Parquet header and downstream DuckDB stages hit Binder Errors.
        await _rename_parquet_columns(
            parquet_path=parquet_path,
            current_columns=current_names,
            proposed_columns=fallback,
        )
        return _rebuild_mat_result(mat_result, fallback)

    try:
        agent = build_column_name_proposer_agent(settings)
        prompt = render_proposal_prompt(
            section_label=section_label,
            current_names=current_names,
            sample_values=sample_values,
        )
        run = await agent.run(prompt)
        proposed_obj = getattr(run, "output", run)
        proposed = list(getattr(proposed_obj, "proposed_names", []) or [])
        if len(proposed) != len(current_names):
            logger_.warning(
                "stage=parse rename_misaligned expected=%d got=%d fallback=section_prefix",
                len(current_names),
                len(proposed),
            )
            proposed = fallback
        else:
            proposed = [_sanitise_proposed_name(p) for p in proposed]
            # Replace empties with section-prefixed fallback at the same index.
            proposed = [p if p else fallback[i] for i, p in enumerate(proposed)]
            proposed = _dedupe_names(proposed, fallback_prefix=section_prefix)
    except Exception as exc:  # noqa: BLE001
        logger_.warning(
            "stage=parse rename_agent_failed err=%s -- using section-prefixed fallback",
            exc,
        )
        proposed = fallback

    # Safety net: clean any remaining year/date names the proposer produced.
    proposed = _apply_deterministic_period_names(current_names, proposed)

    if proposed == current_names:
        return mat_result

    await _rename_parquet_columns(
        parquet_path=parquet_path,
        current_columns=current_names,
        proposed_columns=proposed,
    )
    logger_.info(
        "stage=parse renamed_columns section=%s before=%s after=%s",
        section_label,
        current_names[:6],
        proposed[:6],
    )
    return _rebuild_mat_result(mat_result, proposed)


def _rebuild_mat_result(
    mat_result: MaterialiseResult,
    new_names: list[str],
) -> MaterialiseResult:
    """Return a new MaterialiseResult with column names swapped (types kept)."""
    return MaterialiseResult(
        target_parquet_key=mat_result.target_parquet_key,
        parquet_byte_size=mat_result.parquet_byte_size,
        n_rows_actual=mat_result.n_rows_actual,
        columns=tuple(
            ColumnSchema(
                name=new_names[i],
                data_type=c.data_type,
                is_nullable=c.is_nullable,
                position=c.position,
                # remember the original header iff it actually changed
                original_name=(c.name if new_names[i] != c.name else None),
            )
            for i, c in enumerate(mat_result.columns)
        ),
    )


@dataclass
class ParsedTable:
    table_id: uuid.UUID
    name: str
    qualified_name: str
    sheet_or_json_path: str | None
    parquet_key: str
    result: MaterialiseResult
    # Local FS path to the same Parquet that was uploaded under ``parquet_key``.
    # Kept alive through the synchronous downstream stages (sample, profile,
    # describe) so DuckDB can ``read_parquet(local_path)`` directly instead of
    # the object-store key (which is opaque to DuckDB outside the LocalFs
    # adapter). The owning ``IngestService`` cleans up this path after the
    # ``publish`` stage; on failure it gets cleaned up by Python's tempfile
    # mechanism (the file lives under ``tempfile.gettempdir()``).
    local_parquet_path: str | None = None


async def run_parse(
    *,
    tenant_id: str,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    file_id: uuid.UUID,
    local_temp_path: str,
    file_format: str,
    compression: str,
    object_store: ObjectStore,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Any,  # FlyquerySettings
    # When re-uploading into an existing table slot, pass the existing table_id.
    # When None, new table rows are inserted.
    existing_table_id: uuid.UUID | None = None,
    # When re-uploading into a specific section of a multi-section workbook
    # (XLSX/ODS), pass the target table's ``sheet_or_json_path`` and/or
    # sanitised ``name`` so the parser can pick the matching section instead
    # of defaulting to the first one. ``sheet_or_json_path`` is tried first
    # (exact match), then ``target_name`` (sanitised-name match — robust
    # across re-uploads where the section row range shifted slightly).
    # Falls back to the first proposed table when neither matches.
    target_sheet_or_json_path: str | None = None,
    target_name: str | None = None,
    dataset_name: str = "dataset",
    workspace_locale: str = "en-US",
    original_filename: str | None = None,
) -> list[ParsedTable]:
    """Execute Stage 2: parse."""
    # 1. Decompress if needed
    if compression != "none":
        decompressed_path = await decompress_to_temp(local_temp_path, compression)
    else:
        decompressed_path = local_temp_path
    cleanup_decompressed = decompressed_path != local_temp_path

    try:
        reader = get_reader(file_format=file_format, compression="none")
        rules = TableExtractionRules()
        proposed = await reader.enumerate_tables(decompressed_path, rules)
        logger.info("stage=parse format=%s tables_found=%d", file_format, len(proposed))

        # Targeted re-upload: when the caller supplies the section path or
        # sanitised name of the existing table, isolate the matching section
        # instead of taking whichever sheet comes first.
        #
        # Match precedence:
        #   1. ``sheet_or_json_path`` — exact match (stable when the section
        #      range is unchanged).
        #   2. ``target_name`` (sanitised) — robust across re-uploads where
        #      a row insertion shifts the section range (``section[1:697]``
        #      → ``section[1:698]``) but the human-readable name is stable.
        if existing_table_id is not None and proposed and (target_sheet_or_json_path or target_name):
            match_idx: int | None = None
            match_reason = ""

            if target_sheet_or_json_path:
                match_idx = next(
                    (
                        i
                        for i, p in enumerate(proposed)
                        if getattr(p, "sheet_or_json_path", None) == target_sheet_or_json_path
                    ),
                    None,
                )
                if match_idx is not None:
                    match_reason = f"sheet_or_json_path={target_sheet_or_json_path!r}"

            if match_idx is None and target_name:
                target_norm = _sanitise_name(target_name)
                match_idx = next(
                    (i for i, p in enumerate(proposed) if _sanitise_name(p.name) == target_norm),
                    None,
                )
                if match_idx is not None:
                    match_reason = f"name={target_name!r}"

            if match_idx is None:
                logger.warning(
                    "re-upload target section not found in %d proposed tables "
                    "(sheet=%r name=%r); falling back to first section",
                    len(proposed),
                    target_sheet_or_json_path,
                    target_name,
                )
            else:
                proposed = [proposed[match_idx]]
                logger.info("re-upload: filtered proposed sections by %s", match_reason)

        parsed: list[ParsedTable] = []

        # When re-uploading into an existing slot, we only materialise the
        # first proposed table into that slot (the schema diff is handled in
        # reconcile). Multi-table re-uploads are not yet supported (Phase F).
        for i, pt in enumerate(proposed):
            if existing_table_id is not None and i > 0:
                logger.warning(
                    "re-upload produced %d tables; only first mapped to existing slot %s",
                    len(proposed),
                    existing_table_id,
                )
                break

            table_id = existing_table_id if existing_table_id is not None else uuid.uuid4()

            # If there's only one table (CSV/TSV/single-sheet), prefer the
            # original filename stem so the table is named "orders" not a
            # temp path like "tmpXXXX".
            raw_name = Path(original_filename).stem if original_filename and len(proposed) == 1 else pt.name
            safe_name = _sanitise_name(raw_name)
            qualified_name = f"{_sanitise_name(dataset_name)}.{safe_name}"

            # Build the Parquet key: determine version number
            snap_version = await _next_version(table_id, tenant_id, workspace_id, session_factory)
            parquet_key = (
                f"flyquery/{tenant_id}/{workspace_id}/{dataset_id}/tables/{table_id}/v{snap_version}.parquet"
            )

            # Materialise Parquet to a local temp path first, then upload.
            # Per-section failures (e.g. a dashboard-XLSX section with
            # un-sniffable CSV after compaction) are logged and skipped
            # rather than aborting the whole upload -- a 60-section file
            # with 1 quirky section should still ingest the other 59.
            local_parquet = tempfile.mktemp(suffix=".parquet")  # noqa: S306
            try:
                try:
                    mat_result = await reader.materialise(
                        decompressed_path,
                        pt,
                        local_parquet,
                        workspace_locale=workspace_locale,
                        type_infer_sample_rows=settings.type_infer_sample_rows,
                        max_title_rows=settings.max_title_rows,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "stage=parse failed_to_materialise table=%s path=%s err=%s",
                        pt.name,
                        pt.sheet_or_json_path,
                        exc,
                    )
                    continue

                # Smart column-name proposal: when DuckDB fell back to
                # ``columnNN`` because the section didn't carry a real
                # header band, ask the proposer agent for snake_case
                # business names. The Parquet is rewritten in place;
                # the MaterialiseResult.columns list is updated so
                # downstream stages see the new names from the start.
                section_label_for_naming = pt.name.split("__", 1)[-1] if "__" in pt.name else pt.name
                try:
                    mat_result = await _propose_meaningful_column_names(
                        section_label=section_label_for_naming,
                        mat_result=mat_result,
                        parquet_path=local_parquet,
                        settings=settings,
                        logger_=logger,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "stage=parse column_name_proposal_skipped table=%s err=%s",
                        pt.name,
                        exc,
                    )

                # Upload Parquet to object store. We keep the local file
                # around -- sample / profile / describe read it directly,
                # ingest_service cleans up after publish.
                parquet_bytes = Path(local_parquet).read_bytes()
                await object_store.put(parquet_key, parquet_bytes, "application/octet-stream")
            except Exception:
                # Materialise / upload failed; clean up the temp file
                # immediately since no downstream stage will use it.
                Path(local_parquet).unlink(missing_ok=True)
                raise

            # Insert or verify flyquery_tables row. When a row already
            # exists for ``(dataset_id, safe_name)`` (i.e. someone
            # uploaded a same-named file before), the upsert returns
            # the existing row's id and we re-use it -- otherwise
            # downstream FKs (snapshot, schema_objects) would point at
            # the freshly-generated UUID and fail with
            # ``ForeignKeyViolationError``.
            if existing_table_id is None:
                table_id = await _insert_table(
                    table_id=table_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    dataset_id=dataset_id,
                    source_file_id=file_id,
                    name=safe_name,
                    qualified_name=qualified_name,
                    sheet_or_json_path=pt.sheet_or_json_path,
                    session_factory=session_factory,
                )

            # Update source_file_id on existing table
            if existing_table_id is not None:
                await _update_table_file(table_id, file_id, session_factory)

            parsed.append(
                ParsedTable(
                    table_id=table_id,
                    name=safe_name,
                    qualified_name=qualified_name,
                    sheet_or_json_path=pt.sheet_or_json_path,
                    parquet_key=parquet_key,
                    result=mat_result,
                    local_parquet_path=local_parquet,
                )
            )
            logger.info(
                "stage=parse table_id=%s name=%s rows=%d cols=%d parquet_key=%s",
                table_id,
                safe_name,
                mat_result.n_rows_actual,
                len(mat_result.columns),
                parquet_key,
            )

        return parsed

    finally:
        if cleanup_decompressed:
            Path(decompressed_path).unlink(missing_ok=True)


async def _next_version(
    table_id: uuid.UUID,
    tenant_id: str,
    workspace_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Return the next snapshot version number (1-based)."""
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                "SELECT count(*) FROM flyquery_schema_snapshots WHERE table_id = :tid AND tenant_id = :tenant"
            ),
            {"tid": table_id, "tenant": tenant_id},
        )
        count = result.scalar_one()
        return count + 1


async def _insert_table(
    *,
    table_id: uuid.UUID,
    tenant_id: str,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    source_file_id: uuid.UUID,
    name: str,
    qualified_name: str,
    sheet_or_json_path: str | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Insert a flyquery_tables row OR resolve an existing one.

    Returns the effective ``table_id`` -- the freshly-inserted UUID
    when this is a new (dataset_id, name) pair, or the existing row's
    UUID when ON CONFLICT triggers. The caller MUST use this returned
    id rather than the input ``table_id`` -- otherwise downstream
    inserts (snapshot, schema_objects) would reference a UUID that
    doesn't exist in flyquery_tables and trigger a foreign-key
    violation (this was the cause of the dual-format re-upload bug
    on 2026-05-24).
    """
    async with session_factory() as s, s.begin():
        result = await s.execute(
            sa.text(
                """
                INSERT INTO flyquery_tables (
                    id, tenant_id, workspace_id, dataset_id,
                    source_file_id, name, qualified_name,
                    sheet_or_json_path, kind
                ) VALUES (
                    :id, :tenant_id, :workspace_id, :dataset_id,
                    :source_file_id, :name, :qualified_name,
                    :sheet_or_json_path, 'UPLOADED'
                )
                ON CONFLICT (dataset_id, name) DO UPDATE
                    SET source_file_id = EXCLUDED.source_file_id,
                        updated_at = now()
                RETURNING id
                """
            ),
            {
                "id": table_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "dataset_id": dataset_id,
                "source_file_id": source_file_id,
                "name": name,
                "qualified_name": qualified_name,
                "sheet_or_json_path": sheet_or_json_path,
            },
        )
        return result.scalar_one()


async def _update_table_file(
    table_id: uuid.UUID,
    file_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s, s.begin():
        await s.execute(
            sa.text("UPDATE flyquery_tables SET source_file_id = :fid, updated_at = now() WHERE id = :tid"),
            {"fid": file_id, "tid": table_id},
        )
