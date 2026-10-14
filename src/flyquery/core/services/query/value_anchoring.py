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

"""Value-anchoring helpers for the NL->SQL pipeline (dataset-agnostic).

These pure functions are the backbone of the grounding/generation quality
improvements. They turn the per-column artifacts the ingest pipeline already
computes (``profile_json.top_values`` / ``min`` / ``max`` /
``distinct_estimate``, ``sample_values_json``, ``governance_json.semantic_type``)
into prompt text the SQL writer can copy literals from, resolve question
entities to the columns that store them, and detect degenerate / unsafe SQL.

Nothing here hardcodes a column name, label, or domain assumption -- every
function operates on whatever the dataset's own profiling produced.
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlglot
from sqlglot import exp

# ----------------------------------------------------------------------
# Semantic role (measure vs dimension vs time)
# ----------------------------------------------------------------------

_MEASURE_TYPES = {
    "amount",
    "count",
    "decimal",
    "ratio",
    "percentage",
    "percent",
    "rate",
    "score",
    "currency",
    "measure",
    "quantity",
    "number",
    "money",
    "metric",
}
_TIME_TYPES = {"year", "quarter", "month", "week", "day", "date", "datetime", "period", "fiscal_year"}
_DIMENSION_TYPES = {
    "enum",
    "tag",
    "name",
    "code",
    "category",
    "identifier",
    "id",
    "boolean",
    "label",
    "text",
    "status",
    "geo",
    "country",
    "region",
}


def semantic_role(semantic_type: str | None) -> str | None:
    """Map an ingest-computed semantic_type to measure / time / dimension."""
    st = (semantic_type or "").strip().lower()
    if not st:
        return None
    if st in _TIME_TYPES:
        return "time"
    if st in _MEASURE_TYPES:
        return "measure"
    if st in _DIMENSION_TYPES:
        return "dimension"
    return None


def _as_obj(v: Any) -> Any:
    """JSONB columns usually arrive decoded; tolerate a str just in case."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return None
    return v


def coerce_profile(
    profile_json: Any,
    sample_values_json: Any,
    *,
    max_values: int = 25,
) -> dict:
    """Return ``{distinct, values, min, max}`` from the ingest artifacts.

    ``values`` is the de-duplicated, capped list of distinct/top values for a
    low-cardinality column (drawn from ``profile_json.top_values`` first, then
    ``sample_values_json``). ``min``/``max`` come from the numeric profile.
    """
    samples = _as_obj(sample_values_json)
    # The ingestion PII policy uses [] to revoke sample access. Profile
    # values and numeric ranges must not undo that decision in prompts.
    profile = {} if samples == [] else (_as_obj(profile_json) or {})
    samples = samples or []
    distinct = profile.get("distinct_estimate") if isinstance(profile, dict) else None
    mn = profile.get("min") if isinstance(profile, dict) else None
    mx = profile.get("max") if isinstance(profile, dict) else None

    raw: list = []
    tv = profile.get("top_values") if isinstance(profile, dict) else None
    if isinstance(tv, list):
        for item in tv:
            if isinstance(item, dict) and "value" in item:
                raw.append(item["value"])
            else:
                raw.append(item)
    if not raw and isinstance(samples, list):
        raw = list(samples)

    seen: set[str] = set()
    values: list[str] = []
    for v in raw:
        s = "NULL" if v is None else str(v)
        if s not in seen:
            seen.add(s)
            values.append(s)
        if len(values) >= max_values:
            break
    # mixed_sign: the column stores BOTH negative and positive numbers (so some
    # categories/line-items are already stored as negatives). Derived purely from
    # the min/max the profiler already computed -- no domain assumption.
    mixed = False
    try:
        if mn is not None and mx is not None and float(mn) < 0 < float(mx):
            mixed = True
    except (TypeError, ValueError):
        pass
    return {"distinct": distinct, "values": values, "min": mn, "max": mx, "mixed_sign": mixed}


