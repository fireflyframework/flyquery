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

"""XLSX / XLS / ODS reader (python-calamine) with section-aware extraction.

Real-world spreadsheets are rarely a single flat tabular block. A
typical financial / company-profile export (Orbis / BvD, Bloomberg,
Refinitiv, etc.) is a *dashboard-style* sheet: a header band, a
key-figures box, several periodic tables (one per accounting period),
a contact card, an ownership graph, and a regulatory-codes section --
all laid out down the same sheet with section labels, sparse rows,
and variable column widths per section.

A naive ``sheet = one table'' reader on such a sheet produces a
flat dump with synthetic ``columnNNN'' names and mostly-NULL cells.
That's not useful for Text-to-SQL.

Strategy
========
For every sheet we walk the rows once and segment them into
*sections* using:

1. **Section labels** -- single-cell string rows. The label is kept
   and used to name the next emitted table.
2. **Header rows** -- the first row with >= 2 non-empty cells after
   a label (or after one or more empty rows). The header width
   defines the section's column count.
3. **Section boundary** -- two consecutive empty rows OR another
   single-cell string row (next label) close the section.

Each section becomes its own ``ProposedTable``. ``sheet_or_json_path``
encodes the section's row span as ``<sheet_name>#section[<h>:<e>]``
where ``<h>`` is the header row index and ``<e>`` is the
(exclusive) data end. ``_materialise_sync`` parses that back and
slices just the section's rows before handing them to DuckDB for
type inference + Parquet output.

Backward compat: if a sheet contains exactly one section that spans
its entire usable range (i.e. a classic flat tabular XLSX), exactly
one ``ProposedTable`` is emitted with the sheet's name -- identical
to the pre-section behavior.
"""

from __future__ import annotations

import asyncio
import datetime
import re
import tempfile
from pathlib import Path
from typing import Any

from flyquery.core.services.ingestion.reader import (
    ColumnSchema,
    MaterialiseResult,
    ProposedTable,
    TableExtractionRules,
)

_NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_]+")
# ``#section[<header>:<end>]`` (header row + data on the next rows, contiguous)
# OR ``#section[<header>:<data_start>:<end>]`` when the header row is NOT
# contiguous with the data (an inherited period header -- see below).
_SECTION_RE = re.compile(r"^(?P<sheet>.+)#section\[(?P<a>\d+):(?P<b>\d+)(?::(?P<c>\d+))?\]$")
# A period *value* must be the WHOLE cell (a bare year, an ISO date with an
# optional time, or an FY/H/Q-prefixed year) -- NOT merely a string that
# happens to contain a 4-digit year (which would match invoice/reference codes
# like ``INV-2024-0007`` or ``Form 2020`` and wrongly flag a row as a header).
_PERIOD_RE = re.compile(
    r"^(?:fy|h[12]|q[1-4])?[\s/-]?(?:19|20)\d{2}(?:-\d{2}-\d{2})?(?:[ t]\d{2}:\d{2}(?::\d{2})?)?$",
    re.IGNORECASE,
)

# Heuristic constants
_MIN_HEADER_NON_EMPTY = 2  # a row needs >= 2 non-empty cells to be a header
_SECTION_BREAK_EMPTY_ROWS = 2  # >= 2 consecutive empty rows close a section
# When the first header candidate looks like a numeric/spacer row, look this
# many rows ahead for a clearly-better string-label row before settling.
_HEADER_LOOKAHEAD = 3
# Max rows a data-first section may look BACK to inherit a period/date header
# (financial reports repeat a date header above each block of sub-sections).
_PERIOD_HEADER_MAX_DISTANCE = 60


def _normalise_leading_blanks(rows: list[list[Any]]) -> list[list[Any]]:
    """Drop leading rows that are *entirely* empty.

    calamine's ``to_python(skip_empty_area=True)`` trims the used-range
    bounding box, but the exact number of leading blank rows it keeps can
    differ between near-identical re-ingests (HDR-UNSTABLE) -- which flips
    every section's absolute row index and causes column-name churn. We
    normalise here by consistently removing fully-empty leading rows so the
    same logical sheet yields the same header index. This MUST be applied
    identically in ``_enumerate_sync`` (where indices are computed) and
    ``_materialise_sync`` (where they are sliced) for the indices to line up.
    """
    start = 0
    n = len(rows)
    while start < n and all(c in ("", None) for c in rows[start]):
        start += 1
    # Avoid a needless copy when nothing was trimmed.
    return rows if start == 0 else rows[start:]


