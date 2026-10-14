# flyquery — Architecture

## Table of Contents

1. [System position](#1-system-position)
2. [Resource hierarchy](#2-resource-hierarchy)
3. [Domain model (Postgres tables)](#3-domain-model-postgres-tables)
4. [Storage architecture](#4-storage-architecture)
5. [Multi-tenancy and RLS](#5-multi-tenancy-and-rls)
6. [Ingestion pipeline (10 stages)](#6-ingestion-pipeline-10-stages)
7. [Query pipeline (4 agents)](#7-query-pipeline-4-agents)
8. [Hexagonal adapters](#8-hexagonal-adapters)
9. [Lock-step modules](#9-lock-step-modules)

---

## 1. System position

flyquery is the third pillar of **Firefly Framework**, alongside flycanon
(operational knowledge repository for unstructured content) and flyradar
(operations-discovery and diagnostic intelligence).

| Service | What it stores | How you ask it |
|---------|---------------|----------------|
| **flycanon** | Documents, process artefacts, knowledge items | Natural-language RAG with citations |
| **flyradar** | Discovered process graphs, bottlenecks, dependency DAGs | Discovery jobs + diagnostic queries |
| **flyquery** | Structured files uploaded by operators | Natural-language Text-to-SQL over Parquet |

flyquery's specific responsibilities:

- **Ingestion** — every common structured-file format, multi-table extraction
  (XLSX sheets, JSON top-level arrays), per-format readers behind a hexagonal
  port, materialised to Parquet on object storage.
- **Schema knowledge base** — every table/column a workspace exposes
  (post-materialisation), with embeddings, samples, profiles, PII tags, and
  human + AI-curated descriptions. Snapshots are immutable; re-uploads produce
  new versions with annotation transplant.
- **Relation graph** — cross-table join proposals (heuristic + AI) for the
  file-upload world where no FK catalog exists.
- **Semantic layer** — MetricFlow-shape YAML metrics, dimensions, and glossary,
  versioned per dataset.
- **Example store** — `(question, SQL)` pairs for Vanna-style few-shot retrieval,
  auto-populated from successful runs as `AGENT_LEARNED/PROPOSED` until an
  operator approves.
- **Query execution** — multi-agent pipeline
  (Grounding → Generation → Executor → Critic → Explainer) gated by per-token
  scopes, closed AST admission, registered snapshot paths, row caps, PII
  scanning, and conversation-drill-down memory.
- **Audit trail** — every upload, snapshot diff, question, candidate SQL,
  executed statement, and cost event, append-only.

flyquery does **not** own:
- Ingestion of unstructured documents (flycanon).
- Operations discovery or pain-point analysis (flyradar).
- Connections to customer databases (no DSNs, no driver pool).
- dbt manifests, OpenAPI specs, or BI dashboard rendering.

---

## 2. Resource hierarchy

```
Workspace                      (identity root; RLS scope)
  └── Dataset                  logical container
        └── File               one upload; one blob in object storage
              └── Table        1 from CSV/TSV/JSONL; N from XLSX sheets;
                                N from JSON top-level array keys
                    └── Snapshot   versioned per re-upload; immutable
                    └── Schema objects   TABLE + COLUMN rows with embeddings
                    └── Relations        join proposals scoped to a dataset
```

### Identity rules

| Situation | API call | Effect |
|-----------|----------|--------|
| First upload | `POST /datasets/{id}/files` (multipart) | Creates File + one or more Tables. Returns `{file_id, tables: [{table_id, qualified_name, n_rows_estimate}]}` |
| XLSX with 3 sheets | same | Returns 3 `table_id` values |
| JSON with `{"orders": [...], "customers": [...]}` | same | Returns 2 `table_id` values |
| Re-upload into existing slot | `PUT /datasets/{ds}/tables/{table_id}:upload` | New Snapshot, same `table_id`; annotations carry forward |
| Snapshot pointer | — | `flyquery_tables.current_snapshot_id` flips atomically when a new Snapshot reaches `READY` (stage 10) |
| Snapshot pinning | — | `flyquery_queries.table_id_snapshot_pins_json` records which snapshot answered each query, keeping historical answers reproducible across re-uploads |

---

## 3. Domain model (Postgres tables)

All tables are prefixed `flyquery_`. Every multi-tenant row carries
`(tenant_id, workspace_id)`. The model mirrors flycanon's shape.

### Core entity tables

```
flyquery_workspaces
  kms_key_uri (text|null)          per-workspace CMK/CMEK URI; null = storage-native SSE
  retention_days (int|null)        null = keep forever
  allow_direct_sql (bool)          enables POST /sql:execute
  default_locale (text)            date-format hint for CSV parsing (default en-US)
  storage_used_bytes (bigint)      denormalised cache

flyquery_datasets
  id, tenant_id, workspace_id
  name (UQ per workspace)
  drift_policy (AUTO|REVIEW)
  ingest_policy_json (jsonb)       include/exclude patterns, sample disable, budget overrides
  status (ACTIVE|ARCHIVED)

flyquery_files
  id, tenant_id, workspace_id, dataset_id
  original_filename, file_format, compression
  size_bytes, content_hash_sha256
  object_store_key                 see §4 key layout
  table_extraction_rules_json      sheet allowlist, JSON path spec
  status (RECEIVED|PARSED|FAILED|DELETED)

flyquery_tables
  id, tenant_id, workspace_id, dataset_id, source_file_id
  name (UQ per dataset), qualified_name
  kind (UPLOADED|DERIVED)
  sheet_or_json_path (text|null)
  current_snapshot_id (FK|null)
  description, description_source (HUMAN|INTROSPECTED|AGENT|null)

flyquery_schema_snapshots
  id, tenant_id, workspace_id, dataset_id, table_id
  snapshot_hash (deterministic over column names + types)
  n_columns, n_rows_estimate, n_rows_actual
  parquet_object_key
  status (PARTIAL|READY|FAILED)
  triggered_by (USER|AGENT|SCHEDULED|REPARSE)

flyquery_schema_changes         append-only delta log
  column_name, change (ADDED|REMOVED|TYPE_CHANGED|RENAMED|RENAMED_CANDIDATE)
  before_json, after_json, llm_rationale

flyquery_schema_objects         query-time metadata
  kind (TABLE|COLUMN), parent_id
  qualified_name                  "dataset.table" or "dataset.table.column"
  data_type, is_nullable
  pii_tag, pii_source (REGEX|PRESIDIO|AGENT|HUMAN|null)
  sample_values_json, profile_json
  embedding (vector(1536))
  content_tsv (tsvector)          BM25 over name + description + synonyms

flyquery_relations               proposed/manual joins
  from_table_id, from_column_name, to_table_id, to_column_name
  kind (HEURISTIC|AGENT_PROPOSED|MANUAL)
  confidence, status (PROPOSED|APPROVED|REJECTED)
```

### Semantic layer tables

```
flyquery_semantic_metrics
  name (UQ per dataset), label, description
  definition_yaml, compiled_sql_template
  metric_type (SIMPLE|RATIO|DERIVED|CUMULATIVE)
  status (DRAFT|PUBLISHED|RETIRED)

flyquery_semantic_dimensions   mirror of metrics for dimensions / entities
flyquery_semantic_versions     immutable history per metric/dim
flyquery_glossary_terms        workspace-scoped (not per-dataset)
```

### Query and runtime tables

```
flyquery_examples              Vanna-style few-shot
  question, generated_sql, normalised_sql
  source (USER_CURATED|AGENT_LEARNED)
  quality (PROPOSED|APPROVED|REJECTED)
  embedding (vector(1536))

flyquery_queries               every run, append-only
  question, prior_turn_ids (uuid[])
  table_id_snapshot_pins_json
  semantic_path_taken (SEMANTIC_LAYER|SYNTHESIS|HYBRID)
  candidates_json
  executed_sql
  execution_status (OK|REFINED_OK|FAILED|REJECTED_BY_FIREWALL)
  retries (int), row_count, elapsed_ms, cost_cents

flyquery_query_results         preview cache
  result_preview_json          capped at FLYQUERY_RESULT_PREVIEW_MAX_BYTES
  result_object_key            results/{query_id}.parquet
  ttl_expires_at

flyquery_conversations         multi-turn sessions
flyquery_conversation_turns
  question, executed_sql, summary, table_qnames_json
  snapshot_pins_json           {table_id: snapshot_id}

flyquery_agent_tokens          long-lived bearer tokens
  dataset_allowlist_json
  workspace_allowlist_json
  scopes_json

flyquery_ingest_jobs           async ingest orchestration
  job_kind (PARSE_AND_INGEST|REPARSE|SAMPLE_REFRESH|DESCRIBE_PASS|RELATION_PASS)
  status (PENDING|RUNNING|SUCCEEDED|FAILED|CANCELLED)

flyquery_ingest_events         streamable per-stage progress
  stage, status, message, payload_json

flyquery_audit_events          append-only, mirrors canon_audit_events
flyquery_cost_events           mirrors canon_cost_events
  ingest_job_id (FK|null), query_id (FK|null)
```

---

## 4. Storage architecture

### Parquet on object storage + DuckDB query layer

flyquery uses a two-tier storage design:

1. **Object storage** — original upload blobs + materialised Parquet snapshots.
   Backed by `LocalFs` (dev), `S3`, `GCS`, or `Azure Blob` via the `ObjectStore`
   hexagonal port. Selected by `FLYQUERY_OBJECT_STORE`.

2. **DuckDB** — in-process per-request query engine. Creates views over
   registered local Parquet snapshots in a fresh in-memory connection.
   Connections have exact file allowlists and locked external-access settings.
   See the [SQL read boundary](security-model.md#sql-read-boundary) for admission
   rules, copy-on-write, and the unenforced statement timeout. ObjectStore
   provider support does not establish remote query support.

3. **Postgres + pgvector** — metadata, schema knowledge base, relations,
   embeddings, audit, agent tokens. The single persistent transactional store.

### Object-store key layout

All keys are namespaced by `(tenant_id, workspace_id, dataset_id)`.

```
flyquery/                              configurable prefix (FLYQUERY_OBJECT_STORE_BASE)
  {tenant_id}/
    {workspace_id}/
      {dataset_id}/
        files/{file_id}.{ext}          original upload; one blob even when a file
                                        produces multiple tables
        tables/{table_id}/v{n}.parquet  ingested-table snapshots
        derived/{table_id}/v{n}.parquet derived-table snapshots (CREATE TABLE … AS SELECT)
        results/{query_id}.parquet      full query results (TTL = FLYQUERY_RESULT_TTL_HOURS)
```

Key points:
- A single `flyquery_files` row maps to one `files/` blob, even when XLSX with
  3 sheets produces 3 `flyquery_tables` rows.
- Re-uploading a table slot creates a **new** `files/` blob → a new
  `tables/{table_id}/v{n+1}.parquet`. Previous blobs are retained until
  workspace retention expires.
- Workspace purge walks `{tenant_id}/{workspace_id}/` and removes all keys after
  a 30-day tombstone window.

---

## 5. Multi-tenancy and RLS

### Postgres role split

Two roles are required per deployment:

| Role | BYPASSRLS | Used for |
|------|-----------|---------|
| `flyquery_admin` | Yes | Migrations + cross-workspace workers |
| `flyquery_app` | No | Request-scoped queries (runtime) |

The `flyquery_app` role is bound in the runtime `DATABASE_URL`. Migrations run
via `FLYQUERY_DATABASE_URL_ADMIN`. Without this split, RLS is silently bypassed
in production.

### RLS policy (standard pattern)

Applied to every multi-tenant table:

```sql
USING (
    tenant_id   = current_setting('app.tenant_id')
    AND workspace_id = current_setting('app.workspace_id')
)
```

`FORCE ROW LEVEL SECURITY` ensures the policy applies even to table owners.

Special cases:
- `flyquery_workspaces`: policy is `tenant_id = ... AND id = current_setting('app.workspace_id')`.
- `flyquery_agent_tokens`: policy is `tenant_id = ...` (workspace check is in
  code against `workspace_allowlist_json`).

### GUC binding

`TenantContextMiddleware` (lock-step with canon) extracts `X-Tenant-Id` and
`X-Workspace-Id` from each request and issues `SET LOCAL app.tenant_id = ?` and
`SET LOCAL app.workspace_id = ?` via a SQLAlchemy `after_begin` event listener.
This is a LOCAL transaction-scoped setting — it automatically resets when the
connection returns to the pool.

---

## 6. Ingestion pipeline (10 stages)

Asynchronous, restartable, streamable, idempotent across re-ingests. Each stage
emits an SSE event (see [ingestion.md](ingestion.md) for full detail).

### System-shape: three process types

```
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│  flyquery serve      │    │ flyquery worker      │    │ flyquery worker      │
│  (API server)        │    │ ingest               │    │ retention            │
│                      │    │ (IngestWorker)       │    │ (RetentionWorker)    │
│  HTTP / SSE          │    │ EDA consumer of      │    │ Periodic loop:       │
│  controllers         │    │ flyquery.ingest      │    │  - stuck-job reaper  │
│  + services + repos  │    │ + 10-stage pipeline  │    │  - orphan republish  │
│  (sync ingest path   │    │ + retry / cancel /   │    │  - TTL deletes       │
│   in-process)        │    │   dead-letter        │    │  - PURGED hard-del   │
└──────────┬───────────┘    └──────────┬───────────┘    └──────────┬───────────┘
           │ scale: replicas           │ scale: N replicas         │ scale: 1
           │                           │ × _CONCURRENCY            │ usually
           ▼                           ▼                           ▼
      Postgres (RLS-enforced) ─ EDA bus ─ Object storage (Parquet)
```

Each is a distinct process. Production runs ≥1 of each; dev /
docker-compose can collapse all three into a single process via
`flyquery worker all` (NOT recommended for production — see
[workers.md](workers.md) for full topology + scaling guidance). The
RetentionWorker doesn't run the pipeline; it owns the cross-cutting
cleanup duties (TTL sweeps + reaping stuck `RUNNING` jobs + republishing
orphaned `PENDING` jobs) listed in
[`retention_worker.py`](../src/flyquery/core/services/retention/retention_worker.py).

```
POST /datasets/{id}/files
POST /datasets/{id}/files:async        (new in 26.5.10: 202 Accepted; Stage 1 sync, 2-10 on worker)
PUT  /datasets/{ds}/tables/{id}:upload
        │
        ▼  bytes → object store: files/{file_id}.{ext}
        │
        ▼  publish to "flyquery.ingest" EDA topic
        │
        ▼  IngestWorker: PENDING → RUNNING

┌─────── 1. receive ──────────────────────────────────┐
│  Verify content_hash, size cap, format from magic   │
│  bytes + extension. flyquery_files.status=RECEIVED. │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 2. parse ────────────────────────────────────┐
│  FileReader dispatch by format:                     │
│    CSV/TSV   → chardet + delimiter sniff + DuckDB   │
│    XLSX/ODS  → python-calamine; one table per sheet │
│    JSON      → top-level array or array-valued keys │
│    JSONL     → one table                            │
│    Parquet/Avro/ORC/Feather → pass-through / PyArrow│
│    .gz/.zip/.bz2 → decompress to temp + delegate   │
│  Apply table_extraction_rules_json overrides.       │
│  Materialise each table as Parquet in object store. │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 3. reconcile + persist snapshot ─────────────┐
│  Insert flyquery_schema_snapshots (PARTIAL).        │
│  Diff vs prior snapshot: ADDED/REMOVED/TYPE_CHANGED.│
│  Auto-RENAMED when position+type signature matches  │
│  uniquely; otherwise → RenameDetectionAgent proposes│
│  RENAMED_CANDIDATE with llm_rationale.              │
│  Annotation transplant: human description, pii_tag, │
│  business_owner, governance_json, synonyms carried  │
│  verbatim to the new snapshot.                      │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 4. sample ───────────────────────────────────┐
│  Read N=FLYQUERY_SAMPLE_N values per column via     │
│  DuckDB. PIIScanner gate prevents persisting if     │
│  values look like PII. Skippable via                │
│  ingest_policy_json.sample_disabled.                │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 5. profile ──────────────────────────────────┐
│  null_fraction, approx_count_distinct, top_values,  │
│  min/max. Skipped above FLYQUERY_PROFILE_ROW_       │
│  THRESHOLD (default 10M rows).                      │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 6. relation discovery ───────────────────────┐
│  Across ALL tables in the dataset:                  │
│  (a) Heuristic: column-name match + compatible      │
│      types + one-sided unique constraint.           │
│  (b) RelationProposerAgent inspects table/column    │
│      descriptions + samples.                        │
│  Both inserted as PROPOSED; operator approves via   │
│  POST /datasets/{id}/relations/{rel_id}:approve.    │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 7. describe ─────────────────────────────────┐
│  Tables + columns without descriptions fed to       │
│  DescribeAgent in batches. Budget cap:              │
│  FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN.            │
│  Remaining objects deferred to DESCRIBE_PASS job.  │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 8. PII tag ──────────────────────────────────┐
│  PIIScanner classifies from name + description +    │
│  samples. Policy: warn|redact|reject.               │
│  Late tag flip scrubs sample_values in-place.       │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 9. embed + index ────────────────────────────┐
│  Embedding text: "<dataset>.<table>.<column>:       │
│  <type>\n<description>\nSamples: ...\nSynonyms: ..." │
│  Per-table aggregate rolls up columns.              │
│  Persist embedding + refresh pgvector HNSW +        │
│  content_tsv for BM25.                              │
└────────────────────────┬────────────────────────────┘
                         ▼
┌─────── 10. publish + close snapshot ────────────────┐
│  Atomic transaction: snapshot.status=READY,         │
│  tables.current_snapshot_id flips.                  │
│  Publish flyquery.schema.updated EDA event.         │
│  Emit snapshot_ready + final SSE frames.            │
└─────────────────────────────────────────────────────┘
```

Stages 4–8 are skippable via `ingest_policy_json`. Stages 1–3, 9, 10 are
mandatory.

### Ingestion agents

| Agent | Output type | Stage | Notes |
|-------|-------------|-------|-------|
| `DescribeAgent` | `DescribedObjects` | 7 | Batched; budget-capped per run |
| `RelationProposerAgent` | `ProposedRelations` | 6 | Cross-table; status=PROPOSED until human approval |
| `RenameDetectionAgent` | `RenameProposals` | 3 | Only on ambiguous reconcile |
| `GovernanceClassifierAgent` *(v1+)* | `GovernanceTags` | 8 | Off by default |

---

## 7. Query pipeline (4 agents)

Every `/query` or `/agent/query` call runs through this pipeline.

```
NL question + (conversation_id?, dataset_id?)
       │
       ▼
Hybrid Retrieval (BM25 + pgvector + RRF) over schema_objects,
  relations (APPROVED + high-confidence HEURISTIC only),
  semantic_metrics (PUBLISHED), glossary, examples (APPROVED)
       │
       ▼
Cross-encoder reranker  (top-30 → top-10; FLYQUERY_RERANKER_MODEL)
       │
       ▼
GroundingAgent  →  GroundedContext {
  path: SEMANTIC_LAYER | SYNTHESIS | HYBRID,
  tables[], columns[], joins[], metrics[], examples[],
  confidence, missing_info: list[str] | None
}
  if conversation_id: receives prior turn's
    {executed_sql, table_qnames, snapshot_pins} as starting_point
  if confidence < FLYQUERY_GROUNDING_MIN_CONFIDENCE AND missing_info:
    emits clarification SSE frame alongside the answer
       │
       ├── SEMANTIC_LAYER path ──────────────────────────────────┐
       │   MetricFlow → SQL (deterministic compilation)          │
       │                                                         │
       └── SYNTHESIS path ────────────────────────────────────┐  │
           GenerationAgent → N candidates (default 3)         │  │
                                                         merge ◄──┘
       │
       ▼
AST classifier (sqlglot) + ScopeGuard
  single-statement only
  reject DDL and unknown statements
  reject INSERT/UPDATE/DELETE on uploaded tables
  reject SQL referencing tables outside dataset_allowlist
  require registered physical tables and reviewed pure function names
       │
       ▼
DuckDB executor (in-process, per-request)
  recheck SQL and supplied registered snapshots
  create views over registered local Parquet; exact allowed_paths
  external access / extension autoload off; configuration locked
  SET memory_limit; LIMIT default_row_cap+1 (SELECT)
  statement timeout is unenforced
       │
  ┌────┴──────┐
  OK        ERROR
  │           │
  │         CriticAgent (up to FLYQUERY_MAX_REFINE_RETRIES = 2)
  │           │  RefinedSql → loop back to AST check
  ▼
ExplainerAgent → NLAnswer + ChartHint (line|bar|table|pie|none)
       │
       ▼
Conversation memory: append turn (executed_sql, summary, table_qnames, snapshot_pins)
       │
       ▼
Auto-learn: if OK + no retries + no PII + no clarification → insert example
  (source=AGENT_LEARNED, quality=PROPOSED)
       │
       ▼
Recorder → flyquery_queries + audit_events + cost_events
  full result → results/{query_id}.parquet
  preview → flyquery_query_results
```

### Query-pipeline agents

Direct SQL skips the agents and uses the same admission policy with registered
metadata in both synchronous and SSE handlers. See the
[SQL read boundary](security-model.md#sql-read-boundary).

| Agent | Output type | Notes |
|-------|-------------|-------|
| `GroundingAgent` | `GroundedContext` | Iterative schema expansion up to `EXPAND_ITERS=2` |
| `GenerationAgent` | `GeneratedCandidates` | `FLYQUERY_GENERATION_CANDIDATES=3`; semantic-layer trusted over uploaded tables |
| `CriticAgent` | `RefinedSql` | Always invoked on error; optionally on success to rank N>1 |
| `ExplainerAgent` | `ResultExplanation` | NL summary + chart hint; cheap model by default |

All agents follow canon's `build_agent` recipe: structured `output_type`,
`auto_register=False`, fresh per call, observability middleware wrapping each
run, cost events tied to `query_id`.

---

## 8. Hexagonal adapters

flyquery is hexagonal at every external boundary. The domain core only depends
on port interfaces (Python `Protocol` classes); adapters are wired at
application startup via `@configuration` beans.

### ObjectStore port

```python
class ObjectStore(Protocol):
    async def put(self, key: str, body: ..., content_type: str,
                  kms_key_uri: str | None = None) -> ObjectMeta: ...
    async def get(self, key: str) -> AsyncIterator[bytes]: ...
    async def head(self, key: str) -> ObjectMeta: ...
    async def delete(self, key: str) -> None: ...
    async def list(self, prefix: str) -> AsyncIterator[ObjectMeta]: ...
    async def presign_get(self, key: str, ttl_s: int) -> str: ...
    async def copy(self, src_key: str, dst_key: str) -> None: ...
```

Adapters: `local_fs_object_store` (dev), `s3_object_store` (aiobotocore),
`gcs_object_store` (gcloud-aio-storage), `azure_blob_object_store`
(azure-storage-blob). Selected by `FLYQUERY_OBJECT_STORE`.

### FileReader port

```python
class FileReader(Protocol):
    formats: ClassVar[tuple[str, ...]]
    async def detect(self, head_bytes: bytes, filename: str) -> bool: ...
    async def enumerate_tables(self, handle, rules) -> list[ProposedTable]: ...
    async def materialise(self, handle, table, target_parquet, *,
                          workspace_locale, type_infer_sample_rows) -> MaterialiseResult: ...
```

Implementations: `csv_reader`, `excel_reader`, `json_reader`,
`parquet_reader`, `avro_reader`, `orc_reader`, `arrow_reader`.

### Query execution services (DuckDB)

`AstClassifier` classifies SQL with sqlglot. `ScopeGuard` checks registered
metadata and grants before `DuckDBExecutor.execute(sql, attached_tables,
derived_tables=None)` runs the statement. The executor reads the global
memory and row-cap settings when constructed. It does not accept a
per-request timeout or row-cap argument. See the
[SQL read boundary](security-model.md#sql-read-boundary).

### Other ports (shared with canon)

| Port | Adapters | Notes |
|------|----------|-------|
| `VectorStore` | `pgvector` | pgvector HNSW only — flyquery is pgvector-only by design |
| `PiiScanner` | `regex`, `presidio`, `disabled` | Shared verbatim from canon |
| `RateLimiter` | `memory`, `redis` | Per-token sliding 60 s window |
| `IdempotencyStore` | `memory`, `redis` | Lock-step with canon/radar |
| `SemanticCompiler` | `metricflow_compiler` | MetricFlow YAML → DuckDB SQL |

---

## 9. Lock-step modules

The following files are kept byte-equivalent with flycanon and flyradar.
`scripts/check_lockstep.py` diffs them against pinned SHAs in CI; PRs are
blocked on mismatch.

```
src/flyquery/web/agent_deps.py                    (~3.7 KB)
src/flyquery/web/conventions/middleware.py
src/flyquery/web/conventions/deps.py
src/flyquery/web/conventions/headers.py
src/flyquery/web/conventions/actor.py
src/flyquery/web/conventions/context.py
src/flyquery/web/conventions/validation.py
src/flyquery/web/conventions/errors.py
src/flyquery/web/conventions/idempotency.py
src/flyquery/web/conventions/redis_idempotency.py
src/flyquery/web/conventions/db.py
src/flyquery/web/conventions/handlers.py
src/flyquery/core/services/auth/agent_token_service.py
src/flyquery/core/services/auth/redis_rate_limiter.py
src/flyquery/web/controllers/agent_tokens_controller.py  (adapted for flyquery scope catalog)
src/flyquery/core/agents/builder.py
src/flyquery/core/observability/__init__.py
src/flyquery/web/openapi_override.py
```

21 files total. Any change to these in flyquery must also be reflected in the
canon and radar twins (or vice versa). Post-patch diff is checked via
`task lockstep-check`.