def render_column_catalog_line(
    qualified_name: str,
    data_type: str | None,
    semantic_type: str | None,
    profile_json: Any,
    sample_values_json: Any,
    *,
    max_values: int = 25,
    char_budget: int = 280,
) -> str:
    """Render one column's value catalogue line for a prompt.

    Examples::

        `t.Year` (VARCHAR, time, 4 distinct) values: 'FY23','FY24','FY25','FY26'
        `t.P&L Line` (VARCHAR, dimension, 20 distinct) values: 'Total Revenue','Manpower',...
        `t.FY` (DOUBLE, measure) range: -184.90 .. 361.49
    """
    col = qualified_name.rsplit(".", 1)[-1]
    prof = coerce_profile(profile_json, sample_values_json, max_values=max_values)
    role = semantic_role(semantic_type)
    head_bits = [data_type or "?"]
    if role:
        head_bits.append(role)
    if prof["distinct"] is not None:
        head_bits.append(f"{prof['distinct']} distinct")
    head = f"`{col}` ({', '.join(head_bits)})"

    if prof["values"]:
        vtext = ", ".join(_q(v) for v in prof["values"])
        if len(vtext) > char_budget:
            vtext = vtext[:char_budget].rsplit(",", 1)[0] + ", …"
        return f"{head} values: {vtext}"
    if prof["min"] is not None or prof["max"] is not None:
        return f"{head} range: {_num(prof['min'])} .. {_num(prof['max'])}"
    return head


def render_catalog_from_meta(qualified_name: str, meta: dict, *, char_budget: int = 320) -> str:
    """Render a catalogue line from an already-coerced col_catalog item.

    ``meta`` keys: data_type, semantic_type, distinct, values, min, max.
    """
    col = qualified_name.rsplit(".", 1)[-1]
    bits = [meta.get("data_type") or "?"]
    role = semantic_role(meta.get("semantic_type"))
    if role:
        bits.append(role)
    if meta.get("distinct") is not None:
        bits.append(f"{meta['distinct']} distinct")
    # Echo the source's ORIGINAL header (pre-rename) when the ingest renamed the
    # column (e.g. an Excel year header collapsed to year_1). Lets the model know
    # what year_1 actually was, instead of relying on a fixed ordinal convention.
    oh = meta.get("original_header")
    if oh:
        bits.append(f"original header: {_q(str(oh))}")
    head = f"`{col}` ({', '.join(bits)})"
    vals = meta.get("values") or []
    if vals:
        vt = ", ".join(_q(str(v)) for v in vals)
        if len(vt) > char_budget:
            vt = vt[:char_budget].rsplit(",", 1)[0] + ", …"
        return f"{head} values: {vt}"
    if meta.get("min") is not None or meta.get("max") is not None:
        line = f"{head} range: {_num(meta.get('min'))} .. {_num(meta.get('max'))}"
        if role == "measure" and meta.get("mixed_sign"):
            line += (
                " — SIGNED (stores both negatives and positives; some line-items are already stored negative)"
            )
        return line
    return head


def _q(v: str) -> str:
    if v == "NULL":
        return "NULL"
    return "'" + v.replace("'", "''") + "'"


def _num(v: Any) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


# ----------------------------------------------------------------------
# Entity extraction + value->column resolution (G3)
# ----------------------------------------------------------------------

_STOP = {
    "the",
    "and",
    "for",
    "with",
    "que",
    "los",
    "las",
    "del",
    "una",
    "uno",
    "what",
    "which",
    "how",
    "many",
    "cual",
    "cuales",
    "cuantos",
    "cuanto",
    "team",
    "equipo",
    "average",
    "promedio",
    "total",
    "year",
    "ratio",
}


def extract_question_literals(question: str) -> list[str]:
    """Pull candidate entity literals out of a NL question (heuristic, generic).

    Captures quoted phrases, ALL-CAPS / Capitalized multi-word runs (proper
    nouns, person names, product/brand/business-unit names) and standalone
    upper-case codes. Over-extraction is fine -- the resolver only keeps
    literals that actually match a stored column value.
    """
    out: list[str] = []
    # quoted phrases
    for m in re.findall(r"['\"]([^'\"]{2,})['\"]", question):
        out.append(m.strip())
    # runs of capitalized / all-caps words (>=1 word), e.g. "FRANCISCO JAVIER ..."
    for m in re.findall(r"\b([A-ZÀ-Ý][\wÀ-ý&/.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ý&/.-]*)*)\b", question):
        tok = m.strip()
        if len(tok) >= 2 and tok.lower() not in _STOP:
            out.append(tok)
    # standalone all-caps tokens (OBU, DAPA, CVRM, RIV)
    for m in re.findall(r"\b([A-Z][A-Z0-9&/]{1,})\b", question):
        if m.lower() not in _STOP:
            out.append(m)
    # de-dup preserving order, drop pure substrings already covered
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq


def resolve_from_catalog(
    literals: list[str],
    col_catalog: list[dict],
) -> list[dict]:
    """Map literals to columns using already-fetched low-cardinality values.

    ``col_catalog`` items: ``{qualified_name, values: [str]}``. Returns
    ``[{literal, column, value}]`` for case-insensitive exact matches.
    """
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for lit in literals:
        ll = lit.lower()
        for c in col_catalog:
            for v in c.get("values", []) or []:
                vl = str(v).lower()
                if vl == ll or (len(ll) >= 4 and ll in vl) or (len(vl) >= 4 and vl in ll):
                    key = (lit.lower(), c["qualified_name"])
                    if key not in seen:
                        seen.add(key)
                        found.append({"literal": lit, "column": c["qualified_name"], "value": v})
                    break
    return found


# Words that signal a hierarchy / "reports-to" question, where the answer is the
# set of rows whose PARENT column equals the entity (the value that REPEATS), not
# the single identity row. Generic NL cues (EN + ES); the load-bearing signal is
# row-match cardinality (this only nudges the choice). Never reads the schema.
_HIERARCHY_INTENT = (
    "team of",
    "team for",
    "reports to",
    "report to",
    "direct reports",
    "reporting to",
    "under ",
    "manages",
    "managed by",
    "supervises",
    "supervised by",
    "led by",
    "in charge of",
    "members of",
    "people in",
    "headcount of",
    "size of the team",
    "roster of",
    "equipo de",
    "a cargo de",
    "a su cargo",
    "reportan a",
    "reporta a",
    "bajo ",
    "dirige",
    "dirigido por",
    "supervisa",
    "supervisado por",
    "depende de",
    "dependen de",
    "miembros de",
    "integrantes de",
    "dimensionamiento",
    "personas en",
)


def relationship_intent(question: str) -> bool:
    """True if the question is about a hierarchy / team / reporting relationship."""
    q = " " + (question or "").lower() + " "
    return any(kw in q for kw in _HIERARCHY_INTENT)


def _is_prefix_token(literal: str, value: str) -> bool:
    """True if ``literal`` is an anchored token-prefix of ``value``.

    'Field' prefixes 'Field Sales' / 'Field-Access' (boundary follows), but NOT
    'Fieldwork'. Case-insensitive. This is the structural definition of a term
    that fans out to several sub-values.
    """
    ll = literal.strip().lower()
    vl = str(value).strip().lower()
    if not ll or not vl or vl == ll or not vl.startswith(ll):
        return False
    nxt = vl[len(ll) : len(ll) + 1]
    return nxt == "" or not nxt.isalnum()


def resolve_value_groups(literals: list[str], col_catalog: list[dict]) -> list[dict]:
    """Map a question term to the FULL SET of catalogued values it umbrellas.

    When a literal is an anchored token-prefix of >=2 distinct values of the SAME
    column ('Field' -> {'Field Sales','Field Medical','Field Access',...}), return
    a group so the model filters the whole set, not a subset. Gated to 'pure
    umbrellas': skip a literal that is itself an exact stored value. ``truncated``
    flags that the column has more distinct values than were catalogued (so an
    IN-list would be incomplete and an anchored LIKE is safer). Dataset-agnostic:
    driven only by the column's own distinct values.
    """
    groups: list[dict] = []
    for lit in literals:
        ll = lit.strip().lower()
        if len(ll) < 2:
            continue
        for c in col_catalog:
            vals = [str(v) for v in (c.get("values") or [])]
            if not vals:
                continue
            if any(str(v).strip().lower() == ll for v in vals):
                continue  # the term IS a value -> plain entity, not an umbrella
            matches = [v for v in vals if _is_prefix_token(lit, v)]
            if len({m.lower() for m in matches}) >= 2:
                distinct = c.get("distinct")
                groups.append(
                    {
                        "literal": lit,
                        "column": c["qualified_name"],
                        "values": matches,
                        "truncated": bool(distinct is not None and distinct > len(vals)),
                    }
                )
    return groups