def _looks_like_label_row(row: list[Any]) -> bool:
    """True when a row's populated cells are predominantly non-empty STRINGS.

    Header rows hold labels (text); spacer/index rows hold bare numbers
    (1, 2, 3, ...). We require a strict string majority so genuinely numeric,
    period, or date headers are not misclassified as data.
    """
    non_empty = [c for c in row if c not in ("", None)]
    if not non_empty:
        return False
    str_cells = sum(1 for c in non_empty if isinstance(c, str) and c.strip() != "")
    return str_cells * 2 > len(non_empty)


def _is_numeric_spacer_row(row: list[Any]) -> bool:
    """True when a header candidate looks like a numeric spacer, not labels.

    A row is a spacer when every populated cell is numeric (int/float, or a
    numeric-looking string) and none is a real text label. This includes the
    classic contiguous ``1..k`` column-numbering run Excel exports sometimes
    inject above the real header band. A row with any genuine string label is
    never a spacer.
    """
    non_empty = [c for c in row if c not in ("", None)]
    if len(non_empty) < _MIN_HEADER_NON_EMPTY:
        return False

    def _as_number(cell: Any) -> float | None:
        if isinstance(cell, bool):
            return None
        if isinstance(cell, (int, float)):
            return float(cell)
        if isinstance(cell, str):
            try:
                return float(cell.strip())
            except ValueError:
                return None
        return None

    numbers = [_as_number(c) for c in non_empty]
    # A spacer row has EVERY populated cell numeric and no text label. This
    # covers both the all-numeric case and, as a strict subset, the contiguous
    # ``1..k`` column-numbering run -- both are spacers, never label rows. Any
    # non-numeric (None) populated cell means it is not a spacer.
    return all(num is not None for num in numbers)


def _is_period_value(cell: Any) -> bool:
    """True when a cell IS an accounting period / date / year label.

    Full-match (not substring) so reference/invoice codes that merely embed a
    year (``INV-2024-0007``, ``Form 2020``) are not misread as period headers.
    """
    if isinstance(cell, (datetime.date, datetime.datetime)):
        return True
    if isinstance(cell, str):
        return bool(_PERIOD_RE.match(cell.strip()))
    return False


def _is_period_header_row(row: list[Any]) -> bool:
    """True when a row is a period/date header (the bulk of its cells are years/dates).

    Financial-report exports place a single date header (``2024-12-31 ...``)
    above a block of sub-sections; we use this to let a following data-first
    section inherit those column labels instead of guessing names.
    """
    non_empty = [c for c in row if c not in ("", None)]
    if len(non_empty) < _MIN_HEADER_NON_EMPTY:
        return False
    period = sum(1 for c in non_empty if _is_period_value(c))
    return period >= 2 and period * 5 >= len(non_empty) * 3  # >= 60% period-like


def _populated_cols(row: list[Any]) -> set[int]:
    return {c for c, v in enumerate(row) if v not in ("", None)}


