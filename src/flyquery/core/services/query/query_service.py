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

"""QueryService orchestrator — the complete NL → SQL → result pipeline.

Execution order
---------------
1.  Retrieve schema KB hits (BM25 + pgvector via HybridRetriever)
2.  Rerank top-K schema objects via the cross-encoder reranker
3.  Run GroundingAgent → GroundedContext
4.  Semantic-layer fast-path (SEMANTIC_LAYER + metrics) → compile SQL via MetricFlowCompiler
    OR synthesis path → run GenerationAgent → take candidates[0]
5.  AST classify the chosen SQL (sqlglot)
6.  ScopeGuard.check() — table-kind + dataset allowlist + scope enforcement
7.  Resolve parquet paths for AST table_refs (TableResolver)
8.  DuckDBExecutor.execute() — execute with LIMIT row_cap+1
9.  CriticAgent loop: on ExecutionError, retry up to max_refine_retries times
10. ExplainerAgent — NL summary + chart hint
11. Persist flyquery_queries row via QueryRepository
12. Upload result Parquet + upsert flyquery_query_results via ResultUploader
13. AutoLearner.maybe_propose() — first-shot OK + no PII → insert PROPOSED example
14. Return AnswerResult
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from flyquery.core.services.execution.ast_classifier import AstClassifier
from flyquery.core.services.execution.duckdb_executor import ExecutionError, ExecutionResult
from flyquery.core.services.execution.scope_guard import ScopeGuard, ScopeGuardError
from flyquery.core.services.query import value_anchoring
from flyquery.core.services.semantic.compiler import SemanticCompiler

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Prompt rendering helpers
# ----------------------------------------------------------------------
# Each pipeline agent (Grounding / Generation / Critic / Explainer) is
# a ``FireflyAgent`` -- pydantic-ai's ``Agent.run`` expects a single
# string ``user_prompt``. We render the structured bundle (schema KB
# retrieval hits, examples, glossary, relations, semantic metrics, the
# prior turn's drill-down SQL, etc.) into a markdown-shaped prompt the
# model can reason over.


def _render_grounding_prompt(
    *,
    question: str,
    bundle: dict,
    starting_point_sql: str | None,
) -> str:
    """Pack the retrieved schema KB into a Claude-readable grounding prompt."""

    out: list[str] = []
    out.append("# User question")
    out.append(question.strip())
    out.append("")

    if starting_point_sql:
        out.append("# Prior turn (drill-down starting point)")
        out.append("```sql")
        out.append(starting_point_sql.strip())
        out.append("```")
        out.append("")

    # 1. The "Complete dataset catalogue" lists EVERY table in the dataset.
    #    Ground-truth inventory the LLM must pick from; prevents
    #    hallucination of plausible-but-nonexistent tables like
    #    ``balance_sheet`` / ``income_statement``.
    inventory = bundle.get("schema_inventory", []) or []
    inv_tables = [h for h in inventory if (getattr(h, "metadata", {}) or {}).get("kind") == "TABLE"]
    if inv_tables:
        out.append(f"# Complete dataset catalogue ({len(inv_tables)} tables)")
        out.append(
            "These are the ONLY tables available. Use exactly these qualified "
            "names. Never invent table names like `balance_sheet`, "
            "`income_statement`, or `financials.*` -- if the user asks about "
            "assets, find the matching table below (it may be named in "
            "another language: Spanish `Activos` for English `Assets`, "
            "`Cuenta de Pérdidas y Ganancias` for `Profit & Loss`)."
        )
        for h in inv_tables:
            md = getattr(h, "metadata", None) or {}
            qn = md.get("qualified_name") or "?"
            text = getattr(h, "text", "") or ""
            text = text.replace("\n", " ").strip()
            if len(text) > 160:
                text = text[:157] + "…"
            out.append(f"- `{qn}` :: {text}")
        out.append("")

    # 2. The "Top-ranked columns" section -- only column-level hits
    #    from the hybrid retriever, ranked. Helps the LLM zero in on
    #    the right columns once it has picked a table.
    schema_hits = bundle.get("schema_objects", []) or []
    column_hits = [h for h in schema_hits if (getattr(h, "metadata", {}) or {}).get("kind") != "TABLE"]
    if column_hits:
        out.append(f"# Top-ranked column matches ({len(column_hits)})")
        out.append(
            "Most relevant column-level matches for this question, ranked by "
            "BM25 + vector retrieval. Prefer these when writing the SQL. "
            "Column names that look like dates (e.g. `2024-12-31`) are "
            "legitimate XLSX column names and must be quoted."
        )
        for h in column_hits[:200]:
            md = getattr(h, "metadata", None) or {}
            qn = md.get("qualified_name") or "?"
            text = getattr(h, "text", "") or ""
            text = text.replace("\n", " ").strip()
            if len(text) > 200:
                text = text[:197] + "…"
            out.append(f"- `{qn}` :: {text}")
        out.append("")

    examples = bundle.get("examples", []) or []
    if examples:
        out.append(f"# Approved Q→SQL examples ({len(examples)})")
        for h in examples[:5]:
            md = getattr(h, "metadata", None) or {}
            q = md.get("question", "")
            sql = md.get("sql", "")
            out.append(f"- Q: {q}\n  SQL: `{sql}`")
        out.append("")

    metrics = bundle.get("metrics", []) or []
    if metrics:
        out.append(f"# Published semantic metrics ({len(metrics)})")
        for h in metrics[:5]:
            md = getattr(h, "metadata", None) or {}
            out.append(f"- `{md.get('name')}` -- {md.get('description', '')}")
        out.append("")

    glossary = bundle.get("glossary", []) or []
    if glossary:
        out.append(f"# Glossary terms ({len(glossary)})")
        for h in glossary[:10]:
            md = getattr(h, "metadata", None) or {}
            line = f"- **{md.get('term')}**: {md.get('definition', '')}"
            related = md.get("related_metrics") or []
            if related:
                # A glossary term that maps to a published metric is a strong
                # signal to take the SEMANTIC_LAYER path using that metric.
                line += f" (related metrics: {', '.join(related)})"
            out.append(line)
        out.append("")

    relations = bundle.get("relations", []) or []
    if relations:
        out.append(f"# Approved relations / join hints ({len(relations)})")
        for h in relations[:10]:
            md = getattr(h, "metadata", None) or {}
            out.append(
                f"- {md.get('from_table')}.{md.get('from_column')} "
                f"→ {md.get('to_table')}.{md.get('to_column')} "
                f"(confidence={md.get('confidence')})"
            )
        out.append("")

    out.append("# Task")
    out.append(
        "Produce the GroundedContext for this question. Pick the MINIMAL set of "
        "tables, columns, and joins. If a published metric covers the question, "
        "set path=SEMANTIC_LAYER. Otherwise path=SYNTHESIS. Set confidence ∈ [0,1] "
        "and only populate `missing_info` when confidence is below 0.55."
    )
    return "\n".join(out)


def _lookup_col(qn: str, cat_by_qn: dict) -> dict | None:
    if qn in cat_by_qn:
        return cat_by_qn[qn]
    # tolerate grounding returning a shorter/unqualified column name
    tail = qn.rsplit(".", 1)[-1].lower()
    for k, v in cat_by_qn.items():
        if k.rsplit(".", 1)[-1].lower() == tail:
            return v
    return None


def _render_generation_prompt(
    question: str,
    grounded: Any,
    starting_point_sql: str | None,
    *,
    schema_inventory: list[Any] | None = None,
    col_catalog: list[dict] | None = None,
    resolved_entities: list[dict] | None = None,
    resolved_groups: list[dict] | None = None,
    hierarchy_intent: bool = False,
    examples: list[Any] | None = None,
    n_candidates: int = 3,
    max_columns: int = 80,
    char_budget: int = 320,
) -> str:
    """Pack the grounded context + the per-column VALUE CATALOGUE into a prompt.

    The generation prompt now shows, for each in-scope column, its data_type,
    semantic role (measure/dimension/time), and the actual distinct VALUES (or
    numeric range) the column holds -- so the SQL writer copies real filter
    literals instead of inventing them. Question entities that were located in
    the data are listed explicitly. All sourced from the dataset's own
    ingest-time profiling; nothing is hardcoded.
    """
    from collections import defaultdict

    cat_by_qn = {c["qualified_name"]: c for c in (col_catalog or [])}
    cols_by_table: dict[str, list[dict]] = defaultdict(list)
    for c in col_catalog or []:
        cols_by_table[c["qualified_name"].rsplit(".", 1)[0]].append(c)

    out: list[str] = []
    out.append("# User question")
    out.append(question.strip())
    out.append("")

    if starting_point_sql:
        out.append("# Prior turn SQL (build a delta on top of this when possible)")
        out.append("```sql")
        out.append(starting_point_sql.strip())
        out.append("```")
        out.append("")

    if resolved_entities:
        out.append("# Resolved entities (literals located in the data)")
        out.append(
            "These exact question literals were FOUND as stored values. Filter on "
            "the stated column with the stated value verbatim. When a literal was "
            "found in MORE THAN ONE column, the number of rows it matches is shown:"
        )
        for e in resolved_entities[:24]:
            cnt = e.get("match_count")
            tag = ""
            if cnt is not None:
                role = "repeats → grouping/parent key" if cnt > 1 else "appears once → identity"
                tag = f" — matches {cnt} row(s), {role}"
            out.append(f"- '{e['literal']}' → column `{e['column']}` (stored value: {e['value']!r}){tag}")
        if hierarchy_intent:
            out.append(
                "NOTE: this is a hierarchy / team / reporting question. Filter the column where the "
                "entity REPEATS across rows (the parent/manager key), NOT where it appears once (its "
                "own identity row). Prefer the table with the MOST matching rows over a stale one."
            )
            top = max(
                (e for e in resolved_entities if (e.get("match_count") or 0) > 1),
                key=lambda e: e.get("match_count") or 0,
                default=None,
            )
            if top is not None:
                out.append(
                    f"  >> Best binding: filter on `{top['column']}` (the entity matches "
                    f"{top['match_count']} rows there) — query THAT column in THAT table; ignore "
                    f"tables/columns where the name appears only 0–1 times."
                )
        out.append("")

    if resolved_groups:
        out.append("# Resolved value groups (a term that spans several stored values)")
        out.append(
            "Each question term below is an umbrella over MULTIPLE values of one column — it "
            "means the WHOLE set, never a subset:"
        )
        for g in resolved_groups[:12]:
            col = g["column"].rsplit(".", 1)[-1]
            vlist = ", ".join(repr(v) for v in g["values"])
            if g.get("truncated"):
                out.append(
                    f"- '{g['literal']}' spans column `{col}` (the catalogued list is INCOMPLETE) — "
                    f"use `{col} LIKE '{g['literal']}%'` to capture every member."
                )
            else:
                out.append(
                    f"- '{g['literal']}' spans these values in `{col}`: [{vlist}] — "
                    f"use IN(all of them) or `{col} LIKE '{g['literal']}%'`; never a subset."
                )
        out.append("")

    inv = schema_inventory or []
    inv_tables = [h for h in inv if (getattr(h, "metadata", {}) or {}).get("kind") == "TABLE"]
    if inv_tables:
        out.append(f"# Complete dataset catalogue ({len(inv_tables)} tables)")
        out.append(
            "Every table in this dataset. The SQL you generate MUST reference "
            "tables from this list only -- never invent table names like "
            "`balance_sheet`, `income_statement`, or `financials.*`."
        )
        for h in inv_tables:
            md = getattr(h, "metadata", None) or {}
            qn = md.get("qualified_name") or "?"
            text = getattr(h, "text", "") or ""
            text = text.replace("\n", " ").strip()
            if len(text) > 160:
                text = text[:157] + "…"
            out.append(f"- `{qn}` :: {text}")
        out.append("")

    g_path = getattr(grounded, "path", None)
    g_tables = getattr(grounded, "tables", []) or []
    g_columns = getattr(grounded, "columns", []) or []
    g_joins = getattr(grounded, "joins", []) or []

    out.append(f"# Grounded context (path = {g_path})")
    if g_tables:
        out.append("## Tables in scope")
        for t in g_tables:
            out.append(f"- `{getattr(t, 'table_qualified_name', t)}`")
        out.append("")

    # Full, value-anchored column listing for every in-scope table. This both
    # raises recall (the right column may have ranked below top-12) and gives
    # the SQL writer the real literal vocabulary for each column.
    rendered = 0
    table_qns = [getattr(t, "table_qualified_name", str(t)) for t in g_tables]
    if not table_qns:
        # No grounded tables: fall back to every table that has columns.
        table_qns = list(cols_by_table.keys())
    if table_qns:
        out.append("## Columns with values (use these literals verbatim)")
        for tqn in table_qns:
            cols = cols_by_table.get(tqn) or []
            if not cols:
                # match by table-name tail when grounding used a short qn
                tail = tqn.rsplit(".", 1)[-1].lower()
                for k, v in cols_by_table.items():
                    if k.rsplit(".", 1)[-1].lower() == tail:
                        cols = v
                        break
            if not cols:
                continue
            out.append(f"### `{tqn}`")
            for c in cols:
                if rendered >= max_columns:
                    out.append("- … (column list truncated)")
                    break
                out.append(
                    "- "
                    + value_anchoring.render_catalog_from_meta(
                        c["qualified_name"], c, char_budget=char_budget
                    )
                )
                rendered += 1
            out.append("")
            if rendered >= max_columns:
                break
    elif g_columns:
        out.append("## Columns in scope")
        for c in g_columns:
            qn = getattr(c, "column_qualified_name", str(c))
            meta = _lookup_col(qn, cat_by_qn)
            if meta:
                out.append("- " + value_anchoring.render_catalog_from_meta(qn, meta, char_budget=char_budget))
            else:
                out.append(f"- `{qn}`")
        out.append("")

    if g_joins:
        out.append("## Approved joins")
        for j in g_joins:
            out.append(
                f"- `{getattr(j, 'from_table', '')}.{getattr(j, 'from_column', '')}` "
                f"= `{getattr(j, 'to_table', '')}.{getattr(j, 'to_column', '')}` "
                f"({getattr(j, 'relationship', 'inner')} join)"
            )
        out.append("")

    if examples:
        out.append(f"# Worked examples (approved Q→SQL, {len(examples)})")
        for h in examples[:5]:
            md = getattr(h, "metadata", None) or {}
            out.append(f"- Q: {md.get('question', '')}\n  SQL: `{md.get('generated_sql', '')}`")
        out.append("")

    out.append("# Task")
    out.append(
        f"Generate {n_candidates} candidate DuckDB SQL queries that answer the question, "
        "ordered by confidence (highest first). Each candidate must:\n"
        "- Use only the tables and columns listed above. Reference each table by its "
        "**unqualified name** (the last segment of the qualified name).\n"
        "- For every WHERE / GROUP BY / JOIN literal, COPY a value shown in the "
        "'values:' list of that column VERBATIM (exact case + spelling). Do NOT invent "
        "or translate filter literals. If the question's entity matches a value under a "
        "DIFFERENT column than you expected, filter on the column that actually holds it "
        "(see 'Resolved entities').\n"
        "- For a year/period/time column whose values are strings (e.g. 'FY23'), filter "
        "with the STRING form shown -- never an integer like 2023, and never use a numeric "
        "measure column as the year axis.\n"
        "- Aggregate measure columns; filter/group on dimension/time columns.\n"
        "- NEVER emit a no-op query (e.g. `WHERE 1=0`, `SUM(CASE WHEN ... THEN 0 ELSE 0 END)`, "
        "or a constant SELECT). If you cannot map a needed filter to a real value, widen or "
        "omit that filter and lower your confidence rather than returning a placeholder.\n"
        '- Quote any column name that isn\'t a plain identifier (e.g. `"2024-12-31"`, '
        '`"P&L Line"`).\n'
        "- Be a SINGLE SELECT statement (no multi-statement; no DDL)."
    )
    return "\n".join(out)


def _render_critic_prompt(
    *,
    question: str,
    failing_sql: str,
    error_message: str,
    grounded: Any,
    schema_inventory: list[Any] | None = None,
    value_hints: list[str] | None = None,
) -> str:
    out: list[str] = []
    out.append("# User question")
    out.append(question.strip())
    out.append("")
    out.append("# Previous SQL (needs repair)")
    out.append("```sql")
    out.append(failing_sql.strip())
    out.append("```")
    out.append("")
    out.append("# Problem")
    out.append(error_message.strip())
    out.append("")

    # The actual stored values of the columns the failing query filtered on --
    # so the critic replaces wrong literals with real ones instead of guessing
    # again (this is what fixes the silent 0-row failures).
    if value_hints:
        out.append("# Column value catalogue (verify EVERY filter literal against these)")
        for line in value_hints:
            out.append(f"- {line}")
        out.append("")

    # Full dataset catalogue -- the critic's most common failure mode
    # is rewriting one hallucinated table name into another (e.g.
    # ``balance_sheet`` -> ``financials.balance_sheet`` rather than
    # picking the real ``IVI_MALAGA_SL__Activos``). Showing every real
    # table by qualified_name + column fingerprint forces the critic
    # to pick from the catalogue.
    inv = schema_inventory or []
    inv_tables = [h for h in inv if (getattr(h, "metadata", {}) or {}).get("kind") == "TABLE"]
    if inv_tables:
        out.append(f"# Complete dataset catalogue ({len(inv_tables)} tables)")
        out.append(
            "ONLY these tables exist. If the failing SQL referenced anything "
            "else, that's the bug -- pick the right one from this list. Table "
            "names may be in any language (Spanish `Activos` = Assets, "
            "`Cuenta de Pérdidas y Ganancias` = Profit & Loss)."
        )
        for h in inv_tables:
            md = getattr(h, "metadata", None) or {}
            qn = md.get("qualified_name") or "?"
            text = getattr(h, "text", "") or ""
            text = text.replace("\n", " ").strip()
            if len(text) > 160:
                text = text[:157] + "…"
            out.append(f"- `{qn}` :: {text}")
        out.append("")

    g_tables = getattr(grounded, "tables", []) or []
    g_columns = getattr(grounded, "columns", []) or []
    if g_tables or g_columns:
        out.append("# Grounded scope (preferred tables / columns)")
        for t in g_tables:
            out.append(f"- table: `{getattr(t, 'table_qualified_name', t)}`")
        for c in g_columns:
            out.append(f"- column: `{getattr(c, 'column_qualified_name', c)}`")
        out.append("")
    out.append("# Task")
    out.append(
        "Return a corrected SQL that resolves the execution error. Output a "
        "RefinedSql with a brief reasoning + a confidence in [0,1]. Pick "
        "tables ONLY from the catalogue above. Use unqualified table names "
        "(last segment only) and quote any non-identifier column names like "
        '`"2024-12-31"`.'
    )
    return "\n".join(out)


def _render_explainer_prompt(
    *,
    question: str,
    executed_sql: str,
    row_count: int,
    preview_rows: list[dict],
) -> str:
    out: list[str] = []
    out.append("# User question")
    out.append(question.strip())
    out.append("")
    out.append("# Executed SQL")
    out.append("```sql")
    out.append(executed_sql.strip())
    out.append("```")
    out.append("")
    out.append("# Result")
    out.append(f"row_count: {row_count}")
    if preview_rows:
        out.append(f"rows (first {min(len(preview_rows), 50)}):")
        for row in preview_rows[:50]:
            out.append(f"- {row}")
    out.append("")
    out.append("# Task")
    out.append(
        "Produce a ResultExplanation with a 1-3 sentence NL summary that directly "
        "answers the question using the rows above, and a chart_hint picked from "
        "{line, bar, table, pie, none}. Never invent numbers -- cite only what is "
        "in the preview."
    )
    return "\n".join(out)


@dataclass
class AnswerResult:
    """Full result from QueryService.answer()."""

    query_id: uuid.UUID
    sql: str | None
    execution_status: Literal["OK", "REFINED_OK", "FAILED", "REJECTED_BY_FIREWALL"] | None
    preview: list[dict] | None
    row_count: int | None
    truncated: bool
    elapsed_ms: int | None
    chart_hint: str | None
    explanation: str | None
    clarification: Any  # ClarificationFrame or None
    grounded_summary: dict | None
    snapshot_pins: dict[str, str] = field(default_factory=dict)


class QueryService:
    """Orchestrates the Grounding → Generation → AST → Exec → Critic → Explainer loop.

    All agents are injected (built by ``build_*_agent`` factories) so they
    can be replaced with canned fakes in unit tests without touching LLM APIs.

    :param retriever: HybridRetriever
    :param reranker: cross-encoder reranker (NoopReranker when unavailable)
    :param grounding_agent: FireflyAgent[GroundedContext]
    :param generation_agent: FireflyAgent[GeneratedCandidates]
    :param critic_agent: FireflyAgent[RefinedSql]
    :param explainer_agent: FireflyAgent[ResultExplanation]
    :param ast_classifier: AstClassifier
    :param scope_guard: ScopeGuard
    :param table_resolver: TableResolver
    :param executor: DuckDBExecutor
    :param query_repo: QueryRepository
    :param settings: FlyquerySettings
    :param result_uploader: ResultUploader
    :param auto_learner: AutoLearner
    :param metric_compiler: MetricFlowCompiler (optional — used for SEMANTIC_LAYER path)
    :param semantic_repo: SemanticRepository (optional — fetches compiled SQL)
    :param conversation_service: ConversationService (optional — Phase E drill-down)
    """

    def __init__(
        self,
        retriever,
        reranker,
        grounding_agent,
        generation_agent,
        critic_agent,
        explainer_agent,
        ast_classifier: AstClassifier,
        scope_guard: ScopeGuard,
        table_resolver,
        executor,
        query_repo,
        settings,
        result_uploader,
        auto_learner,
        metric_compiler=None,
        semantic_repo=None,
        conversation_service=None,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._grounding_agent = grounding_agent
        self._generation_agent = generation_agent
        self._critic_agent = critic_agent
        self._explainer_agent = explainer_agent
        self._ast_classifier = ast_classifier
        self._scope_guard = scope_guard
        self._table_resolver = table_resolver
        self._executor = executor
        self._query_repo = query_repo
        self._settings = settings
        self._result_uploader = result_uploader
        self._auto_learner = auto_learner
        self._metric_compiler = metric_compiler
        self._semantic_repo = semantic_repo
        self._conversation_service = conversation_service

    async def answer(
        self,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        dataset_id: uuid.UUID,
        question: str,
        scopes: set[str],
        dataset_allowlist: set[str] | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> AnswerResult:
        """Run the full NL → SQL → result pipeline.

        :param tenant_id: tenant identifier
        :param workspace_id: workspace UUID
        :param dataset_id: dataset to query
        :param question: natural-language question
        :param scopes: caller's token scopes (used by ScopeGuard)
        :param dataset_allowlist: optional set of allowed dataset IDs (None = unrestricted)
        :param conversation_id: optional conversation for drill-down context (Phase E)
        :return: :class:`AnswerResult`
        """
        start_ms = time.monotonic_ns() // 1_000_000

        # ------------------------------------------------------------------
        # 1. Hybrid retrieval
        # ------------------------------------------------------------------
        bundle = await self._retriever.retrieve(
            question,
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            top_k_schema=self._settings.top_k_schema * 3,
            top_k_examples=self._settings.top_k_examples,
            top_k_metrics=self._settings.top_k_metrics,
        )

        # ------------------------------------------------------------------
        # 2. Rerank top-30 schema hits → top-K
        # ------------------------------------------------------------------
        schema_hits = bundle.get("schema_objects", [])
        top_k = self._settings.top_k_schema
        reranked = await self._reranker.rerank(question, schema_hits, top_n=top_k)
        bundle["schema_objects"] = reranked

        # ------------------------------------------------------------------
        # 2b. Load drill-down context from prior turn (Phase E)
        # ------------------------------------------------------------------
        starting_point_sql: str | None = None
        prior_table_qnames: list[str] = []
        prior_snapshot_pins: dict[str, str] = {}

        if conversation_id is not None and self._conversation_service is not None:
            prior_turn = await self._conversation_service.last_turn(conversation_id)
            if prior_turn is not None:
                starting_point_sql = prior_turn.get("executed_sql")
                prior_table_qnames = prior_turn.get("table_qnames_json") or []
                prior_snapshot_pins = prior_turn.get("snapshot_pins_json") or {}

        bundle["starting_point_sql"] = starting_point_sql
        bundle["prior_table_qnames"] = prior_table_qnames

        # ------------------------------------------------------------------
        # 3. Grounding — pydantic-ai's Agent.run expects a STRING prompt,
        # so we render the retrieval bundle into a markdown-ish doc that
        # Claude can reason over.
        # ------------------------------------------------------------------
        grounding_prompt = _render_grounding_prompt(
            question=question,
            bundle=bundle,
            starting_point_sql=starting_point_sql,
        )
        grounded_run = await self._grounding_agent.run(grounding_prompt)
        # pydantic-ai's AgentRunResult wraps the structured response on .output
        grounded = getattr(grounded_run, "output", grounded_run)

        # ------------------------------------------------------------------
        # 4. Value catalogue + entity / group resolution (G1/G3 + round-2 #1/#2)
        # ------------------------------------------------------------------
        col_catalog = bundle.get("column_catalog") or []
        resolution = await self._resolve_entities(dataset_id, question, col_catalog, bundle)
        resolved_entities = resolution["entities"]
        resolved_groups = resolution["groups"]
        hierarchy_intent = resolution["hierarchy_intent"]

        # ------------------------------------------------------------------
        # 5. SQL generation (semantic-layer fast path OR synthesis)
        # ------------------------------------------------------------------
        chosen_sql: str
        candidates_json: list = []
        candidate_sqls: list[str] = []

        if grounded.path == "SEMANTIC_LAYER" and grounded.metrics:
            metric_name = grounded.metrics[0].metric_name
            compiled, metric_version = await self._compiled_metric_sql(
                metric_name, dataset_id, tenant_id=tenant_id, workspace_id=workspace_id
            )
            if compiled:
                candidate_sqls = [compiled]
                candidates_json = [
                    {
                        "sql": compiled,
                        "reasoning": "semantic-layer compiled",
                        "confidence": 1.0,
                        "metric_name": metric_name,
                        "metric_version": metric_version,
                    }
                ]
        if not candidate_sqls:
            gen_prompt = _render_generation_prompt(
                question,
                grounded,
                starting_point_sql,
                schema_inventory=bundle.get("schema_inventory"),
                col_catalog=col_catalog,
                resolved_entities=resolved_entities,
                resolved_groups=resolved_groups,
                hierarchy_intent=hierarchy_intent,
                examples=bundle.get("examples"),
                n_candidates=self._settings.generation_candidates,
                max_columns=self._settings.value_catalog_max_columns,
                char_budget=self._settings.value_catalog_char_budget,
            )
            gen_run = await self._generation_agent.run(gen_prompt)
            gen_out = getattr(gen_run, "output", gen_run)
            candidates_json = [c.model_dump() for c in gen_out.candidates]
            candidate_sqls = [c.sql for c in gen_out.candidates if getattr(c, "sql", None)]
        if not candidate_sqls:
            candidate_sqls = [""]

        # ------------------------------------------------------------------
        # 6. Candidate selection by EXECUTION (G5): drop degenerate, prefer a
        #    candidate that runs AND returns rows. Each candidate passes the
        #    scope guard + synthesis function firewall (G8) + table guard (G6).
        # ------------------------------------------------------------------
        ordered = [s for s in candidate_sqls if not value_anchoring.is_degenerate_sql(s)] or candidate_sqls
        select_pool = ordered if self._settings.candidate_exec_selection else ordered[:1]

        best: tuple[str, Any, Any] | None = None
        scope_reject: ScopeGuardError | None = None
        firewall_reject: str | None = None
        for cand in select_pool:
            run = await self._run_sql_once(cand, dataset_id, scopes, dataset_allowlist, bundle)
            if run["status"] == "scope":
                scope_reject = run["error"]
                continue
            if run["status"] == "firewall":
                firewall_reject = run["error"]
                continue
            if best is None:
                best = (cand, run["result"], run["ast"])
            res = run["result"]
            if (
                isinstance(res, ExecutionResult)
                and res.row_count > 0
                and not value_anchoring.is_degenerate_sql(cand)
            ):
                best = (cand, res, run["ast"])
                break

        if best is None:
            # Nothing executed. If the only blockers were scope/firewall, reject.
            if scope_reject is not None or firewall_reject is not None:
                reason = str(scope_reject) if scope_reject is not None else (firewall_reject or "")
                chosen_sql = ordered[0]
                ast = self._ast_classifier.classify(chosen_sql)
                elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
                query_id = await self._query_repo.create_query(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    dataset_id=dataset_id,
                    question=question,
                    semantic_path_taken=grounded.path,
                    candidates_json=candidates_json,
                    chosen_candidate_index=0,
                    executed_sql=chosen_sql,
                    ast_classification=ast.classification,
                    execution_status="REJECTED_BY_FIREWALL",
                    retries=0,
                    row_count=None,
                    elapsed_ms=elapsed,
                    clarification_emitted=False,
                    clarification_json=None,
                    pii_findings_json=None,
                    error_json={"firewall_error": reason},
                )
                return AnswerResult(
                    query_id=query_id,
                    sql=chosen_sql,
                    execution_status="REJECTED_BY_FIREWALL",
                    preview=None,
                    row_count=None,
                    truncated=False,
                    elapsed_ms=elapsed,
                    chart_hint=None,
                    explanation=None,
                    clarification=self._clarification(grounded),
                    grounded_summary=self._grounded_summary(grounded),
                )
            chosen_sql = ordered[0]
            best = (
                chosen_sql,
                ExecutionError(message="generation produced no usable SQL"),
                self._ast_classifier.classify(chosen_sql),
            )

        chosen_sql, result, ast = best
        chosen_index = candidate_sqls.index(chosen_sql) if chosen_sql in candidate_sqls else 0
        retries = 0

        def _is_good(r, s) -> bool:
            return (
                isinstance(r, ExecutionResult)
                and r.row_count > 0
                and not value_anchoring.is_degenerate_sql(s)
            )

        # Retain an executed, nonempty result if a repair fails. Row count is
        # an execution check; it does not establish semantic correctness.
        best_ok = (chosen_sql, result, ast) if _is_good(result, chosen_sql) else None

        # round-2 #5B/#7: when the result is already OK, an advisory check may still
        # ask the critic to reconsider (signed-measure double-subtraction; an IN-list
        # that under-covers a value group). It rides the non-destructive loop below,
        # and preserves the previous executed result when a proposal fails.
        adv_msg = None
        if _is_good(result, chosen_sql):
            adv_msg = await self._advisory_repair(chosen_sql, ast, col_catalog, question, dataset_id, bundle)

        # ------------------------------------------------------------------
        # 7. Repair loop: HARD repair (error / degenerate / 0-row-with-filter) OR an
        #    ADVISORY reconsideration. The critic receives the REAL stored values of
        #    the filtered columns so it replaces wrong literals/columns/signs instead
        #    of guessing again, and MAY keep the original SQL if it is already correct.
        # ------------------------------------------------------------------
        while (
            self._needs_repair(result, chosen_sql) or adv_msg
        ) and retries < self._settings.max_refine_retries:
            if self._needs_repair(result, chosen_sql):
                critic_msg = self._repair_message(result, chosen_sql, ast, col_catalog)
            else:
                critic_msg = adv_msg
            value_hints = self._build_value_hints(chosen_sql, col_catalog, ast)
            critic_prompt = _render_critic_prompt(
                question=question,
                failing_sql=chosen_sql,
                error_message=critic_msg,
                grounded=grounded,
                schema_inventory=bundle.get("schema_inventory"),
                value_hints=value_hints,
            )
            refined_run = await self._critic_agent.run(critic_prompt)
            refined = getattr(refined_run, "output", refined_run)
            new_sql = getattr(refined, "sql", None) or chosen_sql
            if new_sql.strip() == chosen_sql.strip():
                break  # critic kept the SQL -> accept it as already correct
            if value_anchoring.is_degenerate_sql(new_sql):
                break  # never adopt a placeholder; best_ok (if any) is restored below
            run = await self._run_sql_once(new_sql, dataset_id, scopes, dataset_allowlist, bundle)
            if run["status"] in ("scope", "firewall"):
                break
            chosen_sql = new_sql
            result = run["result"]
            ast = run["ast"]
            retries += 1
            if _is_good(result, chosen_sql):
                best_ok = (chosen_sql, result, ast)
                adv_msg = await self._advisory_repair(
                    chosen_sql, ast, col_catalog, question, dataset_id, bundle
                )
            else:
                adv_msg = None

        # Restore the executed fallback when repair produces no usable result.
        if best_ok is not None and not _is_good(result, chosen_sql):
            chosen_sql, result, ast = best_ok

        # ------------------------------------------------------------------
        # 8. Determine execution status
        # ------------------------------------------------------------------
        if isinstance(result, ExecutionResult) and retries == 0:
            execution_status: str = "OK"
        elif isinstance(result, ExecutionResult):
            execution_status = "REFINED_OK"
        else:
            execution_status = "FAILED"

        # ------------------------------------------------------------------
        # 8. Explain
        # ------------------------------------------------------------------
        explanation_obj = None
        if isinstance(result, ExecutionResult):
            explainer_prompt = _render_explainer_prompt(
                question=question,
                executed_sql=chosen_sql,
                row_count=result.row_count,
                preview_rows=result.rows[:50],
            )
            explanation_run = await self._explainer_agent.run(explainer_prompt)
            explanation_obj = getattr(explanation_run, "output", explanation_run)

        # ------------------------------------------------------------------
        # 9. Clarification frame (low confidence, OR confident-but-still-empty)
        # ------------------------------------------------------------------
        final_row_count = result.row_count if isinstance(result, ExecutionResult) else None
        clarification = self._clarification(grounded, row_count=final_row_count)
        clarification_emitted = clarification is not None

        # ------------------------------------------------------------------
        # 10. Persist query row
        # ------------------------------------------------------------------
        elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
        error_json: dict | None = None
        if isinstance(result, ExecutionError):
            error_json = {"message": result.message}

        query_id = await self._query_repo.create_query(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            question=question,
            semantic_path_taken=grounded.path,
            candidates_json=candidates_json,
            chosen_candidate_index=chosen_index,
            executed_sql=chosen_sql,
            ast_classification=ast.classification,
            execution_status=execution_status,
            retries=retries,
            row_count=result.row_count if isinstance(result, ExecutionResult) else None,
            elapsed_ms=elapsed,
            clarification_emitted=clarification_emitted,
            clarification_json=clarification.model_dump() if clarification else None,
            pii_findings_json=None,  # PII scanning in result is Phase F
            error_json=error_json,
            model_grounding=self._settings.grounding_model,
            model_generation=self._settings.generation_model,
            model_critic=self._settings.critic_model if retries > 0 else None,
            model_explainer=self._settings.explainer_model if explanation_obj else None,
        )

        # ------------------------------------------------------------------
        # 11. Upload result
        # ------------------------------------------------------------------
        if isinstance(result, ExecutionResult):
            await self._result_uploader.upload(
                query_id=query_id,
                result=result,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                dataset_id=dataset_id,
            )

        # ------------------------------------------------------------------
        # 12. Auto-learn (only on first-shot OK + no PII + no clarification)
        # ------------------------------------------------------------------
        if execution_status == "OK" and isinstance(result, ExecutionResult) and not clarification_emitted:
            await self._auto_learner.maybe_propose(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                dataset_id=dataset_id,
                question=question,
                generated_sql=chosen_sql,
                retries=retries,
                pii_findings=[],
                query_id=query_id,
                row_count=result.row_count,
            )

        # ------------------------------------------------------------------
        # 13. Persist conversation turn (Phase E drill-down)
        # ------------------------------------------------------------------
        if (
            conversation_id is not None
            and self._conversation_service is not None
            and execution_status in ("OK", "REFINED_OK")
        ):
            await self._conversation_service.append_turn(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                question=question,
                executed_sql=chosen_sql,
                summary=explanation_obj.summary if explanation_obj else None,
                table_qnames_json=list(ast.table_refs),
                snapshot_pins_json=prior_snapshot_pins,
                elapsed_ms=elapsed,
            )

        return AnswerResult(
            query_id=query_id,
            sql=chosen_sql,
            execution_status=execution_status,  # type: ignore[arg-type]
            preview=result.rows[:10] if isinstance(result, ExecutionResult) else None,
            row_count=result.row_count if isinstance(result, ExecutionResult) else None,
            truncated=result.truncated if isinstance(result, ExecutionResult) else False,
            elapsed_ms=elapsed,
            chart_hint=explanation_obj.chart_hint if explanation_obj else None,
            explanation=explanation_obj.summary if explanation_obj else None,
            clarification=clarification,
            grounded_summary=self._grounded_summary(grounded),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _table_kinds_by_name(
        self,
        table_names: list[str],
        dataset_id: uuid.UUID,
    ) -> dict[str, str]:
        """Return {name: kind} for the given table names in the dataset.

        Uses the session injected into the TableResolver. Both QueryService
        and TableResolver receive the same request-scoped AsyncSession from
        the controller; the session is guaranteed live for the full request.
        """
        if not table_names:
            return {}
        import sqlalchemy as sa

        session = self._table_resolver._session
        rows = await session.execute(
            sa.text("""
                SELECT name, kind FROM flyquery_tables
                WHERE dataset_id = :ds AND name = ANY(:names) AND is_active = true
            """),
            {"ds": dataset_id, "names": list(table_names)},
        )
        return {r["name"]: r["kind"] for r in rows.mappings()}

    async def _dataset_of_tables(
        self,
        table_names: list[str],
        dataset_id: uuid.UUID,
    ) -> dict[str, str]:
        """Return {name: dataset_id_str} — all resolved tables share the same dataset."""
        return {name: str(dataset_id) for name in table_names}

    async def _compiled_metric_sql(
        self,
        metric_name: str,
        dataset_id: uuid.UUID,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
    ) -> tuple[str | None, int | None]:
        """Fetch + bind the compiled SQL for a PUBLISHED metric.

        Returns ``(bound_sql, current_version)`` so the version can be pinned
        in the query record, or ``(None, None)`` when no usable metric is found.
        """
        if self._semantic_repo is None:
            return None, None
        try:
            row = await self._semantic_repo.get_by_name(
                metric_name, dataset_id, tenant_id=tenant_id, workspace_id=workspace_id
            )
        except (AttributeError, KeyError, TypeError) as exc:  # pragma: no cover - defensive
            logger.warning("semantic metric lookup failed for %r: %s", metric_name, exc)
            return None, None
        if not row or not row.get("compiled_sql_template"):
            return None, None
        bound = SemanticCompiler.bind(row["compiled_sql_template"])
        return bound, row.get("current_version")

    def _clarification(self, grounded, *, row_count: int | None = None) -> Any:
        """Build a ClarificationFrame if grounding confidence is low or the
        (confident) query still returned 0 rows (G7 -- couple clarification to
        the observed empty result instead of confidence alone)."""
        from flyquery.interfaces.query import ClarificationFrame

        if grounded.confidence < self._settings.grounding_min_confidence and grounded.missing_info:
            return ClarificationFrame(questions=grounded.missing_info, reasons=[])
        if row_count == 0:
            return ClarificationFrame(
                questions=[
                    "The query executed but matched 0 rows -- a filter value, period, "
                    "or entity may not match how it is stored in the data. Please confirm "
                    "the exact value you mean."
                ],
                reasons=[],
            )
        return None

    def _grounded_summary(self, grounded) -> dict:
        """Convert GroundedContext to a summary dict for the response."""
        return {
            "path": grounded.path,
            "confidence": grounded.confidence,
            "table_count": len(grounded.tables),
            "missing_info": grounded.missing_info,
        }

    # ------------------------------------------------------------------
    # Value-anchoring / repair helpers (G2/G3/G5/G6/G8)
    # ------------------------------------------------------------------

    async def _run_sql_once(
        self,
        sql: str,
        dataset_id: uuid.UUID,
        scopes: set[str],
        dataset_allowlist: set[str] | None,
        bundle: dict,
    ) -> dict:
        """Classify, guard, and execute one candidate SQL.

        Returns ``{status, result, ast, error}`` where status is one of
        ``ok`` / ``empty`` / ``error`` / ``scope`` / ``firewall``.
        """
        ast = self._ast_classifier.classify(sql)

        # G8: block filesystem/exfiltration table-functions on the synthesis path.
        if self._settings.synthesis_function_firewall:
            dangerous = value_anchoring.find_dangerous_functions(sql)
            if dangerous:
                return {
                    "status": "firewall",
                    "result": None,
                    "ast": ast,
                    "error": f"disallowed function(s) in generated SQL: {sorted(dangerous)}",
                }

        table_kinds = await self._table_kinds_by_name(list(ast.table_refs), dataset_id)
        dataset_of_table = await self._dataset_of_tables(list(ast.table_refs), dataset_id)
        try:
            self._scope_guard.check(
                classification=ast,
                scopes=scopes,
                table_kinds_by_name=table_kinds,
                dataset_allowlist=dataset_allowlist,
                dataset_of_table=dataset_of_table,
            )
        except ScopeGuardError as exc:
            return {"status": "scope", "result": None, "ast": ast, "error": exc}

        # G6: CTE-aware unknown-table guard. CTE / derived-table aliases are NOT
        # real tables, so subtract them before the set-difference -- otherwise a
        # valid `WITH x AS (...) SELECT ... FROM x` is wrongly rejected.
        synthetic = {n.lower() for n in value_anchoring.cte_and_derived_names(sql)}
        ref_set = {t for t in ast.table_refs if t and t.lower() not in synthetic}
        bad_tables = sorted(ref_set - set(table_kinds.keys()))
        if bad_tables:
            real_tables = sorted(table_kinds.keys()) + [
                (getattr(h, "metadata", {}) or {}).get("qualified_name", "").rsplit(".", 1)[-1]
                for h in (bundle.get("schema_inventory") or [])
                if (getattr(h, "metadata", {}) or {}).get("kind") == "TABLE"
            ]
            real_tables = [t for t in dict.fromkeys(real_tables) if t]
            return {
                "status": "error",
                "result": ExecutionError(
                    message=(
                        f"Table(s) {bad_tables!r} do not exist in this dataset. "
                        f"Use ONLY these tables: {real_tables[:80]!r}."
                    )
                ),
                "ast": ast,
                "error": None,
            }

        attached = await self._table_resolver.resolve(dataset_id, list(ast.table_refs))
        result = await self._executor.execute(sql, attached)
        if isinstance(result, ExecutionResult):
            status = "ok" if result.row_count > 0 else "empty"
        else:
            status = "error"
        return {"status": status, "result": result, "ast": ast, "error": None}

    def _needs_repair(self, result, sql: str) -> bool:
        """A query needs repair if it errored, is degenerate, or ran to 0 rows
        while filtering on equality/IN literals (G2/G5)."""
        if isinstance(result, ExecutionError):
            return True
        if value_anchoring.is_degenerate_sql(sql):
            return True
        return bool(
            self._settings.zero_row_repair_enabled
            and isinstance(result, ExecutionResult)
            and result.row_count == 0
            and value_anchoring.equality_predicate_columns(sql)
        )

    def _repair_message(self, result, sql: str, ast, col_catalog: list[dict]) -> str:
        unknown = self._unknown_columns(ast, col_catalog, sql)
        suffix = ""
        if unknown:
            names = sorted({c.get("qualified_name", "").rsplit(".", 1)[-1] for c in col_catalog})
            suffix = (
                f" Also: column(s) {unknown!r} are not real columns -- use only these "
                f"columns: {names[:80]!r}."
            )
        if isinstance(result, ExecutionError):
            return result.message + suffix
        if value_anchoring.is_degenerate_sql(sql):
            return (
                "The previous SQL is a no-op (constant/placeholder, e.g. WHERE 1=0 or "
                "SUM(CASE..THEN 0 ELSE 0)). Rewrite it to actually compute the answer "
                "using real columns and literal values from the catalogue below." + suffix
            )
        return (
            "The previous SQL executed but returned 0 ROWS. One or more filter literals "
            "or filtered columns is wrong. Replace each WHERE/IN literal with a value that "
            "actually appears in that column (see the value catalogue). If the entity belongs "
            "to a different column, filter THAT column instead." + suffix
        )

    def _build_value_hints(self, sql: str, col_catalog: list[dict], ast) -> list[str]:
        """Render value-catalogue lines for the columns the failing SQL touched."""
        wanted: set[str] = {c.lower() for c in value_anchoring.equality_predicate_columns(sql)}
        wanted |= {c.lower() for c in (getattr(ast, "column_refs", ()) or ())}
        hints: list[str] = []
        seen: set[str] = set()
        for c in col_catalog:
            tail = c["qualified_name"].rsplit(".", 1)[-1].lower()
            if tail in wanted and tail not in seen:
                seen.add(tail)
                hints.append(value_anchoring.render_catalog_from_meta(c["qualified_name"], c))
        return hints[:40]

    def _unknown_columns(self, ast, col_catalog: list[dict], sql: str) -> list[str]:
        if not col_catalog:
            return []
        known = {c["qualified_name"].rsplit(".", 1)[-1].lower() for c in col_catalog}
        aliases = value_anchoring.select_aliases(sql)
        out: list[str] = []
        for c in getattr(ast, "column_refs", ()) or ():
            cl = c.lower()
            if cl not in known and cl not in aliases and cl != "*":
                out.append(c)
        return out[:20]

    async def _advisory_repair(self, sql, ast, col_catalog, question, dataset_id, bundle) -> str | None:
        """Non-error reasons to ask the critic to reconsider an already-OK result.

        Rides the non-destructive loop (round-2 #4): under-covered value groups (#7)
        and signed-measure double-subtraction (#5B). Returns a combined message or None.
        """
        reasons: list[str] = []
        if self._settings.group_coverage_repair_enabled:
            lits = value_anchoring.extract_question_literals(question)
            for g in value_anchoring.group_coverage_gaps(sql, col_catalog, lits):
                col = g["column"].rsplit(".", 1)[-1]
                reasons.append(
                    f"The filter on `{col}` lists only SOME of the values the question's group "
                    f"covers; it is MISSING {g['missing']!r}. Include ALL of them (IN-list) or use "
                    f"an anchored LIKE; keep the original only if the exclusion is genuinely intended."
                )
        if self._settings.signed_measure_repair_enabled:
            hint = await self._signed_measure_hint(sql, ast, col_catalog, dataset_id)
            if hint:
                reasons.append(hint)
        return " ".join(reasons) if reasons else None

    async def _signed_measure_hint(self, sql, ast, col_catalog, dataset_id) -> str | None:
        """Probe whether the SQL subtracts a term whose SIGNED measure is already
        stored negative (so subtracting double-counts the sign). Best-effort (#5B)."""
        try:
            mixed = {
                c["qualified_name"].rsplit(".", 1)[-1].lower()
                for c in col_catalog
                if c.get("mixed_sign") and value_anchoring.semantic_role(c.get("semantic_type")) == "measure"
            }
            if not mixed:
                return None
            terms = value_anchoring.signed_subtraction_terms(sql)
            subtracted = [
                t
                for t in terms
                if t["sign"] < 0 and t["measure_col"].lower() in mixed and t["dim_col"] and t["literals"]
            ]
            if not subtracted:
                return None
            tables = [t for t in ast.table_refs if t]
            if not tables:
                return None
            attached = await self._table_resolver.resolve(dataset_id, tables)
            if not attached:
                return None
            import asyncio

            offenders = await asyncio.to_thread(_probe_signed_terms, attached, subtracted)
            if not offenders:
                return None
            parts = "; ".join(f"{o['dim']} IN {o['literals']} sums to {o['sum']:.0f}" for o in offenders[:6])
            # build the corrected single-signed-sum pattern from ALL the formula's
            # terms (the generic fix: the data already carries the sign).
            all_terms = [
                t for t in terms if t["measure_col"].lower() in mixed and t["dim_col"] and t["literals"]
            ]
            allowed = sorted({lit for t in all_terms for lit in t["literals"]})
            dim = all_terms[0]["dim_col"]
            meas = all_terms[0]["measure_col"]
            lits_sql = ", ".join("'" + lit.replace("'", "''") + "'" for lit in allowed)
            return (
                f"SIGN ERROR (must fix): this formula SUBTRACTS terms whose measure is ALREADY STORED "
                f"NEGATIVE ({parts}). Subtracting an already-negative value double-counts the sign and "
                f"inflates the result above total revenue. The data already carries the economic sign, so "
                f"REWRITE the whole +/- expression as ONE signed sum over all its line-items: "
                f'SUM(CASE WHEN "{dim}" IN ({lits_sql}) THEN "{meas}" ELSE 0 END) -- keep the original '
                f"WHERE filters and any GROUP BY. Do NOT keep the subtraction chain."
            )
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.debug("signed-measure probe failed: %s", exc)
            return None

    async def _resolve_entities(
        self,
        dataset_id: uuid.UUID,
        question: str,
        col_catalog: list[dict],
        bundle: dict,
    ) -> dict:
        """Map question literals to the columns that actually store them (G3).

        First via the low-cardinality value catalogue (cheap), then -- for
        unresolved entity-looking literals (e.g. person names in a high-card
        column) -- via a bounded live DuckDB scan of the dataset's tables.
        """
        empty = {"entities": [], "groups": [], "hierarchy_intent": False}
        if not self._settings.entity_resolution_enabled:
            return empty
        literals = value_anchoring.extract_question_literals(question)
        if not literals:
            return empty

        hierarchy = value_anchoring.relationship_intent(question)
        # round-2 #1: a term that umbrellas >=2 values of one column -> a group.
        groups: list[dict] = []
        if self._settings.group_resolution_enabled:
            groups = value_anchoring.resolve_value_groups(literals, col_catalog)
        group_keys = {(g["literal"].lower(), g["column"]) for g in groups}
        group_lits = {g["literal"].lower() for g in groups}

        resolved = value_anchoring.resolve_from_catalog(literals, col_catalog)
        # a single value superseded by a group is dropped (the group is the truth)
        resolved = [r for r in resolved if (r["literal"].lower(), r["column"]) not in group_keys]
        done = {r["literal"].lower() for r in resolved} | group_lits
        remaining = [lit for lit in literals if lit.lower() not in done][
            : self._settings.entity_resolution_max_literals
        ]
        if remaining:
            try:
                resolved += await self._scan_columns_for_values(dataset_id, remaining, bundle)
            except Exception as exc:  # noqa: BLE001 - resolution is best-effort
                logger.warning("live entity resolution failed: %s", exc)

        # de-dup entities by (literal, column), keeping the highest match_count
        merged: dict[tuple[str, str], dict] = {}
        for r in resolved:
            key = (r["literal"].lower(), r["column"])
            cur = merged.get(key)
            if cur is None or (r.get("match_count") or 0) > (cur.get("match_count") or 0):
                merged[key] = r
        # de-dup groups by (literal, column)
        gseen: set[tuple[str, str]] = set()
        gout: list[dict] = []
        for g in groups:
            k = (g["literal"].lower(), g["column"])
            if k not in gseen:
                gseen.add(k)
                gout.append(g)
        entities = sorted(merged.values(), key=lambda r: r.get("match_count") or 0, reverse=True)[:25]
        return {"entities": entities, "groups": gout[:12], "hierarchy_intent": hierarchy}

    async def _scan_columns_for_values(
        self,
        dataset_id: uuid.UUID,
        literals: list[str],
        bundle: dict,
    ) -> list[dict]:
        table_names = [
            (getattr(h, "metadata", {}) or {}).get("qualified_name", "").rsplit(".", 1)[-1]
            for h in (bundle.get("schema_inventory") or [])
            if (getattr(h, "metadata", {}) or {}).get("kind") == "TABLE"
        ]
        table_names = [t for t in dict.fromkeys(table_names) if t]
        if not table_names:
            return []
        attached = await self._table_resolver.resolve(dataset_id, table_names)
        if not attached:
            return []
        import asyncio

        return await asyncio.to_thread(_scan_sync, attached, literals)


def _probe_signed_terms(attached_tables: dict[str, str], terms: list[dict]) -> list[dict]:
    """Sum each subtracted term's measure over its line-items; report the ones that
    sum NEGATIVE (already stored negative → subtracting double-counts). Best-effort."""
    try:
        import duckdb
    except ImportError:  # pragma: no cover
        return []
    paths = list(attached_tables.values())
    if not paths:
        return []
    offenders: list[dict] = []
    conn = None
    try:
        conn = duckdb.connect(":memory:")
        conn.execute("SET threads=2")
        for t in terms:
            mq = t["measure_col"].replace(chr(34), chr(34) * 2)
            dq = t["dim_col"].replace(chr(34), chr(34) * 2)
            in_list = ", ".join("'" + str(lit).replace("'", "''") + "'" for lit in t["literals"])
            total = None
            for path in paths:
                try:
                    cols = {
                        c[0].lower()
                        for c in conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
                    }
                    if t["measure_col"].lower() not in cols or t["dim_col"].lower() not in cols:
                        continue
                    s = conn.execute(
                        f"SELECT SUM(TRY_CAST(\"{mq}\" AS DOUBLE)) FROM read_parquet('{path}') "
                        f'WHERE CAST("{dq}" AS VARCHAR) IN ({in_list})'
                    ).fetchone()
                    if s and s[0] is not None:
                        total = (total or 0.0) + float(s[0])
                except Exception:  # noqa: BLE001
                    continue
            if total is not None and total < 0:
                offenders.append({"dim": t["dim_col"], "literals": t["literals"], "sum": total})
    except Exception:  # noqa: BLE001
        return offenders
    finally:
        if conn is not None:
            conn.close()
    return offenders


def _scan_sync(attached_tables: dict[str, str], literals: list[str]) -> list[dict]:
    """Find which column stores each question literal: one bounded scan per table.

    For each table we run a single pass that, per VARCHAR column, returns the
    first stored value equal (case-insensitively) to any of the literals. This
    resolves high-cardinality entities (person/brand names) the low-cardinality
    value catalogue can't carry. Best-effort + dataset-agnostic.
    """
    try:
        import duckdb
    except ImportError:  # pragma: no cover
        return []
    lits = [s.lower() for s in literals if s]
    if not lits:
        return []
    in_list = ", ".join("'" + s.replace("'", "''") + "'" for s in lits)
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for tname, path in attached_tables.items():
        conn = None
        try:
            conn = duckdb.connect(":memory:")
            conn.execute("SET threads=2")
            desc = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
            vcols = [
                d[0] for d in desc if str(d[1]).upper().startswith(("VARCHAR", "TEXT", "STRING", "CHAR"))
            ][:80]
            if not vcols:
                continue
            cols_sql = []
            for i, c in enumerate(vcols):
                cq = c.replace(chr(34), chr(34) * 2)
                pred = f'lower(CAST("{cq}" AS VARCHAR)) IN ({in_list})'
                cols_sql.append(f'MAX(CASE WHEN {pred} THEN CAST("{cq}" AS VARCHAR) END) AS m{i}')
                # match_count: how many rows this column has the literal in. A value
                # that REPEATS is a grouping/parent key; one that appears once is an
                # identity. Same single scan -- no extra cost.
                cols_sql.append(f"SUM(CASE WHEN {pred} THEN 1 ELSE 0 END) AS c{i}")
            row = conn.execute(f"SELECT {', '.join(cols_sql)} FROM read_parquet('{path}')").fetchone()
            if not row:
                continue
            for i, c in enumerate(vcols):
                val = row[2 * i]
                cnt = row[2 * i + 1]
                if val is None:
                    continue
                key = (str(val).lower(), f"{tname}.{c}")
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "literal": str(val),
                        "column": f"{tname}.{c}",
                        "value": val,
                        "match_count": int(cnt or 0),
                    }
                )
        except Exception:  # noqa: BLE001 - resolution is best-effort
            continue
        finally:
            if conn is not None:
                conn.close()
    return found
