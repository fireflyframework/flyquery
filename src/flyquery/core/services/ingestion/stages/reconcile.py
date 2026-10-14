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

"""Stage 3 — reconcile: snapshot insert (PARTIAL) + schema diff + objects.

For each ParsedTable:
- Insert flyquery_schema_snapshots row (status='PARTIAL')
- Insert flyquery_schema_objects: one TABLE object + one COLUMN per column
- If a prev snapshot exists, compute diff → write flyquery_schema_changes
- Annotation transplant: carry HUMAN-set fields from old → new schema_objects
- Return the created snapshot_id
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flyquery.core.services.ingestion.stages.parse import ParsedTable
from flyquery.core.services.storage.jsonb_normalize import (
    normalize_governance_json,
    normalize_synonyms_json,
)

_SYNTHETIC_HEADER = re.compile(r"(?i)^(column|col|unnamed|field|sheet)[\s_:.\-]*\d*$")


def _plausible_original_header(name: str | None) -> str | None:
    """Return a real source header worth preserving, else None.

    Keeps meaningful headers (incl. plain years like '2024') but drops synthetic
    placeholders (column5, Unnamed: 0) and obvious null tokens, so the surfaced
    'original header' is signal, not noise. Fully generic.
    """
    if not name:
        return None
    s = str(name).strip()
    if not s or len(s) > 60:
        return None
    if _SYNTHETIC_HEADER.match(s):
        return None
    if s.lower() in {"none", "null", "nan", "n/a", "na", "-"}:
        return None
    # A header that is just a number is almost certainly a mis-detected data cell;
    # skip it -- UNLESS it is a plausible 4-digit year (a real period header).
    try:
        float(s.replace(",", ""))
        if not (s.isdigit() and len(s) == 4 and 1900 <= int(s) <= 2100):
            return None
    except ValueError:
        pass  # non-numeric header -> keep
    return s


def _governance_with_header(annotation: dict, col: Any) -> str:
    """Serialise governance_json, merging the column's plausible original header."""
    gov = normalize_governance_json(annotation.get("governance_json"))
    if not isinstance(gov, dict):
        gov = {}
    oh = _plausible_original_header(getattr(col, "original_name", None))
    if oh and not gov.get("original_header"):
        gov = {**gov, "original_header": oh}
    return json.dumps(gov)


# Rename auto-confirm threshold (passed from settings when available)
_DEFAULT_AUTO_CONFIRM_THRESHOLD = 0.8

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    snapshot_id: uuid.UUID
    table_id: uuid.UUID
    n_columns: int
    n_rows_actual: int
    added_columns: list[str]
    removed_columns: list[str]
    type_changed: list[str]


