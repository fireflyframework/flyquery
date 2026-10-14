# flyquery — Pipelines

## Table of Contents

1. [Overview](#1-overview)
2. [Upload + 10-stage ingestion pipeline](#2-upload--10-stage-ingestion-pipeline)
3. [Query pipeline](#3-query-pipeline)
4. [Mode coupling: synchronous vs async via EDA](#4-mode-coupling-synchronous-vs-async-via-eda)

---

## 1. Overview

flyquery has two main pipelines:

- **Ingestion pipeline** — takes a raw user-uploaded file, materialises it to
  Parquet on object storage, and populates the schema knowledge base (samples,
  profiles, PII tags, embeddings, relation proposals). Runs asynchronously via
  the EDA topic `flyquery.ingest`. See [ingestion.md](ingestion.md) for
  stage-by-stage detail.

- **Query pipeline** — takes a natural-language question, retrieves relevant
  schema metadata, and generates auditable SQL via four agents
  (Grounding → Generation → Critic → Explainer). Runs synchronously per call
  or streams over SSE.

Both pipelines share the same infrastructure: Postgres + pgvector for state,
object storage for blobs, `pyfly.eda` for async fan-out, and the
`fireflyframework-agentic` `build_agent` factory for every LLM call.

---

## 2. Upload + 10-stage ingestion pipeline

### Entry points

```
POST /api/v1/datasets/{dataset_id}/files        first upload (multipart)
PUT  /api/v1/datasets/{ds}/tables/{table_id}:upload   re-upload into existing slot
POST /api/v1/agent/datasets/{id}/files          agent-tier mirror (X-Agent-Token)
```

Both entry points:
1. Write the raw file bytes to object storage under
   `flyquery/{tenant}/{workspace}/{dataset}/files/{file_id}.{ext}`.
2. Insert a `flyquery_ingest_jobs` row (`status=PENDING`, `job_kind=PARSE_AND_INGEST`).
3. Publish an `IngestRequested` event to the `flyquery.ingest` EDA topic.
4. Return `202 Accepted` with `{ingest_job_id}`.

The caller then polls `GET /ingest-jobs/{id}` or streams
`GET /ingest-jobs/{id}/stream` (SSE) for progress.

### Full pipeline diagram

```
POST /datasets/{id}/files   (or PUT /tables/{id}:upload)
            │
            ▼
    write bytes → object store
    files/{file_id}.{ext}           ← original blob, kept for audit + re-derive
            │
            ▼
    publish IngestRequested → "flyquery.ingest" EDA topic
            │
            ▼
    IngestWorker picks up flyquery_ingest_jobs row
    (PENDING → RUNNING)
            │
            ▼
┌─── Stage 1: receive ────────────────────────────────────────────────┐
│  Verify content_hash vs uploaded bytes.                             │
│  Enforce size cap (FLYQUERY_MAX_FILE_MB, default 2 GiB).            │
│  Detect file format from magic bytes + extension; reject mismatch   │
│  (error_code=FORMAT_MISMATCH).                                      │
│  flyquery_files.status = RECEIVED.                                  │
│  Emit SSE: event=received                                           │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 2: parse ──────────────────────────────────────────────────┐
│  FileReader dispatch by format:                                     │
│    CSV/TSV   → chardet + delimiter sniff + DuckDB read_csv_auto     │
│    XLSX/XLS/ODS → python-calamine; one table per sheet              │
│    JSON      → top-level array = 1 table; top-level object with     │
│                array-valued keys = N tables (one per key)           │
│    JSONL     → one table                                            │
│    Parquet/Avro/ORC/Arrow/Feather → schema pass-through / PyArrow   │
│    .gz/.zip/.bz2 → decompress to temp + delegate to inner reader    │
│  Apply table_extraction_rules_json overrides (sheet allowlist,      │
│  JSON path spec, header skip rows).                                 │
│  For each logical table: materialise as Parquet at                  │
│  tables/{table_id}/v{n}.parquet; capture columns + types.           │
│  Emit SSE: event=parsed {tables_extracted[]}                        │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 3: reconcile + persist snapshot ───────────────────────────┐
│  Insert flyquery_schema_snapshots (status=PARTIAL).                  │
│  If previous snapshot exists, compute column diff:                  │
│    ADDED / REMOVED / TYPE_CHANGED / RENAMED / RENAMED_CANDIDATE      │
│  Auto-RENAMED only when: position + type signature of a removed     │
│  column matches exactly ONE new column. Otherwise:                   │
│    → RenameDetectionAgent proposes RenameProposals                  │
│    → insert flyquery_schema_changes row as RENAMED_CANDIDATE        │
│      with llm_rationale (agent-generated)                           │
│  Mark vanished columns is_active=false (NOT deleted).               │
│  Annotation transplant: description(HUMAN), pii_tag(HUMAN),         │
│  business_owner, governance_json, synonyms carried verbatim.        │
│  Emit SSE: event=reconciled {n_added, n_removed, n_renamed_candidate}│
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 4: sample ─────────────────────────────────────────────────┐
│  For each added/changed column where pii_tag is NULL/NONE and       │
│  policy allows: read N=FLYQUERY_SAMPLE_N values via DuckDB.         │
│  PII scanner gate: refuse to persist if values look like PII.       │
│  Skippable via ingest_policy_json.sample_disabled=true.             │
│  Emit SSE: event=sampled {columns_sampled, columns_skipped}         │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 5: profile ────────────────────────────────────────────────┐
│  Per column: null_fraction, approx_count_distinct (DuckDB), top     │
│  values (low-cardinality), min/max (numeric + temporal).            │
│  Skipped when n_rows > FLYQUERY_PROFILE_ROW_THRESHOLD (default 10M).│
│  Persists to schema_objects.profile_json.                           │
│  Emit SSE: event=profiled {tables_profiled, tables_skipped}         │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 6: relation discovery ─────────────────────────────────────┐
│  Across ALL tables in the dataset (not just this upload):           │
│  (a) Heuristic: column-name equality + compatible types +           │
│      one-sided unique constraint (distinct ≥ 0.95 of n_rows).      │
│      → kind=HEURISTIC, status=PROPOSED,                             │
│        confidence ∝ uniqueness × name-specificity                   │
│  (b) RelationProposerAgent: inspects table + column descriptions,   │
│      samples → ProposedRelations (cross-table, non-name-match focus)│
│      → kind=AGENT_PROPOSED, status=PROPOSED, reason populated       │
│  Neither is used in queries until operator approves:                │
│    POST /datasets/{id}/relations/{rel_id}:approve                   │
│    → status=APPROVED, kind=MANUAL                                   │
│  Exception: HEURISTIC relations at confidence ≥                     │
│    FLYQUERY_RELATION_HEURISTIC_MIN_CONFIDENCE (default 0.85) are    │
│    included in retrieval (but NOT query execution) without approval. │
│  Emit SSE: event=relations_proposed                                 │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 7: describe ───────────────────────────────────────────────┐
│  Tables + columns lacking description fed to DescribeAgent in       │
│  batches of FLYQUERY_DESCRIBE_BATCH (default 20).                   │
│  Output: short business summary + 3-8 synonyms per object.          │
│  Budget cap: FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN (default $2.00) │
│  Remaining objects deferred to a follow-up DESCRIBE_PASS job.       │
│  Emit SSE: event=described {objects_described, budget_remaining}    │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 8: PII tag ────────────────────────────────────────────────┐
│  PIIScanner classifies each column from                             │
│  (column_name + description + sample_values).                       │
│  Sets schema_objects.pii_tag + pii_source.                          │
│  Policy (FLYQUERY_PII_POLICY_SAMPLES):                              │
│    warn    → log + continue                                         │
│    redact  → purge sample_values_json; log                          │
│    reject  → set is_active=false; not queryable until reviewed      │
│  Late-tag flip: if pii_tag is set after samples already persisted,  │
│    sample_values_json scrubbed in-place in the same transaction.    │
│  Emit SSE: event=pii_tagged {tags_set, redactions, late_redactions} │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 9: embed + index ──────────────────────────────────────────┐
│  Per column, build embedding text:                                  │
│    "<dataset>.<table>.<column>: <data_type>\n                       │
│     <description>\nSamples: <preview>\nSynonyms: <list>"            │
│  Per-table aggregate embedding rolls up column texts.               │
│  Persist embedding + embedding_model to schema_objects.             │
│  Refresh pgvector HNSW index + content_tsv (BM25).                 │
│  Emit SSE: event=embedded {embeddings_written}                      │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─── Stage 10: publish + close snapshot ──────────────────────────────┐
│  ATOMIC transaction:                                                │
│    flyquery_schema_snapshots.status = READY                         │
│    flyquery_tables.current_snapshot_id = new snapshot_id           │
│  Publish flyquery.schema SchemaUpdated EDA event                    │
│  (dataset_id, table_id, snapshot_id, diff_summary).                │
│  Emit SSE: event=snapshot_ready + event=final (IngestJobResult)     │
└─────────────────────────────────────────────────────────────────────┘
```

### Stage skip policy

Stages 4–8 are individually skippable via `ingest_policy_json` on the dataset.
Stages 1–3, 9, and 10 are mandatory.

| Stage | Skippable? | Config key |
|-------|-----------|-----------|
| 4: sample | Yes | `ingest_policy_json.sample_disabled=true` |
| 5: profile | Yes | `ingest_policy_json.profile_disabled=true` |
| 6: relation discovery | Yes (separately for heuristic / agent) | `FLYQUERY_RELATION_PROPOSER_ENABLED=false` |
| 7: describe | Yes (budget = 0) | `FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN=0` |
| 8: PII tag | Yes | `ingest_policy_json.pii_disabled=true` |

### Ingestion agents

| Agent | Stage | Output type | Notes |
|-------|-------|-------------|-------|
| `DescribeAgent` | 7 | `DescribedObjects` | Budget-capped per run; deferred to DESCRIBE_PASS job if over budget |
| `RelationProposerAgent` | 6 | `ProposedRelations` | Cross-table, non-name-match focus; PROPOSED until human approval |
| `RenameDetectionAgent` | 3 | `RenameProposals` | Only on ambiguous rename; auto-confirm at confidence ≥ 0.8 |

All agents follow the `build_agent` recipe: structured `output_type`,
`auto_register=False`, fresh per call, observability middleware. See
[prompts.md](prompts.md) for instruction text.

---

## 3. Query pipeline

Every `POST /api/v1/query` (and `/agent/query`) call runs this pipeline.

### Pipeline diagram

```
NL question + {conversation_id?, dataset_id?}
        │
        ▼
Hybrid Retrieval (BM25 + pgvector + RRF, k=60) over:
  flyquery_schema_objects  (TABLE + COLUMN, current snapshot, is_active=true)
  flyquery_relations       (APPROVED + HEURISTIC at confidence ≥ 0.85)
  flyquery_semantic_metrics (status=PUBLISHED)
  flyquery_glossary_terms
  flyquery_examples        (quality=APPROVED only)

        │
        ▼
Cross-encoder reranker   (top-30 → top-10)
  model: FLYQUERY_RERANKER_MODEL
  (default: cross-encoder/ms-marco-MiniLM-L-6-v2)

        │
        ▼
GroundingAgent   →   GroundedContext {
  path: SEMANTIC_LAYER | SYNTHESIS | HYBRID,
  tables[], columns[], joins[], metrics[], examples_used[],
  glossary_terms[], confidence, missing_info: list[str] | None
}
  If conversation_id: receives prior turn's
    {executed_sql, table_qnames, snapshot_pins} as starting_point_sql
  Iterative schema expansion loop (up to FLYQUERY_EXPAND_ITERS=2)
    when missing_info is non-empty and confidence < threshold
  If confidence < FLYQUERY_GROUNDING_MIN_CONFIDENCE AND missing_info:
    → emit SSE: event=clarification {questions[], reasons[]}
    (alongside the answer that follows, non-blocking)

        │
        ├── SEMANTIC_LAYER path ──────────────────────────────────────┐
        │   A published metric covers the question.                   │
        │   MetricFlow compiles the metric YAML → deterministic SQL.  │
        │   No GenerationAgent call.                                  │
        │                                                             │
        └── SYNTHESIS path ───────────────────────────────────────────┘
            GenerationAgent → GeneratedCandidates {
              candidates: N × {sql, reasoning, confidence}
            }
            N = FLYQUERY_GENERATION_CANDIDATES (default 3)
            Candidates ordered by confidence (highest first).
            If starting_point_sql set: generate delta SQL, not from scratch.

        │
        ▼
AST classifier (sqlglot) + ScopeGuard
  Rules:
    single-statement only                         → REJECTED_BY_FIREWALL
    no DDL (CREATE/DROP/ALTER/TRUNCATE)           → REJECTED_BY_FIREWALL
    no INSERT/UPDATE/DELETE on UPLOADED tables    → REJECTED_BY_FIREWALL
    no DML on DERIVED without flyquery.derived:write → REJECTED_BY_FIREWALL
    no tables outside dataset_allowlist           → REJECTED_BY_FIREWALL
    registered physical tables + closed pure function names required
    file/table functions and unknown sources are rejected

        │
        ▼
DuckDB executor (in-process, per-request)
  Reclassify SQL and verify supplied registered snapshots
  Create views over registered local Parquet; exact allowed_paths
  Disable external access and extension autoload/install; lock configuration
  SET memory_limit = FLYQUERY_DUCKDB_MEMORY_LIMIT (default 4GB)
  LIMIT default_row_cap+1 to detect SELECT overflow
  Statement timeout is unenforced; connection is not read-only

        │
   ┌────┴──────┐
   OK         ERROR
   │           │
   │          CriticAgent (up to FLYQUERY_MAX_REFINE_RETRIES=2)
   │           │  output: RefinedSql {sql, reasoning, confidence}
   │           │  loop back to AST check
   │           │
   ▼
ExplainerAgent  →  ResultExplanation {
  summary: str,          ← 1-3 sentence direct answer using the data
  chart_hint: line|bar|table|pie|none
}

        │
        ▼
Conversation memory:
  if conversation_id given → append turn with
    {executed_sql, summary, table_qnames_json, snapshot_pins_json}
  Rolling summary on conversation row
    (fed into Grounding system-instructions slot next turn)

        │
        ▼
Auto-learn:
  if execution_status=OK AND retries=0 AND no PII findings
    AND no clarification emitted
  → insert flyquery_examples
      (source=AGENT_LEARNED, quality=PROPOSED, embedding, citation=query_id)
  NOTE: PROPOSED examples do NOT enter the retrieval pool.
  An operator must POST /examples/{id}:approve to activate.

        │
        ▼
Recorder:
  → flyquery_queries (full audit row)
  → flyquery_audit_events
  → flyquery_cost_events (grounding + generation + critic + explainer costs)
  → results/{query_id}.parquet via ObjectStore (full result)
  → flyquery_query_results (preview JSON, capped at FLYQUERY_RESULT_PREVIEW_MAX_BYTES)

        │
        ▼
AnswerResponse / SSE final frame
  {answer, executed_sql, chart_hint, row_count, elapsed_ms,
   result_preview, result_url (presigned), snapshot_pins, query_id}
```

Direct SQL skips the agents and uses the same policy with registered
metadata in both synchronous and SSE handlers. Initial generated SQL and
every Critic rewrite are checked before execution. See the
[SQL read boundary](security-model.md#sql-read-boundary) for the local
Parquet workflow, copy-on-write, and remaining limits.

### Query-pipeline agents

| Agent | Output type | Model default | Notes |
|-------|-------------|---------------|-------|
| `GroundingAgent` | `GroundedContext` | `FLYQUERY_GROUNDING_MODEL` (claude-sonnet-4-6) | Iterative expansion up to `EXPAND_ITERS=2` |
| `GenerationAgent` | `GeneratedCandidates` | `FLYQUERY_GENERATION_MODEL` (claude-sonnet-4-6) | N candidates (default 3); delta SQL when conversation active |
| `CriticAgent` | `RefinedSql` | `FLYQUERY_CRITIC_MODEL` (claude-sonnet-4-6) | Always invoked on error; optionally on success to rank N>1 |
| `ExplainerAgent` | `ResultExplanation` | `FLYQUERY_EXPLAINER_MODEL` (claude-haiku-4-5) | Cheap model; 50-row preview input |

### SSE frames on /query/stream

```
event: schema_linked    data: {grounded_context_summary, semantic_path, candidate_table_count}
event: clarification    data: {questions[], reasons[]}     -- alongside answer; non-blocking
event: sql_generated    data: {candidate_count, chosen_index, candidate_summaries}
event: executed         data: {row_count, elapsed_ms, retried_after_error, snapshot_pins}
event: explained        data: {summary, chart_hint}
event: final            data: <AnswerResponse JSON>       -- includes presigned URL
event: error            data: {type, title, status, code, detail, errors[]}  -- RFC 7807
```

---

## 4. Mode coupling: synchronous vs async via EDA

### Ingestion is always async

Upload → `202 Accepted` → EDA publish → `IngestWorker`. The HTTP caller never
waits for the 10-stage pipeline to complete. Progress arrives via SSE
(`/ingest-jobs/{id}/stream`) or polling (`GET /ingest-jobs/{id}`).

```
HTTP caller                flyquery API               IngestWorker
    │                           │                          │
    │ POST /files (multipart)   │                          │
    │──────────────────────────>│                          │
    │                           │ store blob               │
    │                           │ insert ingest_job        │
    │                           │ publish IngestRequested  │──────────────>│
    │ 202 {ingest_job_id}       │                          │               │
    │<──────────────────────────│                          │ [10 stages]   │
    │                           │                          │               │
    │ GET /ingest-jobs/…/stream │                          │               │
    │──────────────────────────>│                          │               │
    │                           │<── SSE events ──────────────────────────│
    │<────── SSE events ────────│                          │               │
    │                           │                          │               │
    │     (final frame)         │                          │               │
    │<────── event: final ──────│                          │ status=DONE   │
```

### Query is synchronous (with optional SSE streaming)

```
POST /query        → synchronous; blocks until Explainer output
POST /query/stream → SSE; events arrive as each stage completes
```

The synchronous endpoint internally drains the same pipeline; it just waits
for all frames before responding.

### EDA adapter

`FLYQUERY_EDA_ADAPTER` (default: `postgres`) selects the transport.

| Adapter | Notes |
|---------|-------|
| `postgres` | Postgres LISTEN/NOTIFY (durable, default); Outbox in `flyquery_ingest_events` |
| `redis` | Redis Pub/Sub (low-latency; no durability guarantee) |
| `kafka` | Kafka topic; appropriate for high-throughput multi-consumer scenarios |
| `memory` | In-process; for testing only |

See [eda-events.md](eda-events.md) for the full event catalog and consumer guide.
See [async-ingest.md](async-ingest.md) for `IngestWorker` lifecycle details.

### Job kinds

The `flyquery.ingest` topic carries different `job_kind` values that change
which stages execute:

| Kind | Stages | Triggered by |
|------|--------|-------------|
| `PARSE_AND_INGEST` | 1–10 | New file upload or first re-upload |
| `REPARSE` | 1–10 | Operator-triggered re-ingest from existing blob |
| `SAMPLE_REFRESH` | 4 only | Manual `POST /schema-objects/{id}:sample` |
| `DESCRIBE_PASS` | 7 only | Budget overflow from a prior run |
| `RELATION_PASS` | 6 only | Dataset-level relation re-discovery |

See [async-ingest.md](async-ingest.md) for cooperative cancel semantics and
retry behaviour per kind.
