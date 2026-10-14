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

"""ScopeGuard — enforce token scopes, AST classification, table-kind, and dataset allowlist.

Guards the query execution path to prevent:
- Multi-statement SQL (always rejected)
- DDL via /query (always rejected; allowed only via internal :derive)
- DML on UPLOADED tables (always rejected)
- DML on DERIVED tables without flyquery.derived:write scope
- SELECT without flyquery.query:read (or flyquery.sql:execute or wildcard *)
- Tables outside the caller's dataset allowlist
"""

from __future__ import annotations

from flyquery.core.services.execution.ast_classifier import AstClassification


class ScopeGuardError(PermissionError):
    """Raised when a SQL statement violates scope or structural constraints."""


class ScopeGuard:
    """Enforce: (scopes ∩ AST classification ∩ table.kind ∩ dataset allowlist).

    All ``check`` parameters are keyword-only so call sites can't accidentally
    transpose arguments.
    """

    def check(
        self,
        *,
        classification: AstClassification,
        scopes: set[str],
        table_kinds_by_name: dict[str, str],
        dataset_allowlist: set[str] | None,
        dataset_of_table: dict[str, str],
    ) -> None:
        """Validate the SQL against all gate conditions.

        :param classification: result from :class:`AstClassifier`
        :param scopes: the caller's granted scope strings
        :param table_kinds_by_name: maps unqualified table name → kind ("UPLOADED" | "DERIVED")
        :param dataset_allowlist: if set, only tables whose dataset is in this set are allowed
        :param dataset_of_table: maps unqualified table name → dataset slug/id
        :raises ScopeGuardError: on any violation
        """
        # 1. Single-statement only
        if not classification.single_statement:
            raise ScopeGuardError("multi-statement SQL not allowed")

        # 2. DDL never allowed via /query
        if classification.classification == "DDL":
            raise ScopeGuardError("DDL not allowed via /query (use internal :derive endpoint)")
        if classification.classification == "UNKNOWN" or classification.unsupported_sql:
            raise ScopeGuardError("unsupported SQL statement, function, or table source")

        # 3. DML rules
        if classification.classification in ("INSERT", "UPDATE", "DELETE"):
            for tbl in classification.table_refs:
                kind = table_kinds_by_name.get(tbl)
                if kind == "UPLOADED":
                    raise ScopeGuardError(f"DML on UPLOADED table {tbl!r} not allowed (use re-upload)")
                if kind != "DERIVED":
                    raise ScopeGuardError(
                        f"DML on unknown table {tbl!r} — only DERIVED tables support writes"
                    )
            # Require write scope for derived tables
            if "flyquery.derived:write" not in scopes:
                raise ScopeGuardError("missing flyquery.derived:write scope for DML on DERIVED table")
        else:
            # 4. SELECT: require read scope
            if not (scopes & {"flyquery.query:read", "flyquery.sql:execute", "*"}):
                raise ScopeGuardError("missing flyquery.query:read scope (or flyquery.sql:execute / *)")
            if any(
                table_kinds_by_name.get(tbl) not in {"UPLOADED", "DERIVED"}
                for tbl in classification.table_refs
            ):
                raise ScopeGuardError("SQL source is not a registered table")

        # 5. Dataset allowlist
        if dataset_allowlist is not None:
            for tbl in classification.table_refs:
                ds = dataset_of_table.get(tbl)
                if ds is None or ds not in dataset_allowlist:
                    raise ScopeGuardError(
                        f"table {tbl!r} (dataset {ds!r}) is not in the caller's dataset allowlist"
                    )
