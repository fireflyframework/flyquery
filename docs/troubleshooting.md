# flyquery — Troubleshooting

## Table of Contents

1. [How to use this guide](#1-how-to-use-this-guide)
2. [Upload failures](#2-upload-failures)
3. [Ingest job stuck or failed](#3-ingest-job-stuck-or-failed)
4. [NULL embeddings on schema objects](#4-null-embeddings-on-schema-objects)
5. [RLS returns zero rows](#5-rls-returns-zero-rows)
6. [Agent timeouts](#6-agent-timeouts)
7. [OpenAPI drift gate failure in CI](#7-openapi-drift-gate-failure-in-ci)
8. [PII false positives blocking queries](#8-pii-false-positives-blocking-queries)
9. [DuckDB OOM or timeout](#9-duckdb-oom-or-timeout)
10. [Wrong SQL generated](#10-wrong-sql-generated)
11. [Conversation drill-down returns stale results](#11-conversation-drill-down-returns-stale-results)
12. [Lock-step drift CI failure](#12-lock-step-drift-ci-failure)
13. [SDK installation failures](#13-sdk-installation-failures)

---

## 1. How to use this guide

Each symptom entry follows the format:
- **Symptom** — what you observe.
- **Root cause** — most likely explanation.
- **Fix** — exact steps to resolve.

Start with the HTTP error body (`detail` and `error_code` fields in the
RFC 7807 response) and the service logs before reading this guide. The
`X-Correlation-Id` header on all responses ties logs to requests.

---

## 2. Upload failures

### Symptom: `413 Content Too Large` on upload

**Root cause:** File exceeds `FLYQUERY_MAX_FILE_MB` (default 2048 MiB = 2 GiB)
or total workspace storage exceeds `FLYQUERY_MAX_WORKSPACE_GB` (default 200 GiB).

**Fix:**
```bash
# Check file size before upload
ls -lh myfile.xlsx

# Check workspace storage usage
GET /api/v1/stats

# If workspace is over limit, archive or delete unused datasets:
DELETE /api/v1/datasets/{id}

# Or increase the cap (requires restart):
export FLYQUERY_MAX_FILE_MB=4096
```

---

### Symptom: `422` with `error_code=FORMAT_MISMATCH`

**Root cause:** The file's magic bytes don't match its extension. A common
case is an XLSX file renamed to `.csv` by a third-party export tool.

**Fix:** Rename the file with the correct extension. If the file is genuinely
ambiguous, use the `file_format` override in the upload body:
```bash
curl -X POST .../datasets/{id}/files \
  -F "file=@mystery.bin" \
  -F "file_format=parquet"
```

---

### Symptom: `422` with `error_code=ZIP_MULTI_ENTRY`

**Root cause:** A `.zip` archive with multiple files was uploaded. flyquery
only accepts single-file ZIP archives.

**Fix:** Extract the relevant file and upload it directly. For multi-file
archives, upload each file separately.

---

### Symptom: Upload returns `202` but job fails immediately at stage 1

**Root cause:** Content hash mismatch — the file was corrupted in transit.

**Fix:** Retry the upload. If it fails consistently, check for proxy
middleware truncating large uploads (e.g., nginx body size limits).

---

## 3. Ingest job stuck or failed

### Symptom: Job in `RUNNING` for >15 minutes

**Root cause:** Worker process crashed or network partition caused a dead
connection; heartbeat-timeout recovery has not fired yet.

**Fix:**
```bash
# Restart the worker
docker compose restart flyquery-worker

# Manual reset (wait for heartbeat timeout = FLYQUERY_INGEST_HANDLER_TIMEOUT_S):
# Heartbeat recovery is automatic; the background task checks every 60s
# To force immediately:
psql flyquery -c "
  UPDATE flyquery_ingest_jobs
  SET status='PENDING', attempts=attempts+1
  WHERE id='<job_id>' AND status='RUNNING'
    AND heartbeat_at < NOW() - INTERVAL '15 minutes';
"
```

---

### Symptom: Job in `FAILED` with `error_code=DESCRIBE_BUDGET_EXHAUSTED`

**Root cause:** Normal; the describe budget ran out before all columns were
described. The pipeline completed stages 1–7 (partial), 8, 9, 10 and a
follow-up `DESCRIBE_PASS` job was enqueued.

**Fix:** Wait for the `DESCRIBE_PASS` job to run. To expedite:
```bash
POST /api/v1/ingest-jobs {"job_kind": "DESCRIBE_PASS", "dataset_id": "ds_01"}
```
Or increase `FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN`.

---

### Symptom: Stage 2 fails with `error_code=PARSE_ERROR`

**Root cause:** File is malformed. Common: encrypted XLSX, password-protected
file, binary content with a text extension.

**Fix:** Check the `result_json.error_detail` field for the parser's error
message. Download and inspect the original file from the presigned URL at
`GET /files/{id}`.

---

## 4. NULL embeddings on schema objects

### Symptom: `SELECT COUNT(*) FROM flyquery_schema_objects WHERE embedding IS NULL AND is_active=true` > 0

**Root cause A:** Stage 9 failed due to embedding API error (rate limit,
invalid API key, model not found).

**Fix:**
```bash
# Check embedding config
echo $FLYQUERY_EMBEDDING_MODEL
echo $OPENAI_API_KEY   # or equivalent

# Check ingest_events for stage 9 error
GET /api/v1/ingest-jobs/{id}/events?stage=embed

# Re-ingest
POST /api/v1/ingest-jobs {"job_kind": "REPARSE", "file_id": "<id>"}
```

**Root cause B:** `embedding IS NULL` on rows that were imported via a
migration from a system without pgvector. The `REPARSE` job above fixes this.

**Root cause C:** pgvector extension is not installed or vector dimension
mismatch (`FLYQUERY_EMBEDDING_DIMENSIONS` changed after initial ingest).

**Fix:**
```bash
# Check extension
psql flyquery -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"

# Check dimension mismatch
psql flyquery -c "SELECT embedding_model, COUNT(*) FROM flyquery_schema_objects GROUP BY 1;"
# If two models with different dimensions coexist, full REPARSE is needed
```

---

## 5. RLS returns zero rows

### Symptom: `GET /datasets` returns `[]` when datasets exist

**Root cause A:** Missing `X-Tenant-Id` or `X-Workspace-Id` header. The
`TenantContextMiddleware` sets the GUC to an empty string when headers are
absent, making RLS filter everything.

**Fix:** Add the headers:
```bash
curl -H "X-Tenant-Id: acme" -H "X-Workspace-Id: analytics" \
  http://localhost:8520/api/v1/datasets
```

**Root cause B:** Wrong `workspace_id` — the workspace was created with
a different `id` than the one being requested.

**Fix:**
```bash
# List workspaces for the tenant (tenant-only auth for admin operations)
curl -H "X-Tenant-Id: acme" http://localhost:8520/api/v1/workspaces
```

**Root cause C:** Test code uses the default `test` Postgres user (SUPERUSER /
BYPASSRLS). RLS tests must use the `flyquery_app` role.

**Fix:** See [security-model.md § 3](security-model.md#3-postgres-role-split-and-rls)
for the test role setup recipe.

---

## 6. Agent timeouts

### Symptom: Query fails with `execution_status=FAILED`, error contains "timeout"

`FLYQUERY_DEFAULT_STATEMENT_TIMEOUT_MS` is currently unenforced by the query
executor, and `QueryRequest` has no per-query timeout override. Increasing
that setting cannot fix a DuckDB execution stall. Identify the failing stage
from the error and logs; see the [SQL read boundary](security-model.md#sql-read-boundary).

**Root cause A:** LLM API latency (Anthropic / OpenAI rate limit or slow
response).

**Fix:** Check LLM API status pages. Temporarily switch to fallback model:
```bash
export FLYQUERY_FALLBACK_MODEL=openai:gpt-4o
```

**Root cause B:** `FLYQUERY_AGENT_MAX_OUTPUT_TOKENS` too small for the
number of tables/columns in the Grounded context.

**Fix:** Increase to 16384 for large schemas.

---

## 7. OpenAPI drift gate failure in CI

### Symptom: CI fails with "openapi.json has drifted from the live spec"

**Root cause:** A DTO or endpoint changed but `openapi.json` was not
regenerated and committed.

**Fix:**
```bash
task serve &   # start the service in background
task openapi-snapshot   # fetches /openapi.json and writes to ./openapi.json
git add openapi.json
git commit -m "chore: regenerate openapi.json"
```

---

## 8. PII false positives blocking queries

### Symptom: Column is marked `is_active=false` after ingest; queries on that column return nothing

**Root cause:** Stage 8 PII scanner flagged the column with `policy=reject`,
setting `is_active=false`.

**Fix:**
```bash
# Review the column
GET /api/v1/schema-objects/{id}
# Look at pii_tag, pii_source, sample_values_json (if still present)

# If the classification is wrong (false positive):
PUT /api/v1/schema-objects/{id}
  {"pii_tag": "NONE", "is_active": true}

# Or change policy to 'warn' and re-ingest
export FLYQUERY_PII_POLICY_SAMPLES=warn
POST /api/v1/ingest-jobs {"job_kind": "REPARSE", "file_id": "<id>"}
```

---

## 9. DuckDB OOM or timeout

### Symptom: Query fails with DuckDB `Out of memory` error

**Root cause:** `FLYQUERY_DUCKDB_MEMORY_LIMIT` (default 4 GB) is too low for
the aggregation, or the query touches a very large Parquet file.

**Fix:**
```bash
# Increase per-connection memory limit
export FLYQUERY_DUCKDB_MEMORY_LIMIT=8GB

# Check query plan first:
POST /api/v1/query:explain {"question": "...", "dataset_id": "..."}
# Look for large HASH_AGG or CROSS JOIN in the plan
```

For repeated OOM on the same query, simplify the question or add a WHERE
clause to scope the data.

For a long-running DuckDB statement, reduce the scan or join work and inspect
the query plan. The statement-timeout setting currently does not interrupt
execution; the result row cap limits returned rows, not computation time.
File-source or unregistered-table rejections are expected policy failures,
not reasons to enable httpfs or external access. See the
[SQL read boundary](security-model.md#sql-read-boundary).

---

## 10. Wrong SQL generated

### Symptom: Query returns wrong results; `executed_sql` in the response uses wrong column or table name

**Root cause A:** Schema objects have incorrect or missing descriptions —
the GroundingAgent picks the wrong column because there's no semantic signal.

**Fix:**
```bash
# Add descriptions to schema objects
PUT /api/v1/schema-objects/{id}
  {"description": "The date the order was placed, in YYYY-MM-DD format"}
```

**Root cause B:** No approved examples for similar questions. The
GenerationAgent has no few-shot anchor.

**Fix:**
```bash
# Add a curated example
POST /api/v1/examples
  {"question": "Total revenue by month",
   "generated_sql": "SELECT strftime('%Y-%m', order_date) AS month, SUM(amount) FROM ...",
   "dataset_id": "ds_01"}
```

**Root cause C:** Relation between tables is not approved. JOIN is omitted
or uses wrong column.

**Fix:**
```bash
# List and approve heuristic relations
GET /api/v1/datasets/{id}/relations?kind=HEURISTIC
POST /api/v1/datasets/{id}/relations/{rel_id}:approve

# Or add a manual relation
POST /api/v1/datasets/{id}/relations
  {"from_table_id": "...", "from_column_name": "customer_id",
   "to_table_id": "...", "to_column_name": "id"}
```

---

## 11. Conversation drill-down returns stale results

### Symptom: A drill-down question re-runs the original question instead of adding a filter

**Root cause:** The `starting_point_sql` from the prior turn is for a
snapshot that has been re-uploaded (new `current_snapshot_id`). flyquery
detects the stale pin and falls back to a fresh Grounding pass.

**Fix:** Start a new conversation after re-uploading data. The old
conversation's snapshot pins reference the previous upload's data.

---

## 12. Lock-step drift CI failure

### Symptom: CI fails with `scripts/check_lockstep.py: drift detected in src/flyquery/web/conventions/middleware.py`

**Root cause:** A local source file differs from its reviewed historical
baseline or service-specific pin, or the variant manifest is invalid.

**Fix:**
```bash
python scripts/check_lockstep.py
```

Review the reported source diff before restoring a file or changing a pin.
Current canon/radar files may have different APIs; copying them blindly can
break flyquery. Only the builder and observability paths permit reviewed
service variants. Authentication changes still fail their historical pins.
The [architecture guide](architecture.md#9-lock-step-modules) explains the
manifest and canonical provenance; rerun behavior tests after a correction.

---

## 13. SDK installation failures

### Python SDK

**Symptom:** `pip install flyquery-sdk` fails with dependency conflict.

**Fix:**
```bash
# Ensure Python 3.11+
python --version

# Install with extras if needed
pip install 'flyquery-sdk[async]'

# Or install from local sdks/python
pip install -e ./sdks/python
```

### Java SDK

**Symptom:** Maven resolution fails for `io.firefly:flyquery-sdk`.

**Fix:** Ensure the Firefly internal Maven registry is configured in your
`settings.xml`. See `sdks/java/README.md` for the repo URL and credentials.