# ----------------------------------------------------------------------
# SQL analysis: degenerate detection, predicate literals, CTEs, functions
# ----------------------------------------------------------------------


def _parse(sql: str):
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # noqa: BLE001
        return None
    return tree


def is_degenerate_sql(sql: str) -> bool:
    """True if the SQL is a no-op: constant-false WHERE or constant-only aggregates.

    Catches placeholder queries like ``... WHERE 1=0`` and
    ``SUM(CASE WHEN ... THEN 0 ELSE 0 END)`` that execute cleanly but answer
    nothing. Structural + schema-agnostic.
    """
    tree = _parse(sql)
    if tree is None:
        return False

    # 1) constant-false WHERE
    for where in tree.find_all(exp.Where):
        cond = where.this
        if cond is None:
            continue
        try:
            from sqlglot.optimizer.simplify import simplify

            simp = simplify(cond.copy())
            if isinstance(simp, exp.Boolean) and simp.this is False:
                return True
        except Exception:  # noqa: BLE001
            pass
        if (
            isinstance(cond, exp.EQ)
            and isinstance(cond.this, exp.Literal)
            and isinstance(cond.expression, exp.Literal)
            and cond.this.name != cond.expression.name
        ):
            return True

    # 2) every projected expression is a constant aggregate / literal
    selects = list(tree.find_all(exp.Select))
    if selects:
        top = selects[0]
        exprs = [e for e in top.expressions]
        if exprs and all(_is_constant_projection(e) for e in exprs):
            return True
    return False


def _is_constant_projection(e: exp.Expression) -> bool:
    node = e.this if isinstance(e, exp.Alias) else e
    if isinstance(node, exp.Literal):
        return True
    if isinstance(node, exp.AggFunc):
        arg = node.this
        if isinstance(arg, exp.Literal):
            return True
        if isinstance(arg, exp.Case) and _case_all_same_literal(arg):
            return True
    return False


def _case_all_same_literal(case_expr: exp.Case) -> bool:
    lits: list[exp.Expression] = []
    for ifexpr in case_expr.args.get("ifs", []) or []:
        lits.append(ifexpr.args.get("true"))
    default = case_expr.args.get("default")
    if default is not None:
        lits.append(default)
    if not lits:
        return False
    names: set[str] = set()
    for lit in lits:
        if not isinstance(lit, exp.Literal):
            return False
        names.add(lit.name)
    return len(names) <= 1


def equality_predicate_columns(sql: str) -> list[str]:
    """Column names used in ``=`` / ``IN`` / ``LIKE`` predicates (for repair).

    These are the columns whose stored values the critic should re-check when a
    query executes but returns 0 rows.
    """
    tree = _parse(sql)
    if tree is None:
        return []
    cols: list[str] = []
    seen: set[str] = set()
    for pred in tree.find_all(exp.EQ, exp.In, exp.Like, exp.ILike):
        target = pred.this
        col = target.find(exp.Column) if target is not None else None
        if isinstance(col, exp.Column) and col.name and col.name.lower() not in seen:
            seen.add(col.name.lower())
            cols.append(col.name)
    return cols


def predicate_literals(sql: str) -> dict:
    """Return ``{column_name(lower): set(literal strings)}`` for =/IN predicates."""
    tree = _parse(sql)
    out: dict[str, set] = {}
    if tree is None:
        return out
    for pred in tree.find_all(exp.EQ, exp.In):
        target = pred.this
        col = target.find(exp.Column) if target is not None else None
        if not isinstance(col, exp.Column) or not col.name:
            continue
        lits: set = set()
        if isinstance(pred, exp.EQ) and isinstance(pred.expression, exp.Literal):
            lits.add(pred.expression.name)
        elif isinstance(pred, exp.In):
            for e in pred.expressions or []:
                if isinstance(e, exp.Literal):
                    lits.add(e.name)
        if lits:
            out.setdefault(col.name.lower(), set()).update(lits)
    return out