async def run_reconcile(
    *,
    tenant_id: str,
    workspace_id: uuid.UUID,
    dataset_id: uuid.UUID,
    parsed: ParsedTable,
    actor: str,
    triggered_by: str,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Any | None = None,
) -> ReconcileResult:
    """Execute Stage 3: reconcile."""
    mat = parsed.result
    snapshot_id = uuid.uuid4()

    # Snapshot hash = hash of (column_name, data_type) pairs for change detection
    col_sig = sorted((c.name, c.data_type) for c in mat.columns)
    snapshot_hash = hashlib.sha256(json.dumps(col_sig).encode()).hexdigest()

    # --- Insert snapshot (PARTIAL) ---
    async with session_factory() as s, s.begin():
        await s.execute(
            sa.text(
                """
                INSERT INTO flyquery_schema_snapshots (
                    id, tenant_id, workspace_id, dataset_id, table_id,
                    snapshot_hash, n_columns, n_rows_estimate, n_rows_actual,
                    parquet_object_key, parquet_byte_size, status,
                    triggered_by, created_by
                ) VALUES (
                    :id, :tenant_id, :workspace_id, :dataset_id, :table_id,
                    :snapshot_hash, :n_columns, :n_rows_estimate, :n_rows_actual,
                    :parquet_object_key, :parquet_byte_size, 'PARTIAL',
                    :triggered_by, :created_by
                )
                """
            ),
            {
                "id": snapshot_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "dataset_id": dataset_id,
                "table_id": parsed.table_id,
                "snapshot_hash": snapshot_hash,
                "n_columns": len(mat.columns),
                "n_rows_estimate": mat.n_rows_actual,
                "n_rows_actual": mat.n_rows_actual,
                "parquet_object_key": parsed.parquet_key,
                "parquet_byte_size": mat.parquet_byte_size,
                "triggered_by": triggered_by,
                "created_by": actor,
            },
        )

    # --- Find previous snapshot for diff ---
    prev_snapshot = await _get_latest_ready_snapshot(tenant_id, parsed.table_id, snapshot_id, session_factory)
    prev_columns: dict[str, str] = {}  # name → data_type
    if prev_snapshot:
        prev_columns = await _get_snapshot_columns(prev_snapshot["id"], tenant_id, session_factory)

    new_columns: dict[str, str] = {c.name: c.data_type for c in mat.columns}

    # --- Compute diff ---
    added = [name for name in new_columns if name not in prev_columns]
    removed = [name for name in prev_columns if name not in new_columns]
    type_changed = [
        name for name in new_columns if name in prev_columns and new_columns[name] != prev_columns[name]
    ]

    prev_snap_id = prev_snapshot["id"] if prev_snapshot else None

    # --- Rename detection (Stage 3 deep-dive) ---
    # Build position-indexed maps from ColumnSchema for rename detection
    {c.position: c for c in mat.columns}
    {c.name: c for c in mat.columns}

    prev_snapshot_columns_detail: list[dict[str, Any]] = []
    if prev_snapshot:
        prev_snapshot_columns_detail = await _get_snapshot_columns_detail(
            prev_snapshot["id"], tenant_id, session_factory
        )

    confirmed_renames: dict[str, str] = {}  # old_name → new_name
    confirmed_rationales: dict[str, str] = {}  # old_name → LLM rationale
    candidate_renames: list[
        tuple[str, list[dict[str, Any]]]
    ] = []  # (old_name, [{name, confidence, rationale}])

    if prev_snapshot and removed and added:
        confirmed_renames, confirmed_rationales, candidate_renames = await _detect_renames(
            removed_names=removed,
            added_names=added,
            prev_columns=prev_columns,
            new_columns=new_columns,
            prev_detail=prev_snapshot_columns_detail,
            settings=settings,
        )

        # Update added/removed to exclude confirmed renames
        for old_name, new_name in confirmed_renames.items():
            if old_name in removed:
                removed.remove(old_name)
            if new_name in added:
                added.remove(new_name)

    # --- Mark removed columns as is_active=false on their old schema_objects rows ---
    if prev_snapshot and removed:
        await _mark_removed_columns_inactive(
            tenant_id=tenant_id,
            prev_snapshot_id=cast("uuid.UUID", prev_snap_id),
            removed_names=removed,
            session_factory=session_factory,
        )

    # --- Write schema_changes ---
    if prev_snapshot and (added or removed or type_changed or confirmed_renames or candidate_renames):
        await _write_schema_changes(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            table_id=parsed.table_id,
            prev_snapshot_id=prev_snap_id,
            next_snapshot_id=snapshot_id,
            prev_columns=prev_columns,
            new_columns=new_columns,
            added=added,
            removed=removed,
            type_changed=type_changed,
            confirmed_renames=confirmed_renames,
            confirmed_rationales=confirmed_rationales,
            candidate_renames=candidate_renames,
            session_factory=session_factory,
        )

    # --- Load annotation transplant candidates from previous snapshot ---
    human_annotations: dict[str, dict[str, Any]] = {}
    if prev_snapshot:
        human_annotations = await _load_human_annotations(
            cast("uuid.UUID", prev_snap_id), tenant_id, session_factory
        )

    # --- Insert schema_objects (TABLE + per-column COLUMN) ---
    table_obj_id = uuid.uuid4()
    table_source_hash = hashlib.sha256(f"{parsed.qualified_name}:TABLE".encode()).hexdigest()
    async with session_factory() as s, s.begin():
        await s.execute(
            sa.text(
                """
                INSERT INTO flyquery_schema_objects (
                    id, tenant_id, workspace_id, table_id, snapshot_id,
                    kind, qualified_name, source_hash
                ) VALUES (
                    :id, :tenant_id, :workspace_id, :table_id, :snapshot_id,
                    'TABLE', :qualified_name, :source_hash
                )
                """
            ),
            {
                "id": table_obj_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "table_id": parsed.table_id,
                "snapshot_id": snapshot_id,
                "qualified_name": parsed.qualified_name,
                "source_hash": table_source_hash,
            },
        )

        for col in mat.columns:
            col_qualified = f"{parsed.qualified_name}.{col.name}"
            col_hash = hashlib.sha256(f"{col_qualified}:{col.data_type}".encode()).hexdigest()
            col_obj_id = uuid.uuid4()

            # Transplant human annotations if this column existed before.
            # Also check reverse of confirmed_renames: if new_col was renamed from
            # old_col, carry old_col's annotations onto new_col.
            annotation = human_annotations.get(col.name, {})
            if not annotation:
                # Build reverse rename map: new_name → old_name
                reverse_renames = {v: k for k, v in (confirmed_renames or {}).items()}
                old_name = reverse_renames.get(col.name)
                if old_name:
                    annotation = human_annotations.get(old_name, {})

            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_objects (
                        id, tenant_id, workspace_id, table_id, snapshot_id,
                        kind, parent_id, qualified_name, data_type, is_nullable,
                        source_hash,
                        description, description_source,
                        synonyms_json, pii_tag, pii_source,
                        business_owner, governance_json
                    ) VALUES (
                        :id, :tenant_id, :workspace_id, :table_id, :snapshot_id,
                        'COLUMN', :parent_id, :qualified_name, :data_type, :is_nullable,
                        :source_hash,
                        :description, :description_source,
                        CAST(:synonyms_json AS jsonb), :pii_tag, :pii_source,
                        :business_owner, CAST(:governance_json AS jsonb)
                    )
                    """
                ),
                {
                    "id": col_obj_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "table_id": parsed.table_id,
                    "snapshot_id": snapshot_id,
                    "parent_id": table_obj_id,
                    "qualified_name": col_qualified,
                    "data_type": col.data_type,
                    "is_nullable": col.is_nullable,
                    "source_hash": col_hash,
                    "description": annotation.get("description"),
                    "description_source": annotation.get("description_source"),
                    # Always insert canonical shapes (list for synonyms,
                    # dict for governance) -- annotation may have been
                    # transplanted from a legacy row whose JSONB was the
                    # wrong shape; the normalisers heal that on the way in.
                    "synonyms_json": json.dumps(normalize_synonyms_json(annotation.get("synonyms_json"))),
                    "pii_tag": annotation.get("pii_tag"),
                    "pii_source": annotation.get("pii_source"),
                    "business_owner": annotation.get("business_owner"),
                    # round-2 #3: preserve the source's original header (pre-rename)
                    # so the query layer knows what e.g. year_1 actually was.
                    "governance_json": _governance_with_header(annotation, col),
                },
            )

    logger.info(
        "stage=reconcile snapshot_id=%s table_id=%s added=%d removed=%d type_changed=%d",
        snapshot_id,
        parsed.table_id,
        len(added),
        len(removed),
        len(type_changed),
    )

    return ReconcileResult(
        snapshot_id=snapshot_id,
        table_id=parsed.table_id,
        n_columns=len(mat.columns),
        n_rows_actual=mat.n_rows_actual,
        added_columns=added,
        removed_columns=removed,
        type_changed=type_changed,
    )


async def _get_latest_ready_snapshot(
    tenant_id: str,
    table_id: uuid.UUID,
    exclude_snapshot_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any] | None:
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                """
                SELECT id, n_columns, taken_at
                FROM flyquery_schema_snapshots
                WHERE tenant_id = :tenant AND table_id = :tid
                  AND status = 'READY'
                  AND id != :excl
                ORDER BY taken_at DESC
                LIMIT 1
                """
            ),
            {"tenant": tenant_id, "tid": table_id, "excl": exclude_snapshot_id},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row else None


async def _get_snapshot_columns(
    snapshot_id: uuid.UUID,
    tenant_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Return {column_name: data_type} for a snapshot."""
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                """
                SELECT qualified_name, data_type
                FROM flyquery_schema_objects
                WHERE snapshot_id = :sid AND tenant_id = :tenant AND kind = 'COLUMN'
                """
            ),
            {"sid": snapshot_id, "tenant": tenant_id},
        )
        rows = result.mappings().all()
        # qualified_name is like "dataset.table.col_name"; extract last part
        return {row["qualified_name"].rsplit(".", 1)[-1]: row["data_type"] or "" for row in rows}


