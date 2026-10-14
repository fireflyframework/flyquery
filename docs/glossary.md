# flyquery — Glossary

Precise definitions for terms used in the flyquery API, documentation, and
source code. Terms are alphabetical within each section.

---

## Resource hierarchy

**tenant**
The top-level isolation boundary. Corresponds to a customer organisation.
Every flyquery resource carries `tenant_id`. RLS policies enforce that rows
are only visible when `app.tenant_id` matches.

**workspace**
A scoped environment within a tenant. Corresponds to a team, project, or
environment (e.g., "analytics", "finance", "staging"). Every flyquery
resource carries `workspace_id`. RLS policies enforce the workspace boundary.
Stored in `flyquery_workspaces`.

**dataset**
A logical container for related tables. A dataset groups together files that
form a coherent analytical subject (e.g., "Q1 Sales Data", "Customer CRM
Export"). Stored in `flyquery_datasets`. A dataset has a `drift_policy` and
an `ingest_policy_json`.

**file**
A single uploaded binary. One `flyquery_files` row per upload. A file may
produce multiple tables (e.g., an XLSX with 3 sheets produces 3 tables from
one file). The original blob is retained in object storage for audit and
re-derive purposes.

**table**
A logical table identity within a dataset. A table has a stable `table_id`
across re-uploads. Kind is `UPLOADED` (from a file) or `DERIVED` (from
`POST /tables:derive`). Stored in `flyquery_tables`.

**snapshot**
An immutable, versioned copy of a table's Parquet data. Created each time a
table is (re-)uploaded. Identified by `snapshot_id`. The current active
snapshot is pointed to by `flyquery_tables.current_snapshot_id`, which flips
atomically in stage 10 when the new snapshot reaches `READY`. Stored in
`flyquery_schema_snapshots`.

**schema object**
A row in `flyquery_schema_objects` representing either a table
(`kind=TABLE`) or a column (`kind=COLUMN`). Carries `description`,
`pii_tag`, `sample_values_json`, `profile_json`, `embedding`, and
`content_tsv` (for BM25). Schema objects are the primary metadata indexed
for hybrid retrieval.

**relation**
A proposed or approved cross-table join in `flyquery_relations`. Has a `kind`
(`HEURISTIC`, `AGENT_PROPOSED`, `MANUAL`) and a `status` (`PROPOSED`,
`APPROVED`, `REJECTED`). Approved relations are used in the query pipeline.

**semantic metric**
A MetricFlow-shape YAML definition of a business metric (e.g., "monthly
recurring revenue"). Stored in `flyquery_semantic_metrics`. Published metrics
can be used by the GroundingAgent via the `SEMANTIC_LAYER` path.

**glossary term**
A workspace-scoped business vocabulary entry in `flyquery_glossary_terms`.
Injected into the retrieval context to help agents interpret domain-specific
language (e.g., "ARR" = "Annual Recurring Revenue").

**example**
A `(question, SQL)` pair in `flyquery_examples` used for Vanna-style few-shot
retrieval. Has `source` (`USER_CURATED` or `AGENT_LEARNED`) and `quality`
(`PROPOSED`, `APPROVED`, `REJECTED`). Only `APPROVED` examples participate
in retrieval.

---

## Query pipeline

**query**
A single invocation of the query pipeline (one NL question + answer). Stored
in `flyquery_queries` (append-only). Each query has a unique `query_id`.

**conversation turn**
A single question-answer exchange within a conversation. Stored in
`flyquery_conversation_turns`. Each turn records `executed_sql`,
`table_qnames_json`, and `snapshot_pins_json` for drill-down continuity.

**agent token**
A long-lived bearer token (`agt_<8hex>_<32hex>`) that authenticates
non-human callers. Stored (hash-only) in `flyquery_agent_tokens`. Carries
`scopes_json`, `workspace_allowlist_json`, `dataset_allowlist_json`,
`rate_limit_rpm`.

**scope**
A permission string that grants access to a flyquery API surface. Examples:
`flyquery.query:read`, `flyquery.files:upload`, `flyquery.schema:annotate`.
See [api-reference.md § Scope catalog](api-reference.md).

**ingest job**
A unit of async work for the ingestion pipeline. Stored in
`flyquery_ingest_jobs`. Has a `job_kind` and `status` state machine.

**ingest event**
A per-stage progress record in `flyquery_ingest_events`. One row per stage
transition. Used to stream SSE progress and to reconstruct a timeline of
what happened during ingestion.

**audit event**
An append-only record in `flyquery_audit_events` of a significant mutation
(workspace created, file uploaded, query executed, PII tagged, etc.).
Never updated or deleted.

**cost event**
An append-only record in `flyquery_cost_events` of LLM usage (tokens, model,
estimated cost). Associated with a `query_id` or `ingest_job_id`.

---

## Ingestion

**RENAMED_CANDIDATE**
A `flyquery_schema_changes.change` value indicating that a column was removed
and a candidate replacement was found, but the match is ambiguous. Requires
operator confirmation via `POST /schema-changes/{id}:confirm`.

**kind=UPLOADED**
The `flyquery_tables.kind` value for tables that originate from user file
uploads. UPLOADED tables are read-only; DML is rejected by the AST firewall.

**kind=DERIVED**
The `flyquery_tables.kind` value for tables created via `POST /tables:derive`
(SQL materialisation). DERIVED tables accept DML under
`flyquery.derived:write` scope.

**PROPOSED / APPROVED / REJECTED**
The `status` values on `flyquery_relations` and `flyquery_examples`.
`PROPOSED` means pending review; `APPROVED` means active and used;
`REJECTED` means excluded.

**AGENT_LEARNED**
The `flyquery_examples.source` value for examples auto-inserted by the
query pipeline after a clean first-shot OK run. Always created as
`quality=PROPOSED`; requires operator approval to enter the retrieval pool.

---

## Technical

**RLS**
Row Level Security. A Postgres feature that enforces access control at the
row level using policies. All `flyquery_*` tables have `ENABLE ROW LEVEL
SECURITY` + `FORCE ROW LEVEL SECURITY`. Policies use
`current_setting('app.tenant_id')` and `current_setting('app.workspace_id')`
GUCs.

**GUC**
Grand Unified Configuration — Postgres session/transaction parameter. flyquery
binds `app.tenant_id` and `app.workspace_id` as `SET LOCAL` GUCs in the
`after_begin` hook of every database session. `SET LOCAL` scopes the GUC to
the current transaction.

**BYPASSRLS**
A Postgres role attribute that exempts the role from RLS policies. The
`flyquery_admin` role has BYPASSRLS (for migrations). The `flyquery_app` role
(runtime) must NOT have BYPASSRLS.

**lock-step**
The local source-contract check: nineteen normalized historical shared
baselines and two reviewed service-specific agent/cache variants. It rejects
drift without asserting that current canon/radar main has identical files.
See [architecture](architecture.md#9-lock-step-modules).

**hybrid retrieval**
The retrieval strategy combining BM25 (full-text search via `content_tsv`)
and dense vector search (pgvector HNSW on `embedding`) fused via RRF
(Reciprocal Rank Fusion).

**RRF**
Reciprocal Rank Fusion. A rank-fusion algorithm that combines two ranked
lists: `score = 1 / (k + rank)` where `k=FLYQUERY_RRF_K` (default 60).
Ranks from BM25 and pgvector are fused before the cross-encoder reranker.

**AST classifier**
The sqlglot component that classifies generated, rewritten, or direct SQL
and admits only reviewed pure function names and supported table sources.
`ScopeGuard` checks registered metadata and grants; the executor independently
reclassifies SQL. See the [SQL read boundary](security-model.md#sql-read-boundary).

**ScopeGuard**
The component that checks SQL classification, token scopes, table kind,
registered table metadata, and dataset allowlists before execution. Actor
authentication, workspace restrictions, and Postgres RLS remain upstream.

**MetricFlow**
The OSI/MetricFlow-shape YAML format used for semantic metrics in flyquery.
A published metric has a `compiled_sql_template` that the
`SemanticCompiler` expands to a DuckDB SELECT.

**PROPOSED (examples)**
The initial quality state of `AGENT_LEARNED` examples. PROPOSED examples are
NOT in the retrieval pool. An operator calls `POST /examples/{id}:approve`
to promote to `APPROVED`.

**RENAMED_CANDIDATE**
See Ingestion section above. Also appears in `flyquery.schema` event
`diff_summary.renamed_candidates`.

**snapshot_pins**
The `{table_id: snapshot_id}` map stored on `flyquery_queries` and
`flyquery_conversation_turns`. Ensures that re-running a historical query
or a drill-down conversation step uses the same Parquet data that answered
the original question.

**CalVer**
flyquery's versioning scheme: `YY.MM.Patch` (e.g., `26.5.3`). Breaking
changes ship as `Patch+1` within the same month, signalled in CHANGELOG.

**httpfs**
A DuckDB extension that enables reading remote files via HTTP/S3/GCS/Azure.
The current query executor does not load httpfs and disables extension
autoload/install and external access. Remote query workflows are unqualified;
see the [SQL read boundary](security-model.md#sql-read-boundary).

**presigned URL**
A time-limited, single-object URL generated by the ObjectStore for result
download. TTL is `FLYQUERY_OBJECT_STORE_PRESIGN_TTL_S` (default 86400 s).
flyquery never returns raw storage URIs.

**IngestWorker**
The long-running background process (`uv run flyquery worker`) that consumes
jobs from the `flyquery.ingest` EDA topic and executes the 10-stage ingestion
pipeline.

**EDA**
Event-Driven Architecture. flyquery uses an EDA topic (`flyquery.ingest`) to
decouple uploads from ingestion, and another (`flyquery.schema`) to notify
downstream services of schema changes.