def group_coverage_gaps(sql: str, col_catalog: list[dict], literals: list[str]) -> list[dict]:
    """IN/= predicates that are a STRICT SUBSET of a detected value group (round-2 #7).

    Returns ``[{column, missing}]`` when the SQL listed SOME members of a value
    group the question umbrellas but not all. Advisory only.
    """
    groups = resolve_value_groups(literals, col_catalog)
    if not groups:
        return []
    preds = predicate_literals(sql)
    gaps: list[dict] = []
    for g in groups:
        colname = g["column"].rsplit(".", 1)[-1].lower()
        listed = preds.get(colname)
        if not listed:
            continue
        listed_l = {x.lower() for x in listed}
        group_vals = {str(v) for v in g["values"]}
        group_l = {v.lower() for v in group_vals}
        missing = [v for v in group_vals if v.lower() not in listed_l]
        if missing and (listed_l & group_l):  # listed some-but-not-all
            gaps.append({"column": g["column"], "missing": missing})
    return gaps


def cte_and_derived_names(sql: str) -> set[str]:
    """Names that are CTE aliases or derived-table/subquery aliases (not real tables)."""
    tree = _parse(sql)
    if tree is None:
        return set()
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        if cte.alias:
            names.add(cte.alias)
    for sub in tree.find_all(exp.Subquery):
        if sub.alias:
            names.add(sub.alias)
    return {n for n in names if n}


def referenced_columns(sql: str) -> list[str]:
    """Distinct column identifiers referenced anywhere in the SQL."""
    tree = _parse(sql)
    if tree is None:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for c in tree.find_all(exp.Column):
        if c.name and c.name.lower() not in seen:
            seen.add(c.name.lower())
            out.append(c.name)
    return out


def select_aliases(sql: str) -> set[str]:
    """Aliases defined in the query (SELECT-list + CTE column outputs)."""
    tree = _parse(sql)
    if tree is None:
        return set()
    out: set[str] = set()
    for a in tree.find_all(exp.Alias):
        if a.alias:
            out.add(a.alias.lower())
    return out


def _flatten_signed(expr, sign: int, out: list) -> None:
    if isinstance(expr, exp.Paren):
        _flatten_signed(expr.this, sign, out)
    elif isinstance(expr, exp.Sub):
        _flatten_signed(expr.this, sign, out)
        _flatten_signed(expr.expression, -sign, out)
    elif isinstance(expr, exp.Add):
        _flatten_signed(expr.this, sign, out)
        _flatten_signed(expr.expression, sign, out)
    else:
        out.append((sign, expr))


def _cond_dim_literals(cond):
    """From a ``dim = lit`` / ``dim IN (lits)`` condition -> (dim_col, [literals])."""
    if isinstance(cond, exp.EQ):
        c = cond.this.find(exp.Column) if cond.this is not None else None
        if isinstance(c, exp.Column) and isinstance(cond.expression, exp.Literal):
            return c.name, [cond.expression.name]
    elif isinstance(cond, exp.In):
        c = cond.this.find(exp.Column) if cond.this is not None else None
        lits = [e.name for e in (cond.expressions or []) if isinstance(e, exp.Literal)]
        if isinstance(c, exp.Column) and lits:
            return c.name, lits
    return None, None


def _literal_value(x):
    """Numeric value of a literal possibly wrapped in a unary minus, else None."""
    if isinstance(x, exp.Neg) and isinstance(x.this, exp.Literal):
        try:
            return -float(x.this.name)
        except (TypeError, ValueError):
            return None
    if isinstance(x, exp.Literal):
        try:
            return float(x.name)
        except (TypeError, ValueError):
            return None
    return None