async def _load_human_annotations(
    snapshot_id: uuid.UUID,
    tenant_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, dict[str, Any]]:
    """Load HUMAN-set annotations from the previous snapshot (keyed by column name)."""
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                """
                SELECT
                    qualified_name,
                    description, description_source,
                    synonyms_json, pii_tag, pii_source,
                    business_owner, governance_json
                FROM flyquery_schema_objects
                WHERE snapshot_id = :sid AND tenant_id = :tenant AND kind = 'COLUMN'
                  AND (
                    description_source = 'HUMAN'
                    OR pii_source = 'HUMAN'
                    OR business_owner IS NOT NULL
                  )
                """
            ),
            {"sid": snapshot_id, "tenant": tenant_id},
        )
        out: dict[str, dict[str, Any]] = {}
        for row in result.mappings().all():
            col_name = row["qualified_name"].rsplit(".", 1)[-1]
            out[col_name] = {
                "description": row["description"],
                "description_source": row["description_source"],
                "synonyms_json": row["synonyms_json"],
                "pii_tag": row["pii_tag"],
                "pii_source": row["pii_source"],
                "business_owner": row["business_owner"],
                "governance_json": row["governance_json"],
            }
        return out


async def _mark_removed_columns_inactive(
    *,
    tenant_id: str,
    prev_snapshot_id: uuid.UUID,
    removed_names: list[str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Set is_active=false on schema_objects rows from the previous snapshot
    whose column names are no longer present in the new upload.
    The rows are preserved for historical pinning.
    """
    if not removed_names:
        return
    async with session_factory() as s, s.begin():
        for col_name in removed_names:
            # qualified_name ends with ".<col_name>", so we match the suffix.
            await s.execute(
                sa.text(
                    """
                    UPDATE flyquery_schema_objects
                    SET is_active = false, last_changed_at = now()
                    WHERE snapshot_id = :snap_id
                      AND tenant_id = :tenant
                      AND kind = 'COLUMN'
                      AND qualified_name LIKE :pattern
                    """
                ),
                {
                    "snap_id": prev_snapshot_id,
                    "tenant": tenant_id,
                    "pattern": f"%.{col_name}",
                },
            )


async def _write_schema_changes(
    *,
    tenant_id: str,
    workspace_id: uuid.UUID,
    table_id: uuid.UUID,
    prev_snapshot_id: uuid.UUID | None,
    next_snapshot_id: uuid.UUID,
    prev_columns: dict[str, str],
    new_columns: dict[str, str],
    added: list[str],
    removed: list[str],
    type_changed: list[str],
    confirmed_renames: dict[str, str] | None = None,
    confirmed_rationales: dict[str, str] | None = None,
    candidate_renames: list[tuple[str, list[dict[str, Any]]]] | None = None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s, s.begin():
        for col_name in added:
            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_changes (
                        id, tenant_id, workspace_id, table_id,
                        prev_snapshot_id, next_snapshot_id,
                        column_name, change, before_json, after_json
                    ) VALUES (
                        :id, :tenant_id, :workspace_id, :table_id,
                        :prev_snap, :next_snap,
                        :col, 'ADDED', null, CAST(:after AS jsonb)
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "table_id": table_id,
                    "prev_snap": prev_snapshot_id,
                    "next_snap": next_snapshot_id,
                    "col": col_name,
                    "after": json.dumps({"data_type": new_columns[col_name]}),
                },
            )
        for col_name in removed:
            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_changes (
                        id, tenant_id, workspace_id, table_id,
                        prev_snapshot_id, next_snapshot_id,
                        column_name, change, before_json, after_json
                    ) VALUES (
                        :id, :tenant_id, :workspace_id, :table_id,
                        :prev_snap, :next_snap,
                        :col, 'REMOVED', CAST(:before AS jsonb), null
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "table_id": table_id,
                    "prev_snap": prev_snapshot_id,
                    "next_snap": next_snapshot_id,
                    "col": col_name,
                    "before": json.dumps({"data_type": prev_columns[col_name]}),
                },
            )
        for col_name in type_changed:
            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_changes (
                        id, tenant_id, workspace_id, table_id,
                        prev_snapshot_id, next_snapshot_id,
                        column_name, change, before_json, after_json
                    ) VALUES (
                        :id, :tenant_id, :workspace_id, :table_id,
                        :prev_snap, :next_snap,
                        :col, 'TYPE_CHANGED', CAST(:before AS jsonb), CAST(:after AS jsonb)
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "table_id": table_id,
                    "prev_snap": prev_snapshot_id,
                    "next_snap": next_snapshot_id,
                    "col": col_name,
                    "before": json.dumps({"data_type": prev_columns[col_name]}),
                    "after": json.dumps({"data_type": new_columns[col_name]}),
                },
            )

        # Confirmed renames (auto-confirmed by 1-to-1 type signature OR LLM agent ≥ 0.8)
        rationales_map = confirmed_rationales or {}
        for old_name, new_name in (confirmed_renames or {}).items():
            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_changes (
                        id, tenant_id, workspace_id, table_id,
                        prev_snapshot_id, next_snapshot_id,
                        column_name, change, before_json, after_json,
                        llm_rationale
                    ) VALUES (
                        :id, :tenant_id, :workspace_id, :table_id,
                        :prev_snap, :next_snap,
                        :col, 'RENAMED', CAST(:before AS jsonb), CAST(:after AS jsonb),
                        :rationale
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "table_id": table_id,
                    "prev_snap": prev_snapshot_id,
                    "next_snap": next_snapshot_id,
                    "col": old_name,
                    "before": json.dumps({"column_name": old_name, "data_type": prev_columns.get(old_name)}),
                    "after": json.dumps({"column_name": new_name, "data_type": new_columns.get(new_name)}),
                    "rationale": rationales_map.get(old_name) or None,
                },
            )

        # Candidate renames (LLM ranking failed to pass threshold — human review)
        # ``candidates_list`` holds dicts ``{name, confidence, rationale}`` sorted
        # best-first by the LLM agent. The top entry's rationale is hoisted to
        # ``llm_rationale`` so operators see WHY the system surfaced this row
        # without parsing the JSON envelope.
        for old_name, candidates_list in candidate_renames or []:
            top_rationale: str | None = None
            if candidates_list:
                top = candidates_list[0]
                if isinstance(top, dict):
                    top_rationale = top.get("rationale") or None
            await s.execute(
                sa.text(
                    """
                    INSERT INTO flyquery_schema_changes (
                        id, tenant_id, workspace_id, table_id,
                        prev_snapshot_id, next_snapshot_id,
                        column_name, change, before_json, after_json,
                        llm_rationale
                    ) VALUES (
                        :id, :tenant_id, :workspace_id, :table_id,
                        :prev_snap, :next_snap,
                        :col, 'RENAMED_CANDIDATE', CAST(:before AS jsonb), CAST(:after AS jsonb),
                        :rationale
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "table_id": table_id,
                    "prev_snap": prev_snapshot_id,
                    "next_snap": next_snapshot_id,
                    "col": old_name,
                    "before": json.dumps({"column_name": old_name, "data_type": prev_columns.get(old_name)}),
                    "after": json.dumps({"candidates": candidates_list}),
                    "rationale": top_rationale,
                },
            )


# ---------------------------------------------------------------------------
# Rename detection helpers (Stage 3 deep-dive)
# ---------------------------------------------------------------------------


async def _get_snapshot_columns_detail(
    snapshot_id: uuid.UUID,
    tenant_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    """Return full column detail for rename comparison."""
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                """
                SELECT qualified_name, data_type, description, sample_values_json
                FROM flyquery_schema_objects
                WHERE snapshot_id = :sid AND tenant_id = :tenant AND kind = 'COLUMN'
                ORDER BY qualified_name
                """
            ),
            {"sid": snapshot_id, "tenant": tenant_id},
        )
        rows = []
        for r in result.mappings().all():
            d = dict(r)
            d["col_name"] = (d.get("qualified_name") or "").rsplit(".", 1)[-1]
            rows.append(d)
        return rows


