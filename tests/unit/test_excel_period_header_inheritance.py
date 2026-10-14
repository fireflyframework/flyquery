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

"""Unit tests for period-header inheritance in the XLSX section extractor.

Financial-report exports (Orbis/BvD) place ONE date header above a block of
sub-sections; section-splitting orphans that header above each sub-section's
title. These tests pin the inheritance behavior + its guards (no false
inherit, leftmost-label-only, legacy path round-trip).
"""

from __future__ import annotations

import datetime

from flyquery.core.services.ingestion.readers.excel_reader import (
    ExcelReader,
    _is_period_header_row,
    _is_period_value,
)


def test_is_period_value_full_match_rejects_embedded_year_codes() -> None:
    for ok in ("2024", "2024-12-31", "FY2024", "Q1 2024", "H1 2023"):
        assert _is_period_value(ok), ok
    assert _is_period_value(datetime.datetime(2024, 12, 31))
    # Codes / addresses that merely *contain* a year must NOT be period values.
    for bad in ("INV-2024-0007", "Form 2020", "2001 Main St", "REG-2019-X", "86.21", "Andalucia"):
        assert not _is_period_value(bad), bad


def test_is_period_header_row_requires_majority_period_cells() -> None:
    assert _is_period_header_row(["", "2024", "2023", "2022"])
    assert _is_period_header_row([datetime.date(2024, 12, 31), datetime.date(2023, 12, 31)])
    # A single year among labels is not a header.
    assert not _is_period_header_row(["Founded 2024", "CEO", "Revenue"])


def _orbis_like_rows() -> list[list[object]]:
    """A miniature Orbis-style sheet:

    one date header governs a data-first sub-section introduced by its own
    title; then a label-headed table closes the band; then another data-first
    section that must NOT inherit the (now stale) date header.
    """
    return [
        ["Financial data", "", "", ""],  # 0 title
        ["", "2024", "2023", "2022"],  # 1 period header (cols 1-3)
        ["Profit & Loss", "", "", ""],  # 2 title
        ["Revenue", 100, 90, 80],  # 3 data-first -> inherits row 1
        ["Costs", 40, 30, 20],  # 4 data
        ["", "", "", ""],  # 5 blank
        ["", "", "", ""],  # 6 blank (section break)
        ["Board", "", "", ""],  # 7 title
        ["Name", "Role", "", ""],  # 8 label header (closes the period band)
        ["Alice", "CEO", "", ""],  # 9 data
        ["", "", "", ""],  # 10 blank
        ["", "", "", ""],  # 11 blank
        ["Extra metrics", "", "", ""],  # 12 title
        ["Metric A", 1, 2, 3],  # 13 data-first, columns OVERLAP the date header
        ["Metric B", 4, 5, 6],  # 14 data
    ]


def test_data_first_section_inherits_period_header() -> None:
    secs = ExcelReader._extract_sections(_orbis_like_rows())
    pnl = next(s for s in secs if s["label"] == "Profit & Loss")
    # Header is the date row (1), data is non-contiguous (starts at 3).
    assert pnl["header_row_idx"] == 1
    assert pnl["data_start_idx"] == 3
    assert pnl["data_end_idx"] == 5


def test_label_headed_table_does_not_inherit_and_closes_the_band() -> None:
    secs = ExcelReader._extract_sections(_orbis_like_rows())
    board = next(s for s in secs if s["label"] == "Board")
    # Board has its OWN label header -> contiguous, no inheritance.
    assert board["data_start_idx"] == board["header_row_idx"] + 1

    # The later "Extra metrics" section shares column positions with the date
    # header, but the band was CLOSED by the Board table -> it must NOT inherit.
    extra = next(s for s in secs if s["label"] == "Extra metrics")
    assert extra["data_start_idx"] == extra["header_row_idx"] + 1


def test_section_path_round_trip_contiguous_and_inherited() -> None:
    # Contiguous -> 2-index form (byte-identical to legacy).
    s_contig = {"header_row_idx": 5, "data_start_idx": 6, "data_end_idx": 9}
    p = ExcelReader._section_path("Sheet1", s_contig)
    assert p == "Sheet1#section[5:9]"
    assert ExcelReader._parse_section_path(p) == ("Sheet1", 5, 6, 9)

    # Inherited (non-contiguous) -> 3-index form.
    s_inh = {"header_row_idx": 1, "data_start_idx": 3, "data_end_idx": 5}
    p2 = ExcelReader._section_path("Sheet1", s_inh)
    assert p2 == "Sheet1#section[1:3:5]"
    assert ExcelReader._parse_section_path(p2) == ("Sheet1", 1, 3, 5)


def test_parse_section_path_legacy_and_plain() -> None:
    # Legacy 2-index path still parses (already-stored tables).
    assert ExcelReader._parse_section_path("S#section[2:7]") == ("S", 2, 3, 7)
    # Plain sheet name -> all None.
    assert ExcelReader._parse_section_path("JustASheet") == ("JustASheet", None, None, None)