def _measure_and_sign(expr):
    """For a CASE THEN expression, return (sign, measure_col) when it is a measure
    column or its negation (``-m``, ``m * -1``, ``(-m)``); else (None, None).

    This is what lets the detector see a CASE branch that NEGATES the measure
    (e.g. ``WHEN cost THEN -"FY (Real)"``) -- the same sign double-count expressed
    without a SUM(...)-SUM(...) chain.
    """
    e = expr
    sign = 1
    for _ in range(6):  # bounded unwrap
        if isinstance(e, exp.Paren):
            e = e.this
        elif isinstance(e, exp.Neg):
            sign = -sign
            e = e.this
        elif isinstance(e, exp.Mul):
            lv = _literal_value(e.expression)
            other = e.this
            if lv is None:
                lv = _literal_value(e.this)
                other = e.expression
            if lv is None:
                break
            if lv < 0:
                sign = -sign
            e = other
        else:
            break
    col = e if isinstance(e, exp.Column) else (e.find(exp.Column) if e is not None else None)
    if isinstance(col, exp.Column) and col.name:
        return sign, col.name
    return None, None


def _agg_case_branches(node) -> list[tuple]:
    """AGG(CASE WHEN dim (=|IN) lits THEN [±]measure ...) -> list of
    (branch_sign, measure_col, dim_col, [lits]) across ALL branches."""
    if isinstance(node, exp.Alias):
        node = node.this
    if not isinstance(node, exp.AggFunc):
        return []
    arg = node.this
    if not isinstance(arg, exp.Case):
        return []
    out: list[tuple] = []
    for ifx in arg.args.get("ifs") or []:
        bsign, mcol = _measure_and_sign(ifx.args.get("true"))
        if mcol is None:
            continue
        dim_col, lits = _cond_dim_literals(ifx.this)
        if not dim_col or not lits:
            continue
        out.append((bsign, mcol, dim_col, lits))
    return out


def signed_subtraction_terms(sql: str) -> list[dict]:
    """Terms of an additive formula applied over a measure (round-2 #5B).

    Returns ``[{sign, measure_col, dim_col, literals}]`` for measure terms combined
    by +/-, covering BOTH shapes the generator uses:
      * a ``SUM(...) - SUM(...) - ...`` chain of per-line-item aggregates, and
      * a single ``SUM(CASE WHEN rev THEN m WHEN cost THEN -m ...)`` whose branches
        negate the measure.
    The caller probes whether a SUBTRACTED term's measure is already stored negative
    (so subtracting / negating double-counts the sign).
    """
    tree = _parse(sql)
    if tree is None:
        return []
    selects = list(tree.find_all(exp.Select))
    if not selects:
        return []
    out: list[dict] = []
    for e in selects[0].expressions:
        node = e.this if isinstance(e, exp.Alias) else e
        if isinstance(node, (exp.Sub, exp.Add, exp.Paren)):
            leaves: list = []
            _flatten_signed(node, 1, leaves)
            for chain_sign, leaf in leaves:
                for bsign, mcol, dim, lits in _agg_case_branches(leaf):
                    out.append(
                        {"sign": chain_sign * bsign, "measure_col": mcol, "dim_col": dim, "literals": lits}
                    )
        elif isinstance(node, exp.AggFunc):
            for bsign, mcol, dim, lits in _agg_case_branches(node):
                out.append({"sign": bsign, "measure_col": mcol, "dim_col": dim, "literals": lits})
    return out


# Generated SQL must never reach out to the filesystem / external sources.
# The executor only exposes the dataset's parquet tables as views; a model
# that emits read_csv_auto/read_parquet/pg_read_file would bypass that.
_DANGEROUS_FUNCS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "parquet_scan",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_ndjson_auto",
    "read_text",
    "read_blob",
    "glob",
    "sniff_csv",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "load",
    "install",
    "csv_scan",
}


def find_dangerous_functions(sql: str) -> set[str]:
    """Return any filesystem/exfiltration table-function names present in the SQL."""
    tree = _parse(sql)
    if tree is None:
        return set()
    hits: set[str] = set()
    for fn in tree.find_all(exp.Func, exp.Anonymous):
        name = (getattr(fn, "name", "") or "").lower()
        if not name and hasattr(fn, "sql_name"):
            try:
                name = fn.sql_name().lower()
            except Exception:  # noqa: BLE001
                name = ""
        if name in _DANGEROUS_FUNCS:
            hits.add(name)
    # also catch raw COPY commands
    if tree.find(exp.Command) is not None and re.search(r"\bcopy\b", sql, re.IGNORECASE):
        hits.add("copy")
    return hits