async def _detect_renames(
    *,
    removed_names: list[str],
    added_names: list[str],
    prev_columns: dict[str, str],
    new_columns: dict[str, str],
    prev_detail: list[dict[str, Any]],
    settings: Any | None,
) -> tuple[dict[str, str], dict[str, str], list[tuple[str, list[dict[str, Any]]]]]:
    """Detect column renames via position+type signature + optional LLM agent.

    Returns a tuple of three structures:

    * ``confirmed_renames``: ``{old_name → new_name}`` — auto-confirmed mappings
      (either unambiguous 1-to-1 by type, or LLM top proposal ≥
      :data:`_DEFAULT_AUTO_CONFIRM_THRESHOLD`).
    * ``confirmed_rationales``: ``{old_name → rationale}`` — natural-language
      rationale from the LLM (empty string for unambiguous 1-to-1 type matches).
    * ``candidate_renames``: ``[(old_name, [{name, confidence, rationale}, ...])]``
      — ranked candidate proposals when no candidate passed the auto-confirm
      threshold. Order is best-first by ``confidence``.
    """
    confirmed: dict[str, str] = {}
    rationales: dict[str, str] = {}
    candidates: list[tuple[str, list[dict[str, Any]]]] = []

    if not removed_names or not added_names:
        return confirmed, rationales, candidates

    # Build type-signature groups for added and removed
    # Group removed columns by data_type
    removed_by_type: dict[str, list[str]] = {}
    for name in removed_names:
        dt = prev_columns.get(name, "")
        removed_by_type.setdefault(dt, []).append(name)

    added_by_type: dict[str, list[str]] = {}
    for name in added_names:
        dt = new_columns.get(name, "")
        added_by_type.setdefault(dt, []).append(name)

    unmatched_removed: set[str] = set(removed_names)

    for dt, rem_cols in removed_by_type.items():
        add_cols = added_by_type.get(dt, [])
        if not add_cols:
            continue

        if len(rem_cols) == 1 and len(add_cols) == 1:
            # Unambiguous: one removed ↔ one added, same type → auto-RENAMED
            old_name = rem_cols[0]
            new_name = add_cols[0]
            confirmed[old_name] = new_name
            rationales[old_name] = (
                f"Auto-confirmed by 1-to-1 type signature match ({dt}): "
                f"only one removed column and one added column shared this type."
            )
            unmatched_removed.discard(old_name)
        else:
            # Ambiguous: multiple candidates — ask the LLM agent to rank them
            for old_name in rem_cols:
                if old_name in unmatched_removed:
                    ranked = await _invoke_rename_agent(
                        old_name=old_name,
                        candidate_names=add_cols,
                        prev_detail=prev_detail,
                        new_columns=new_columns,
                        settings=settings,
                    )
                    if ranked and ranked[0]["confidence"] >= _DEFAULT_AUTO_CONFIRM_THRESHOLD:
                        # Top proposal passes the auto-confirm threshold.
                        top = ranked[0]
                        confirmed[old_name] = top["name"]
                        rationales[old_name] = top.get("rationale") or ""
                        unmatched_removed.discard(old_name)
                    elif ranked:
                        # Below threshold — surface the LLM's ranked list as candidates.
                        candidates.append((old_name, ranked))
                        unmatched_removed.discard(old_name)
                    else:
                        # LLM unavailable / errored — fall back to the raw
                        # type-group as unscored candidates so the operator
                        # still has something to review.
                        fallback = [{"name": c, "confidence": None, "rationale": None} for c in add_cols]
                        candidates.append((old_name, fallback))
                        unmatched_removed.discard(old_name)

    return confirmed, rationales, candidates


