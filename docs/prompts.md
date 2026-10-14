# flyquery — Agent Prompts

## Table of Contents

1. [Overview](#1-overview)
2. [GroundingAgent](#2-groundingagent)
3. [GenerationAgent](#3-generationagent)
4. [CriticAgent](#4-criticagent)
5. [ExplainerAgent](#5-explaineragent)
6. [DescribeAgent](#6-describeagent)
7. [RelationProposerAgent](#7-relationproposeragent)
8. [RenameDetectionAgent](#8-renamedetectionagent)
9. [Agent construction pattern](#9-agent-construction-pattern)

---

## 1. Overview

flyquery uses seven `FireflyAgent` instances, all built via the shared
`build_agent` factory from `core/agents/builder.py`. Each agent:

- Has a single `_INSTRUCTIONS` string that defines its behaviour.
- Takes a structured Pydantic `output_type` — no tool calls; LLM output is
  parsed directly into the schema.
- Is built fresh per call (`auto_register=False`) to avoid shared state.
- Uses Agentic's logging and observability defaults and the factory's
  configured prompt-cache policy.

Source of truth: `src/flyquery/core/agents/*.py`.

The four query-pipeline agents run per `POST /query` call. The three
ingestion agents run inside `IngestWorker` during specific stages.

---

## 2. GroundingAgent

**Source:** `src/flyquery/core/agents/grounding_agent.py`

**Stage / pipeline:** Query pipeline — first LLM call.

**Model default:** `FLYQUERY_GROUNDING_MODEL` (default: `anthropic:claude-sonnet-4-6`)

### Output type

```python
class GroundedTable(BaseModel):
    table_qualified_name: str
    relevance: float  # [0, 1]

class GroundedColumn(BaseModel):
    column_qualified_name: str
    relevance: float  # [0, 1]

class GroundedJoin(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    relationship: Literal["inner", "left", "right", "outer"] = "inner"

class GroundedMetric(BaseModel):
    metric_name: str
    relevance: float  # [0, 1]

class GroundedContext(BaseModel):
    path: Literal["SEMANTIC_LAYER", "SYNTHESIS", "HYBRID"]
    tables: list[GroundedTable]
    columns: list[GroundedColumn]
    joins: list[GroundedJoin]
    metrics: list[GroundedMetric]
    examples_used: list[str]
    glossary_terms: list[str]
    confidence: float  # [0, 1]
    missing_info: list[str] | None  # only when confidence < 0.55
    starting_point_sql: str | None  # from prior turn drill-down
```

### Input shape

The agent receives (via the user message):
- The NL question.
- Retrieved schema metadata: table descriptions, column names/types/samples,
  approved relations, published metrics, approved examples, glossary terms.
- (If conversation): `starting_point` block with `{executed_sql, table_qnames, snapshot_pins}`.

### Instructions (verbatim from source)

```
You are a SQL grounding agent. You receive a natural-language question
plus retrieved schema metadata (tables, columns, samples, descriptions,
relations, examples, semantic metrics, glossary).

Your job: pick the MINIMAL set of tables + columns + joins to answer
the question. Output a GroundedContext with:
- path: SEMANTIC_LAYER if a published metric covers the question,
  SYNTHESIS otherwise (HYBRID if both contribute)
- tables, columns, joins (with reasoning)
- confidence ∈ [0, 1]
- missing_info: list of ambiguities the user should resolve, ONLY when
  confidence is below 0.55 — otherwise leave None

If the user is in a conversation and the prior turn provided a
starting_point_sql, treat it as the base SELECT and identify only
which deltas the new question requires.

Never invent tables or columns. Use only what's in the retrieved
metadata.
```

### Iterative expansion

If `confidence < FLYQUERY_GROUNDING_MIN_CONFIDENCE` and `missing_info` is
non-empty, `QueryService` expands the retrieval (top-30 → wider window) and
calls the agent again. This loop runs up to `FLYQUERY_EXPAND_ITERS=2` times.
If still below threshold, a `clarification` SSE frame is emitted alongside
the best-effort answer.

---

## 3. GenerationAgent

**Source:** `src/flyquery/core/agents/generation_agent.py`

**Stage / pipeline:** Query pipeline — second LLM call (SYNTHESIS / HYBRID path).

**Model default:** `FLYQUERY_GENERATION_MODEL` (default: `anthropic:claude-sonnet-4-6`)

### Output type

```python
class GeneratedCandidate(BaseModel):
    sql: str
    reasoning: str
    confidence: float  # [0, 1]

class GeneratedCandidates(BaseModel):
    candidates: list[GeneratedCandidate]  # N items, ordered by confidence descending
```

### Input shape

The agent receives:
- The NL question.
- The `GroundedContext` from `GroundingAgent`.
- `N` (from `FLYQUERY_GENERATION_CANDIDATES`, default 3).
- (If conversation): `starting_point_sql`.

### Instructions (verbatim from source)

```
You are a SQL generation agent. You receive a GroundedContext
(tables, columns, joins, metrics) plus the NL question.

Generate exactly N candidate SQL queries against DuckDB, ordered by
confidence (highest first). Each candidate must:
- Use only the tables and columns from the grounded context
- Use the joins specified
- Be a SINGLE statement (no multi-statement; no DDL)
- Be a SELECT against ingested tables (no DML on UPLOADED tables)
- Prefer semantic-layer metrics over re-derived aggregations

Trust order: SEMANTIC_LAYER > UPLOADED_TABLE.

If the GroundedContext provides a starting_point_sql, your candidates
should be deltas (added WHERE clause, swapped column, etc.) — do not
rewrite from scratch unless necessary.

Output exactly the GeneratedCandidates structure.
```

### Candidate selection

The `CriticAgent` receives all N candidates and the DuckDB execution result
of the top-1 candidate. If the top-1 succeeds, the Critic ranks N candidates
by quality and picks the best. If the top-1 fails, the Critic repairs it.

---

## 4. CriticAgent

**Source:** `src/flyquery/core/agents/critic_agent.py`

**Stage / pipeline:** Query pipeline — invoked on execution error; optionally on
success to rank N>1 candidates.

**Model default:** `FLYQUERY_CRITIC_MODEL` (default: `anthropic:claude-sonnet-4-6`)

### Output type

```python
class RefinedSql(BaseModel):
    sql: str
    reasoning: str
    confidence: float  # [0, 1]
```

### Input shape

The agent receives:
- The failing (or all N) candidate SQL statements.
- The DuckDB error message (if error).
- The `GroundedContext`.

### Instructions (verbatim from source)

```
You are a SQL critic. You receive a candidate SQL that FAILED execution
(DuckDB error + error message) AND the GroundedContext.

Produce a corrected SQL. Common errors to fix:
- Misnamed columns/tables (the grounded context is authoritative)
- Wrong join conditions
- Missing GROUP BY
- Type-coercion issues (e.g. comparing TEXT to INTEGER)
- Aggregation in WHERE (move to HAVING)

Stay within the grounded context's table+column set. Do not introduce
new tables or columns.
```

### Retry loop

`QueryService` calls the CriticAgent up to `FLYQUERY_MAX_REFINE_RETRIES=2`
times. Each iteration:
1. CriticAgent returns `RefinedSql`.
2. The refined SQL passes through the AST firewall.
3. DuckDB executes it.
4. If execution still fails, loop (up to max retries).

After exhausting retries, `execution_status=FAILED` is recorded. Cost events
are recorded for each CriticAgent invocation under the originating `query_id`.

---

## 5. ExplainerAgent

**Source:** `src/flyquery/core/agents/explainer_agent.py`

**Stage / pipeline:** Query pipeline — final LLM call; runs regardless of
SEMANTIC_LAYER vs SYNTHESIS path.

**Model default:** `FLYQUERY_EXPLAINER_MODEL` (default: `anthropic:claude-haiku-4-5`)

A cheaper/faster model is used here because the task (summarise the data
result) has lower hallucination risk than SQL generation.

### Output type

```python
class ResultExplanation(BaseModel):
    summary: str           # 1-3 sentence NL answer using the data
    chart_hint: Literal["line", "bar", "table", "pie", "none"]
```

### Input shape

The agent receives:
- The original NL question.
- The executed SQL.
- The row count.
- Up to 50 rows of the result preview (from `flyquery_query_results.result_preview_json`).

### Instructions (verbatim from source)

```
You are a result explainer. You receive: the original question, the
executed SQL, the row count, and up to 50 rows of the result preview.

Output:
- summary: a 1-3 sentence direct answer to the question using the
  data (e.g. "Total revenue across all regions is $12,345. The
  Northeast region accounted for 42%.")
- chart_hint: pick the visualisation that best fits the result shape.
  - 1 row × 1 col → "none"
  - many rows × 2 cols (1 categorical + 1 numeric) → "bar" or "pie"
  - many rows × 2 cols (1 temporal + 1 numeric) → "line"
  - otherwise → "table"

Never invent numbers. Cite only what's in the result preview.
```

### Chart hint contract

The `chart_hint` field is advisory. flydesk-frontend (v1+) renders the result
using the hint but falls back to `"table"` if the result shape contradicts
the hint. The value is also stored on `flyquery_queries.chart_hint` for
analytics.

---

## 6. DescribeAgent

**Source:** `src/flyquery/core/agents/describe_agent.py`

**Stage / pipeline:** Ingestion pipeline — Stage 7 (describe).

**Model default:** `FLYQUERY_DESCRIBE_MODEL` (default: `anthropic:claude-haiku-4-5`)

### Output type

```python
class DescribedColumn(BaseModel):
    qualified_name: str         # "dataset.table.column"
    description: str            # 1-2 sentences, business-flavoured
    synonyms: list[str]         # 3-8 alternative business names

class DescribedObjects(BaseModel):
    columns: list[DescribedColumn]
```

### Input shape

A batch of columns (up to `FLYQUERY_DESCRIBE_BATCH=20`), each with:
- `qualified_name` (dataset.table.column)
- `data_type`
- `samples` (sample values from stage 4)
- `table_context` (other columns in the same table — for disambiguation)

### Instructions (verbatim from source)

```
You receive a batch of database columns in JSON format. Each column has:
qualified_name (dataset.table.column), data_type, samples (sample values),
and table_context (other columns in the same table).
For each column, write:
(1) a 1-2 sentence business-oriented description explaining what the column
stores and how it might be used by a business analyst, and
(2) 3-8 alternative business names (synonyms) that an analyst might use to
refer to this column.
Be concise and precise. Avoid restating the column name in the description.
Output every column from the input — do not skip any.
```

### Budget management

The DescribeAgent is called in batches until either all columns are described
or `FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN` (default $2.00) is exhausted.
When budget runs out, the remaining columns are deferred to a follow-up
`DESCRIBE_PASS` job. The `flyquery_ingest_events.budget_remaining_cents` field
tracks spend across the run.

---

## 7. RelationProposerAgent

**Source:** `src/flyquery/core/agents/relation_proposer_agent.py`

**Stage / pipeline:** Ingestion pipeline — Stage 6 (relation discovery, part b).

**Model default:** `FLYQUERY_RELATION_PROPOSER_MODEL` (default: `anthropic:claude-sonnet-4-6`)

A stronger model than Describe/Explain because cross-table semantic reasoning
is harder.

### Output type

```python
class ProposedRelation(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: float   # [0, 1]
    reason: str

class ProposedRelations(BaseModel):
    items: list[ProposedRelation]
```

### Input shape

All tables in the dataset (not just the newly uploaded one), each with:
- Column names, data types, descriptions, sample values.
- Approximate row count / cardinality.

### Instructions (verbatim from source)

```
You receive a list of tables in a single dataset, each with column names,
descriptions, samples and approximate cardinality. Identify cross-table
join candidates that are NOT exact name matches (the heuristic detector
already covers those). Examples: orders.email <-> customers.email
(non-PK match); shipments.tracking_no <-> tracking_events.tracking_id
(naming-mismatch but semantically equivalent). Output up to N proposals
per table-pair with confidence in [0,1] and a brief reason. Never invent
columns; only refer to ones actually present in the input.
```

### Approval flow

RelationProposerAgent output is persisted as `kind=AGENT_PROPOSED,
status=PROPOSED`. These proposals do NOT enter the retrieval pool until an
operator approves via:

```
POST /api/v1/datasets/{id}/relations/{rel_id}:approve
→ status=APPROVED, kind=MANUAL
```

Compare to `kind=HEURISTIC` proposals, which can enter retrieval (but not
query execution) at confidence ≥ `FLYQUERY_RELATION_HEURISTIC_MIN_CONFIDENCE`.

---

## 8. RenameDetectionAgent

**Source:** `src/flyquery/core/agents/rename_detection_agent.py`

**Stage / pipeline:** Ingestion pipeline — Stage 3 (reconcile + persist snapshot).
Only invoked when column reconciliation is ambiguous.

**Model default:** `FLYQUERY_RENAME_DETECT_MODEL` (default: `anthropic:claude-haiku-4-5`)

**Max output tokens:** 2048 (tight cap; rename reasoning is short).

### Output type

```python
class RenameProposal(BaseModel):
    removed_column: str
    new_column: str
    confidence: float   # [0, 1]
    rationale: str

class RenameProposals(BaseModel):
    items: list[RenameProposal]  # ranked, most likely first
```

### Input shape

- The removed column: name, data type, description, sample values.
- A list of candidate new columns: name, data type, description, sample values.

### Instructions (verbatim from source)

```
You receive a removed database column and a list of candidate replacement
columns from the new schema snapshot. The removed column may have been
renamed to one of the candidates.
For each candidate, assess how likely it is to be the same column under a
different name, considering: name similarity, data type compatibility,
description similarity, and sample value overlap.
Return a ranked list of proposals with confidence in [0,1] and a brief
rationale. Rank from most to least likely.
If no candidate is a plausible rename (they are genuinely new columns),
return an empty items list.
```

### Auto-confirm threshold

`AUTO_CONFIRM_THRESHOLD = 0.8`. If the top proposal's confidence is ≥ 0.8,
reconciliation automatically confirms the rename and inserts
`flyquery_schema_changes` with `change=RENAMED`. Below 0.8, the row is
inserted as `change=RENAMED_CANDIDATE` for operator review via:

```
POST /api/v1/schema-changes/{id}:confirm
```

---

## 9. Agent construction pattern

All seven agents share the same construction recipe:

```python
from flyquery.core.agents.builder import build_agent

def build_my_agent(settings):
    return build_agent(
        name="flyquery-<name>",
        model=settings.<model_field>,
        output_type=MyOutputType,
        instructions=_INSTRUCTIONS,
        settings=settings,
    )
```

The service-specific `build_agent` factory wires:
- `auto_register=False` — each agent instance is fresh per call; no shared
  pydantic-ai registry state.
- Agentic's default logging and observability middleware, without duplicate
  instances. `build_agent_middleware()` adds the configured cache policy.
- `max_output_tokens` — defaults to `FLYQUERY_AGENT_MAX_OUTPUT_TOKENS=8192`.
  `RenameDetectionAgent` overrides to 2048.

### Provider prompt caching

`FLYQUERY_PROMPT_CACHE` defaults to `on`. Set it to `off`, `0`, `false`, or
`no` to stop the factory from adding prompt-cache middleware. The factory
reads the setting each time it constructs an agent; agents already running
keep their existing policy.

For direct Anthropic models, the policy marks static system instructions for
a five-minute provider cache. It does not mark conversation messages or tool
definitions. It adds no shared OpenAI cache routing key and creates no Gemini
cached-content resources. Claude through Bedrock/OpenRouter and other providers
receive no additional cache configuration from this policy.

This is provider prompt caching, not a flyquery result cache. Each request
still runs its agent; SQL results and user/tool responses are not memoized or
reused by this middleware. Turning the switch off does not disable a provider's
automatic caching or override cache settings explicitly supplied by a caller.
The local tests verify the settings received by real `FireflyAgent` runs using
`TestModel`; they do not measure provider cache hits, billing, or retention.

**Agent test mocking note:** Per the `agent_test_mocking` memory,
`stream.usage()` and `result.usage()` in mocks must return `None` (not a
`MagicMock`). Returning `MagicMock` causes arithmetic errors in the
cost-tracking middleware.

For the full lock-step module list see
[architecture.md § Lock-step modules](architecture.md#9-lock-step-modules).
