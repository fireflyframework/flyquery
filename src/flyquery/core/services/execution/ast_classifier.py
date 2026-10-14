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

"""AST classifier using sqlglot to classify SQL statements.

Parses SQL with the DuckDB dialect (``read="duckdb"``) and returns an
``AstClassification`` describing the statement type, table/column references,
and structural properties.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import sqlglot
import sqlglot.expressions  # noqa: F401 — ensures exp alias is populated on sqlglot module
from sqlglot.optimizer.scope import Scope, traverse_scope

_PURE_FUNCTIONS = frozenset(
    {
        "SUM",
        "COUNT",
        "AVG",
        "MIN",
        "MAX",
        "COUNT_IF",
        "APPROX_DISTINCT",
        "STDDEV",
        "STDDEV_POP",
        "STDDEV_SAMP",
        "VARIANCE",
        "VAR_POP",
        "VAR_SAMP",
        "MEDIAN",
        "BOOL_AND",
        "BOOL_OR",
        "LOGICAL_AND",
        "LOGICAL_OR",
        "ANY_VALUE",
        "COALESCE",
        "NULLIF",
        "CAST",
        "TRY_CAST",
        "CASE",
        "IF",
        "DATE_TRUNC",
        "TIMESTAMP_TRUNC",
        "DATE_DIFF",
        "DATEDIFF",
        "EXTRACT",
        "YEAR",
        "MONTH",
        "DAY",
        "DAY_OF_MONTH",
        "DAY_OF_WEEK",
        "DAY_OF_YEAR",
        "WEEK",
        "WEEK_OF_YEAR",
        "QUARTER",
        "TIME_TO_STR",
        "STR_TO_TIME",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
        "CURRENT_TIME",
        "ABS",
        "ROUND",
        "FLOOR",
        "CEIL",
        "CEILING",
        "POWER",
        "POW",
        "SQRT",
        "LOG",
        "LN",
        "EXP",
        "SIGN",
        "GREATEST",
        "LEAST",
        "LOWER",
        "UPPER",
        "LENGTH",
        "CHAR_LENGTH",
        "TRIM",
        "LTRIM",
        "RTRIM",
        "CONCAT",
        "CONCAT_WS",
        "SUBSTRING",
        "STR_POSITION",
        "REPLACE",
        "REGEXP_REPLACE",
        "REGEXP_EXTRACT",
        "REGEXP_LIKE",
        "SPLIT",
        "SPLIT_PART",
        "STARTS_WITH",
        "ENDS_WITH",
        "ARRAY",
        "ARRAY_SIZE",
        "STRUCT",
        "STRUCT_EXTRACT",
        "ROW_NUMBER",
        "RANK",
        "DENSE_RANK",
        "LAG",
        "LEAD",
        "FIRST_VALUE",
        "LAST_VALUE",
        "NTH_VALUE",
        "GROUP_CONCAT",
        "STRING_AGG",
    }
)


@dataclass(frozen=True)
class AstClassification:
    """The result of classifying a SQL string via the AST."""

    classification: Literal["SELECT", "INSERT", "UPDATE", "DELETE", "DDL", "UNKNOWN"]
    single_statement: bool
    table_refs: tuple[str, ...]  # unqualified table names referenced in the statement
    column_refs: tuple[str, ...]  # column names referenced in the statement
    has_subquery: bool
    unsupported_sql: bool = False


class AstClassifier:
    """Classifies a SQL string using sqlglot with the DuckDB dialect."""

    def classify(self, sql: str) -> AstClassification:
        """Parse and classify ``sql``.

        :param sql: raw SQL string
        :return: :class:`AstClassification`; classification="UNKNOWN" on parse error
        """
        try:
            statements = sqlglot.parse(sql, read="duckdb")
        except Exception:  # noqa: BLE001
            return AstClassification(
                classification="UNKNOWN",
                single_statement=False,
                table_refs=(),
                column_refs=(),
                has_subquery=False,
            )

        # sqlglot.parse("") returns [None] for an empty/whitespace-only input
        non_null = [s for s in statements if s is not None]
        if not non_null:
            return AstClassification(
                classification="UNKNOWN",
                single_statement=False,
                table_refs=(),
                column_refs=(),
                has_subquery=False,
            )

        single = len(non_null) == 1
        stmt = non_null[0]
        # sqlglot.parse() is typed to yield its internal ``Expr`` alias, which
        # pyright does not unify with the public ``Expression`` base below.
        kind = self._kind(stmt)  # pyright: ignore[reportArgumentType]

        exp = sqlglot.expressions
        try:
            cte_refs = {
                id(node)
                for scope in traverse_scope(stmt)
                for node, source in scope.selected_sources.values()
                if isinstance(source, Scope)
            }
        except Exception:
            return AstClassification("UNKNOWN", single, (), (), False, unsupported_sql=True)
        sources = list(stmt.find_all(exp.Table))
        tables = tuple(sorted({t.name for t in sources if t.name and id(t) not in cte_refs}))
        columns = tuple(sorted({c.name for c in stmt.find_all(sqlglot.expressions.Column) if c.name}))
        has_subquery = bool(list(stmt.find_all(sqlglot.expressions.Subquery)))
        # Typed parser nodes can also read files; admission is by reviewed function name, never node type alone.
        unsupported = any(
            (function.name.upper() if isinstance(function, exp.Anonymous) else function.sql_name())
            not in _PURE_FUNCTIONS
            for function in stmt.find_all(exp.Func)
        ) or any(
            not isinstance(table.this, exp.Identifier)
            or table.catalog
            or (table.db and table.db.lower() != "main")
            for table in sources
        )

        return AstClassification(
            classification=kind,
            single_statement=single,
            table_refs=tables,
            column_refs=columns,
            has_subquery=has_subquery,
            unsupported_sql=bool(unsupported),
        )

    @staticmethod
    def _kind(
        # ``Expression`` is the public base class but sqlglot omits it from
        # ``expressions.__all__``, so pyright flags it as a private import.
        stmt: sqlglot.expressions.Expression,  # pyright: ignore[reportPrivateImportUsage]
    ) -> Literal["SELECT", "INSERT", "UPDATE", "DELETE", "DDL", "UNKNOWN"]:
        if isinstance(stmt, sqlglot.expressions.Select):
            return "SELECT"
        # ``UNION ALL`` / ``UNION`` / ``INTERSECT`` / ``EXCEPT`` are
        # also read-only set operations -- classify them as SELECT so
        # the scope guard treats them like a read and the queries
        # CHECK constraint (which only allows SELECT/INSERT/UPDATE/
        # DELETE/DDL) doesn't reject them with UNKNOWN.
        if isinstance(
            stmt,
            (sqlglot.expressions.Union, sqlglot.expressions.Intersect, sqlglot.expressions.Except),
        ):
            return "SELECT"
        if isinstance(stmt, sqlglot.expressions.Insert):
            return "INSERT"
        if isinstance(stmt, sqlglot.expressions.Update):
            return "UPDATE"
        if isinstance(stmt, sqlglot.expressions.Delete):
            return "DELETE"
        if isinstance(
            stmt, (sqlglot.expressions.Create, sqlglot.expressions.Drop, sqlglot.expressions.Alter)
        ):
            return "DDL"
        return "UNKNOWN"