async def _invoke_rename_agent(
    *,
    old_name: str,
    candidate_names: list[str],
    prev_detail: list[dict[str, Any]],
    new_columns: dict[str, str],
    settings: Any | None,
) -> list[dict[str, Any]] | None:
    """Call RenameDetectionAgent. Returns the full ranked list of proposals
    (each ``{name, confidence, rationale}``) or ``None`` on failure / no result.

    The list is ranked from most to least likely. Callers pick the top entry
    for auto-confirm and persist the rest as the ranked candidate list.
    """
    if settings is None:
        return None

    try:
        from flyquery.core.agents.rename_detection_agent import build_rename_detection_agent
    except (ImportError, RuntimeError) as exc:
        logger.warning("rename_detection_agent unavailable (skip LLM): %s", exc)
        return None

    try:
        # Build old column context
        old_detail = next((c for c in prev_detail if c.get("col_name") == old_name), {})
        candidates_ctx = []
        for cname in candidate_names[:10]:
            candidates_ctx.append(
                {
                    "name": cname,
                    "data_type": new_columns.get(cname, "UNKNOWN"),
                    "description": None,
                    "samples": [],
                }
            )

        prompt = json.dumps(
            {
                "removed_column": {
                    "name": old_name,
                    "data_type": old_detail.get("data_type"),
                    "description": old_detail.get("description"),
                    "samples": (old_detail.get("sample_values_json") or [])[:5],
                },
                "candidate_new_columns": candidates_ctx,
            }
        )

        agent = build_rename_detection_agent(settings)
        result = await agent.run(prompt)
        proposals = result.output.items

        if not proposals:
            return None

        return [
            {
                "name": p.new_column,
                "confidence": float(p.confidence),
                "rationale": p.rationale,
            }
            for p in proposals
        ]

    except Exception as exc:  # noqa: BLE001
        logger.warning("rename_detection_agent failed (graceful skip): %s", exc)
        return None
