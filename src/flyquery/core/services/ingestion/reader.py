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

"""FileReader port (spec §9.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class UnsupportedFormatError(ValueError):
    """Raised when (format, compression) pair is not handled by any reader."""


@dataclass(frozen=True)
class TableExtractionRules:
    """User-driven overrides on parsing. Empty = use heuristic defaults."""

    sheet_allowlist: tuple[str, ...] = ()
    json_paths: tuple[str, ...] = ()
    header_skip_rows: int = 0


@dataclass(frozen=True)
class ProposedTable:
    """Logical table inside an upload (1 from CSV; N from XLSX sheets)."""

    name: str
    sheet_or_json_path: str | None
    n_columns: int
    n_rows_estimate: int


@dataclass(frozen=True)
class ColumnSchema:
    """Column emitted by the parse step (post-DuckDB type inference)."""

    name: str
    data_type: str
    is_nullable: bool
    position: int
    # The source's ORIGINAL header before any rename (e.g. an Excel year header
    # '2024' that the column-name proposer collapsed to ``year_1``). Preserved so
    # the query layer can recover what a renamed column actually meant, instead of
    # relying on a fixed ordinal convention. None when the name was not renamed.
    original_name: str | None = None


@dataclass(frozen=True)
class MaterialiseResult:
    """Result of materialising one ProposedTable to a Parquet snapshot."""

    target_parquet_key: str  # object-store key (relative to base)
    parquet_byte_size: int
    n_rows_actual: int
    columns: tuple[ColumnSchema, ...]


class FileReader(Protocol):
    """Per-format reader. Adapters: csv, excel, json, parquet, avro, orc, arrow.

    Each reader handles uncompressed input by default; the compression layer is
    decorator-wrapped via core.services.ingestion.compression.
    """

    @property
    def formats(self) -> tuple[str, ...]:  # e.g., ("csv", "tsv")
        """Formats this reader handles. Read-only so concrete readers can
        declare a narrower literal tuple (``("csv", "tsv")``)."""
        ...

    async def enumerate_tables(
        self, source_path: str, rules: TableExtractionRules
    ) -> list[ProposedTable]: ...

    async def materialise(
        self,
        source_path: str,
        table: ProposedTable,
        target_parquet_key: str,
        *,
        workspace_locale: str,
        type_infer_sample_rows: int,
        max_title_rows: int = 3,
    ) -> MaterialiseResult: ...