class ExcelReader:
    formats = ("xlsx", "xls", "ods")

    async def enumerate_tables(self, source_path: str, rules: TableExtractionRules) -> list[ProposedTable]:
        return await asyncio.to_thread(self._enumerate_sync, source_path, rules)

    async def materialise(
        self,
        source_path: str,
        table: ProposedTable,
        target_parquet_key: str,
        *,
        workspace_locale: str,
        type_infer_sample_rows: int,
        max_title_rows: int = 3,
    ) -> MaterialiseResult:
        return await asyncio.to_thread(
            self._materialise_sync,
            source_path,
            table,
            target_parquet_key,
            workspace_locale,
            type_infer_sample_rows,
            max_title_rows,
        )

    # ------------------------------------------------------------------
    # Public utilities -- exposed for unit tests
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitise(name: str) -> str:
        return _NAME_SAFE_RE.sub("_", name).strip("_") or "sheet"

    @staticmethod
    def _extract_sections(rows: list[list[Any]]) -> list[dict[str, Any]]:
        """Segment a sheet's rows into tabular sections.

        Each returned dict has:
          * ``label``            -- best-guess section name (str)
          * ``header_row_idx``   -- index of the header row (int)
          * ``data_start_idx``   -- inclusive (int) == header_row_idx + 1
          * ``data_end_idx``     -- exclusive (int)
          * ``n_cols``           -- size of the union of populated column
                                    indices ACROSS the section (header +
                                    data rows). Dashboard XLSX layouts use
                                    merged cells, so the header row alone
                                    underreports the real width -- the
                                    label column often only fills in on
                                    the data rows below.
          * ``n_data_rows``      -- count of non-empty rows below the header
        """
        sections: list[dict[str, Any]] = []
        i = 0
        pending_label: str | None = None
        last_period_header_idx: int | None = None
        n = len(rows)
        while i < n:
            row = rows[i]
            non_empty = [c for c in row if c not in ("", None)]
            if len(non_empty) == 0:
                i += 1
                continue
            if len(non_empty) == 1 and isinstance(non_empty[0], str):
                # Single-cell string row = potential label
                pending_label = str(non_empty[0]).strip()
                i += 1
                continue
            if len(non_empty) < _MIN_HEADER_NON_EMPTY:
                i += 1
                continue

            # Multi-cell row = section header candidate.
            #
            # A naive reader takes the FIRST >=2-non-empty row as the header.
            # But dashboard exports sometimes inject a numeric spacer / column-
            # numbering row (e.g. ``1 2 3 4``) just above the real label band
            # (HDR-MULTIROW). If we treat that spacer as the header, the real
            # labels become data and columns get opaque positional names. So
            # when this candidate looks like a numeric/contiguous spacer, peek
            # a small window ahead and prefer the first following row that is
            # clearly a string-label row. We only skip the candidate when such
            # a better row exists -- genuinely numeric / period / date headers
            # (no string-label row just below) are left untouched, as are
            # single-row sheets.
            own_header_idx = i
            if _is_numeric_spacer_row(row) and not _looks_like_label_row(row):
                look_end = min(i + 1 + _HEADER_LOOKAHEAD, n)
                for la in range(i + 1, look_end):
                    la_ne = [c for c in rows[la] if c not in ("", None)]
                    if len(la_ne) == 0:
                        # A blank row before any label row means the spacer is
                        # really the last populated row -- stop looking ahead.
                        break
                    if len(la_ne) >= _MIN_HEADER_NON_EMPTY and _looks_like_label_row(rows[la]):
                        # Found a better string-label header just below; treat
                        # the skipped numeric/title rows as pre-header.
                        own_header_idx = la
                        break

            # Period-header inheritance. Financial-report exports (Orbis/BvD,
            # etc.) place ONE date header (``2024-12-31  2023-12-31 ...``) above
            # a block of sub-sections (P&L, ratios, ...), each introduced by its
            # own title. Section-splitting starts each sub-section at its first
            # DATA row, orphaning that shared header above the title -- so the
            # value columns get opaque/guessed names instead of the years. When
            # a section starts directly with data (its own header row is neither
            # label-like nor a period header) and a recent period header covers
            # its value columns, adopt that period header as this section's
            # column header and treat the section's own first row as data.
            own_is_period = _is_period_header_row(rows[own_header_idx])
            own_is_label = _looks_like_label_row(rows[own_header_idx])
            header_row_idx = own_header_idx
            data_start = own_header_idx + 1
            inherited = False
            if (
                last_period_header_idx is not None
                and not own_is_label
                and not own_is_period
                and own_header_idx - last_period_header_idx <= _PERIOD_HEADER_MAX_DISTANCE
            ):
                sec_cols = _populated_cols(rows[own_header_idx])
                ph_cols = _populated_cols(rows[last_period_header_idx])
                extra = sec_cols - ph_cols
                # The period header must cover the section's value columns. The
                # ONLY column it may legitimately not cover is a row-label column
                # to the LEFT of the period columns -- never a trailing value
                # column (that would shift the inherited year labels by one).
                if len(ph_cols & sec_cols) >= _MIN_HEADER_NON_EMPTY and (
                    not extra or (len(extra) == 1 and min(extra) < min(ph_cols))
                ):
                    header_row_idx = last_period_header_idx
                    data_start = own_header_idx
                    inherited = True

            j = data_start
            consecutive_empty = 0
            data_end = j  # exclusive
            while j < n:
                row_j = rows[j]
                row_ne = [c for c in row_j if c not in ("", None)]
                if len(row_ne) == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= _SECTION_BREAK_EMPTY_ROWS:
                        break
                    j += 1
                    continue
                consecutive_empty = 0
                # Another single-cell string label closes this section.
                if len(row_ne) == 1 and isinstance(row_ne[0], str):
                    break
                data_end = j + 1
                j += 1

            # Maintain the active period header. A genuine period/date header
            # opens (or renews) a band that the following data-first sub-sections
            # inherit; a real label-headed table CLOSES the band so a stale date
            # header can't bleed into an unrelated (positionally-overlapping)
            # table further down.
            if own_is_period:
                last_period_header_idx = own_header_idx
            elif own_is_label:
                last_period_header_idx = None

            n_data_rows = data_end - data_start
            if n_data_rows >= 1:
                # Populated columns. For a contiguous section the header row is
                # part of the table, so include it. For an INHERITED header we
                # count only DATA columns, so a period the sub-section does not
                # report does not become an all-NULL column.
                populated_cols: set[int] = set() if inherited else set(_populated_cols(rows[header_row_idx]))
                for k in range(data_start, data_end):
                    populated_cols |= _populated_cols(rows[k])
                sections.append(
                    {
                        "label": pending_label or f"section_{len(sections):02d}",
                        "header_row_idx": header_row_idx,
                        "data_start_idx": data_start,
                        "data_end_idx": data_end,
                        "n_cols": len(populated_cols),
                        "n_data_rows": n_data_rows,
                    }
                )
                pending_label = None
            i = data_end
        return sections

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    @staticmethod
    def _enumerate_sync(source_path: str, rules: TableExtractionRules) -> list[ProposedTable]:
        # python-calamine ships in the optional 'file-readers' extra.
        from python_calamine import CalamineWorkbook  # pyright: ignore[reportMissingImports]

        wb = CalamineWorkbook.from_path(source_path)
        out: list[ProposedTable] = []
        allow = set(rules.sheet_allowlist) if rules.sheet_allowlist else None
        for sheet_name in wb.sheet_names:
            if allow is not None and sheet_name not in allow:
                continue
            sheet = wb.get_sheet_by_name(sheet_name)
            # Normalise leading fully-empty rows so section indices are stable
            # across re-ingests (HDR-UNSTABLE). The SAME normalisation runs in
            # ``_materialise_sync`` so the stored indices slice the same rows.
            rows = _normalise_leading_blanks(sheet.to_python(skip_empty_area=True))
            if not rows:
                continue

            sections = ExcelReader._extract_sections(rows)

            if not sections:
                # Truly empty / fully-non-tabular sheet -- skip.
                continue

            # Single-section sheet that covers most of the data ->
            # name the table after the sheet, identical to old behavior.
            covers_whole_sheet = (
                len(sections) == 1
                and sections[0]["header_row_idx"] <= 3
                and sections[0]["data_end_idx"] >= len(rows) - 2
            )
            if covers_whole_sheet:
                s = sections[0]
                out.append(
                    ProposedTable(
                        name=ExcelReader._sanitise(sheet_name),
                        sheet_or_json_path=ExcelReader._section_path(sheet_name, s),
                        n_columns=s["n_cols"],
                        n_rows_estimate=s["n_data_rows"],
                    )
                )
                continue

            # Multi-section sheet -- one ProposedTable per section.
            sanitised_sheet = ExcelReader._sanitise(sheet_name)
            used_names: dict[str, int] = {}
            for s in sections:
                base = ExcelReader._sanitise(s["label"])[:64] or "section"
                candidate = f"{sanitised_sheet}__{base}"
                # Collide-disambiguate
                idx = used_names.get(candidate, 0)
                final_name = f"{candidate}_{idx + 1}" if idx > 0 else candidate
                used_names[candidate] = idx + 1
                out.append(
                    ProposedTable(
                        name=final_name,
                        sheet_or_json_path=ExcelReader._section_path(sheet_name, s),
                        n_columns=s["n_cols"],
                        n_rows_estimate=s["n_data_rows"],
                    )
                )
        return out

    @staticmethod
    def _section_path(sheet_name: str, s: dict[str, Any]) -> str:
        """Encode a section span. ``[h:e]`` when header+data are contiguous,
        ``[h:ds:e]`` when the header row is inherited (not adjacent to data)."""
        h, ds, e = s["header_row_idx"], s["data_start_idx"], s["data_end_idx"]
        return f"{sheet_name}#section[{h}:{e}]" if ds == h + 1 else f"{sheet_name}#section[{h}:{ds}:{e}]"

    @staticmethod
    def _parse_section_path(path: str) -> tuple[str, int | None, int | None, int | None]:
        """Split a section path -> ``(sheet, header_idx, data_start, data_end)``.

        Accepts both ``<sheet>#section[<header>:<end>]`` (contiguous; data starts
        at ``header+1``) and ``<sheet>#section[<header>:<data_start>:<end>]`` (an
        inherited period header that is NOT adjacent to its data). For backward
        compat, a plain sheet name (no ``#section[...]``) returns all ``None``.
        """
        m = _SECTION_RE.match(path or "")
        if not m:
            return path or "", None, None, None
        header_idx = int(m.group("a"))
        if m.group("c") is not None:
            data_start, data_end = int(m.group("b")), int(m.group("c"))
        else:
            data_start, data_end = header_idx + 1, int(m.group("b"))
        return m.group("sheet"), header_idx, data_start, data_end

    @staticmethod
    def _materialise_sync(
        source_path: str,
        table: ProposedTable,
        target_parquet_key: str,
        workspace_locale: str,
        type_infer_sample_rows: int,
        max_title_rows: int,
    ) -> MaterialiseResult:
        import csv

        import duckdb

        # python-calamine ships in the optional 'file-readers' extra.
        from python_calamine import CalamineWorkbook  # pyright: ignore[reportMissingImports]

        Path(target_parquet_key).parent.mkdir(parents=True, exist_ok=True)
        sheet_name, header_idx, data_start, data_end = ExcelReader._parse_section_path(
            table.sheet_or_json_path or table.name
        )
        wb = CalamineWorkbook.from_path(source_path)
        sheet = wb.get_sheet_by_name(sheet_name)
        # Apply the SAME leading-blank normalisation used at enumerate time so
        # the stored section indices slice the intended rows (HDR-UNSTABLE).
        rows = _normalise_leading_blanks(sheet.to_python(skip_empty_area=True))

        inherited_header = False
        if header_idx is not None and data_end is not None:
            # Section-encoded path. The header row + the data rows, which may be
            # NON-contiguous when the header was inherited from a period header
            # above the section's title (financial-report layout). For the
            # common contiguous case (data_start == header_idx + 1) this is
            # exactly ``rows[header_idx:data_end]``.
            #
            # ``rows[header_idx]`` is a scalar index, so guard it: if the sheet
            # changed between enumerate and materialise (re-ingest drift -- the
            # raison d'être of HDR-UNSTABLE) the index can fall past the end. The
            # old slice degraded silently; we raise a contextual ValueError
            # instead of an opaque IndexError.
            if header_idx >= len(rows):
                raise ValueError(
                    f"sheet {sheet_name!r}: header row {header_idx} out of range "
                    f"(rows={len(rows)}) for table {table.name!r} "
                    f"(path={table.sheet_or_json_path!r}); sheet changed since enumerate?"
                )
            inherited_header = data_start != header_idx + 1
            section_rows = [rows[header_idx]] + rows[data_start:data_end]
        else:
            # Legacy / no-section path -- apply the merged-cell title heuristic.
            body_start = 0
            for i in range(min(max_title_rows, len(rows))):
                non_empty = sum(1 for c in rows[i] if c not in (None, ""))
                if non_empty <= 1:
                    body_start = i + 1
                else:
                    break
            section_rows = rows[body_start:]

        if not section_rows:
            raise ValueError(
                f"sheet {sheet_name!r} has no usable rows for "
                f"table {table.name!r} (path={table.sheet_or_json_path!r})"
            )

        # COMPACT to the populated column set. Dashboard-style XLSX
        # layouts (Orbis/BvD financial reports, Bloomberg / Refinitiv
        # exports, Excel "templates" that use merged cells for visual
        # framing, etc.) place real values at sparse, non-consecutive
        # column indices -- e.g. five yearly figures might land at
        # cols 18, 32, 51, 70, 91 with everything in between left
        # empty because the merged title cells span those gaps. A
        # naive trim to [min_col, max_col] would still leave dozens
        # of all-empty columns that defeat DuckDB header detection.
        # Compacting to ONLY the populated indices yields rows that
        # match the visual "5 yearly columns + label" view a human
        # sees in Excel.
        # For an inherited (non-contiguous) header, compact over the DATA rows
        # only -- a period the sub-section doesn't report must not survive as an
        # all-NULL year column just because the shared header names it.
        compact_rows = section_rows[1:] if inherited_header and len(section_rows) > 1 else section_rows
        populated: set[int] = set()
        for r in compact_rows:
            for col_idx, cell in enumerate(r):
                if cell not in ("", None):
                    populated.add(col_idx)
        if populated:
            keep = sorted(populated)
            section_rows = [[r[k] if k < len(r) else "" for k in keep] for r in section_rows]

        # Embedded newlines in Excel cells (multi-line addresses,
        # description paragraphs, etc.) trip up DuckDB's CSV dialect
        # sniffer even when the cell is double-quoted -- the sniffer
        # reads forward and gets confused about row boundaries. We
        # flatten any newline/CR inside a cell to a single space before
        # writing. Lossy on layout but preserves the information.
        def _flatten(cell: Any) -> str:
            if cell is None:
                return ""
            s = str(cell)
            if "\n" in s or "\r" in s:
                s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            return s

        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", newline="", delete=False, encoding="utf-8"
        ) as tmp:
            writer = csv.writer(tmp)
            for r in section_rows:
                writer.writerow([_flatten(c) for c in r])
            tmp_path = tmp.name

        try:
            conn = duckdb.connect()
            try:
                src = tmp_path.replace("'", "''")
                tgt = target_parquet_key.replace("'", "''")
                # We control the temp file -- ``csv.writer`` always
                # emits comma-delimited, double-quoted CSV. Telling
                # DuckDB the dialect explicitly avoids two failure
                # modes on dashboard-XLSX sections:
                #  * Single-column sections (e.g. an "Industria y
                #    actividades" two-cell row) defeat DuckDB's dialect
                #    sniffer because the sniffer needs >=2 columns to
                #    distinguish ``,`` from ``;`` / ``\t`` / ``|``.
                #  * ``max_line_size`` is bumped above DuckDB's default
                #    (~2 MB) because real XLSX cells routinely contain
                #    paragraph-length descriptions or comma-joined
                #    regulatory-codes lists.
                conn.execute(
                    f"COPY (SELECT * FROM read_csv_auto('{src}', "
                    f"sample_size={type_infer_sample_rows}, "
                    f"auto_detect=true, ignore_errors=true, "
                    f"null_padding=true, "
                    f"delim=',', quote='\"', escape='\"', "
                    f"max_line_size=10000000)) "
                    f"TO '{tgt}' (FORMAT PARQUET, COMPRESSION 'snappy')"
                )
                rows_ct_row = conn.execute(
                    "SELECT count(*) FROM read_parquet(?)", [target_parquet_key]
                ).fetchone()
                rows_ct = rows_ct_row[0] if rows_ct_row else 0
                schema = conn.execute(
                    "SELECT * FROM (DESCRIBE SELECT * FROM read_parquet(?))",
                    [target_parquet_key],
                ).fetchall()
                columns = tuple(
                    ColumnSchema(name=r[0], data_type=r[1], is_nullable=(r[2] == "YES"), position=i)
                    for i, r in enumerate(schema)
                )
            finally:
                conn.close()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        byte_size = Path(target_parquet_key).stat().st_size
        return MaterialiseResult(
            target_parquet_key=target_parquet_key,
            parquet_byte_size=byte_size,
            n_rows_actual=rows_ct,
            columns=columns,
        )
