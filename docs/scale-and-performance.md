# flyquery — Scale and Performance

## Table of Contents

1. [Throughput reference numbers](#1-throughput-reference-numbers)
2. [Bottlenecks](#2-bottlenecks)
3. [Tuning knobs](#3-tuning-knobs)
4. [Parallel vs serial operations](#4-parallel-vs-serial-operations)
5. [Capacity planning rules of thumb](#5-capacity-planning-rules-of-thumb)
6. [Observability for performance](#6-observability-for-performance)

---

## 1. Throughput reference numbers

All numbers are estimates from a reference deployment:
- 2 API pods × 4 vCPU × 8 GB RAM
- 2 worker pods × 4 vCPU × 8 GB RAM, `CONCURRENCY=4`
- Postgres db.t3.large (2 vCPU, 8 GB RAM)
- S3 object storage
- Anthropic claude-sonnet-4-6 (grounding, generation, critic)
- Anthropic claude-haiku-4-5 (explainer, describe)

**Caveats:** Numbers vary with file size, column count, LLM latency, and
network conditions. Treat these as order-of-magnitude starting points, not SLAs.

| Operation | Typical latency | Throughput (reference) |
|-----------|----------------|----------------------|
| Upload (10 MB CSV) | 2–5 s (upload + ingest start) | ~20 concurrent |
| Ingest — stages 1–3 (10 MB CSV) | 5–15 s | 8 concurrent (2 workers × 4) |
| Ingest — full 10-stage (10 MB CSV) | 30–90 s | 8 concurrent |
| Ingest — 100 MB Parquet | 60–180 s | 4 concurrent (memory pressure) |
| Query (simple SELECT + SUM) | 1.5–4 s (Grounding + Generation + DuckDB + Explainer) | 10–20 rps |
| Query (complex multi-join, 3 candidates) | 4–10 s | 5–10 rps |
| Query (SEMANTIC_LAYER path) | 1–2.5 s (MetricFlow deterministic) | 20+ rps |
| Embedding batch (50 columns) | 2–5 s | Limited by OpenAI rate limit |

---

## 2. Bottlenecks

### Postgres — schema knowledge base

For workspaces with large datasets (10,000+ columns), pgvector HNSW lookups
and BM25 `content_tsv` searches become the dominant retrieval latency.

Signals:
- `FLYQUERY_TOP_K_SCHEMA` queries taking > 500 ms
- Slow `explain analyze` on `SELECT … FROM flyquery_schema_objects WHERE embedding <-> $1 < 0.5`

Mitigations:
- Tune HNSW index `ef_construction` and `m` parameters for your dataset size.
- Add an index on `(workspace_id, is_active, kind)` for the filtered scan.
- Consider read replicas for retrieval queries (API) while worker writes
  go to primary.

### DuckDB memory

Each DuckDB connection uses up to `FLYQUERY_DUCKDB_MEMORY_LIMIT` (default 4 GB)
for large aggregations. With 10 concurrent queries:
- Worst case: 40 GB memory on the API pod.
- In practice: most queries use < 500 MB; 4 GB is a ceiling.

Signals: `Out of memory` errors in query responses.

Mitigations:
- Reduce `FLYQUERY_DUCKDB_MEMORY_LIMIT` per connection.
- Scale API pods horizontally (each pod runs its own DuckDB instances).
- Add WHERE clause pushdown in the query prompt to reduce scan sizes.

### LLM latency

Grounding + Generation + Critic + Explainer calls run sequentially per query.
Each call adds 500 ms–3 s depending on model and prompt size.

LLM call sequence latency:
- Grounding: 0.5–2 s
- Generation (N=3 candidates): 1–3 s
- Critic (if needed): 0.5–2 s
- Explainer: 0.3–1 s
- Total: 2.3–8 s (serial)

Signals: p99 query latency > 10 s.

Mitigations:
- Use `FLYQUERY_EXPLAINER_MODEL=anthropic:claude-haiku-4-5` (already default).
- Reduce `FLYQUERY_GENERATION_CANDIDATES` from 3 to 1 for latency-sensitive
  workloads (less quality).
- Enable `FLYQUERY_QUERY_EXPANSION_ENABLED=false` (already default).
- Use the `SEMANTIC_LAYER` path for frequently-asked metric questions (bypasses
  GenerationAgent).

### Object-storage I/O (large Parquet files)

Ingestion reads through ObjectStore adapters. The qualified DuckDB query
workflow reads registered local Parquet snapshots accessible to the API
process. Measure ingestion storage I/O and local query scans separately;
remote httpfs query timings have not been qualified.

Use efficient Parquet row groups and column statistics for predicate
pushdown. `FLYQUERY_DUCKDB_HTTPFS_METADATA_CACHE_MB` does not configure the
current executor, which disables extension autoload/install and external
access. See the [SQL read boundary](security-model.md#sql-read-boundary).

---

## 3. Tuning knobs

### Query pipeline

| Variable | Default | Latency impact | Quality impact |
|----------|---------|---------------|----------------|
| `FLYQUERY_GENERATION_CANDIDATES` | `3` | +50-100% per extra candidate | Higher quality |
| `FLYQUERY_MAX_REFINE_RETRIES` | `2` | +1-3 s per retry | Better on complex SQL |
| `FLYQUERY_EXPAND_ITERS` | `2` | +1-2 s per iteration | Better grounding |
| `FLYQUERY_TOP_K_SCHEMA` | `12` | +10-20 ms per extra row | More context for Grounding |
| `FLYQUERY_RERANKER_TOP_N` | `30` | +50-200 ms | Better schema linking |
| `FLYQUERY_DUCKDB_MEMORY_LIMIT` | `4GB` | N/A | Per-connection DuckDB memory budget |
| `FLYQUERY_DEFAULT_STATEMENT_TIMEOUT_MS` | `30000` | None in current executor | Unenforced; does not prevent runaway queries |

### Ingestion

| Variable | Default | Throughput impact |
|----------|---------|------------------|
| `FLYQUERY_INGEST_WORKER_CONCURRENCY` | `4` | Linear with job parallelism |
| `FLYQUERY_DESCRIBE_BATCH` | `20` | Fewer LLM calls per run = higher throughput |
| `FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN` | `200` | Budget cap; raise for faster full-describe |
| `FLYQUERY_SAMPLE_N` | `8` | Fewer samples = faster stage 4 |
| `FLYQUERY_PROFILE_ROW_THRESHOLD` | `10000000` | Raise to skip profiling on medium tables |

### Object storage

| Variable | Default | Effect |
|----------|---------|--------|
| `FLYQUERY_DUCKDB_HTTPFS_METADATA_CACHE_MB` | `512` | Configuration field; unused by the current query executor |
| `FLYQUERY_OBJECT_STORE_PRESIGN_TTL_S` | `86400` | Reduce to limit exposure window |
| `FLYQUERY_RESULT_TTL_HOURS` | `24` | Reduce to save object-storage costs |

---

## 4. Parallel vs serial operations

### Query pipeline — serial

All four query agents run serially (Grounding → Generation → Critic →
Explainer). This is intentional: each stage consumes the output of the
previous one. No parallelisation opportunity within a single query.

Multiple queries (different requests) run concurrently via async/await.
DuckDB calls run in a thread pool to avoid blocking the event loop.

### Ingestion pipeline — mostly serial with one parallel step

Stages 1–10 are serial within a single job (each stage depends on the
previous). However:

- Multiple jobs run concurrently across worker goroutines.
- Stage 6 (relation discovery) runs heuristic and `RelationProposerAgent`
  concurrently within the stage (two separate async tasks).
- Stage 9 (embed + index) embeds all columns for a table concurrently
  (batch embedding API call).

### Embedding generation — batched

Stage 9 sends all columns for a snapshot in a single batch API call
(up to `FLYQUERY_DESCRIBE_BATCH=20` items per call). For large tables (100+
columns), multiple batch calls run sequentially to stay within token limits.

---

## 5. Capacity planning rules of thumb

### Storage

- Parquet snapshot size ≈ original CSV / 3–6 (compression ratio).
- Query results TTL = 24 h; average result size = 50–500 KB (preview JSON +
  Parquet). For 100 queries/day: 5–50 MB/day.
- `flyquery_schema_objects` row size ≈ 2–5 KB per column (including embedding
  vector at 1536 dimensions × 4 bytes = 6 KB). For 10,000 columns: 80–110 MB
  in Postgres.

### Memory

| Component | Memory estimate |
|-----------|----------------|
| API pod | 2–4 GB base + `N_concurrent_queries × DUCKDB_MEMORY_LIMIT` |
| Worker pod | 2–4 GB base + DuckDB for ingestion stages (< 1 GB typical) |
| pgvector HNSW index | ~50 MB per 10,000 vectors at 1536 dims |

### CPU

DuckDB aggregations are CPU-bound. One DuckDB query can spike a CPU core.
With 10 concurrent queries, expect 10× CPU cores to avoid queuing.

### Network

ObjectStore ingestion and result transfers contribute network traffic. The
qualified query executor scans registered local Parquet; it does not load
httpfs. Remote column-transfer estimates require separate provider and query
qualification. See the [SQL read boundary](security-model.md#sql-read-boundary).

### Horizontal worker scaling formula

Total inflight ingest jobs across the fleet:

```
total_inflight = N_processes × FLYQUERY_INGEST_WORKER_CONCURRENCY
```

Each `IngestWorker` process bounds simultaneous handler tasks with an
`asyncio.Semaphore(_CONCURRENCY)` (see
[concurrency.md § 4](concurrency.md#4-eda-worker-concurrency)). Adding
processes is linear in capacity; adding `_CONCURRENCY` per process is
cheaper but capped by the per-process Postgres pool + per-key LLM RPM
budget.

**Tuning rules of thumb:**

| Constraint | Symptom | Knob |
|---|---|---|
| LLM provider rate limit (RPM) | Burst errors from Anthropic / OpenAI | Lower `_CONCURRENCY` per process, add more processes (smaller bursts per key). |
| Postgres connection pool saturation | `TimeoutError` on `await session.begin()` | Raise pool size to ≥ `N × _CONCURRENCY + API_pool` connections OR run PgBouncer in transaction mode. |
| DuckDB OOM in ingest stages | `Out of memory` errors mid-pipeline | Raise pod RAM OR lower `_CONCURRENCY` per process. |
| Pending queue grows (slow consumer) | `ingest_job_count_pending` from `GET /api/v1/stats` climbs | Add `N_processes`. |
| Pending queue grows (ingest pipeline LLM-bound) | Per-job duration > 60s, queue grows | Raise `_CONCURRENCY` per process (more parallel work) if Postgres has slack. |

The RetentionWorker doesn't scale — one process per cluster is enough.
Two processes are safe (every operation is idempotent + atomic) but
redundant. See [workers.md](workers.md) for the full deployment
topology.

---

## 6. Observability for performance

flyquery exposes metrics via Prometheus at `/actuator/metrics`:

| Metric | What it measures |
|--------|-----------------|
| `flyquery_query_latency_seconds` | Query pipeline latency (p50, p95, p99) |
| `flyquery_ingest_stage_latency_seconds` | Per-stage ingestion latency |
| `flyquery_duckdb_memory_bytes` | DuckDB memory usage per active connection |
| `flyquery_agent_tokens_used` | LLM tokens consumed (by agent name) |
| `flyquery_cost_cents_total` | Cumulative LLM cost |
| `flyquery_ingest_jobs_active` | Currently running ingest jobs |
| `flyquery_ingest_jobs_queued` | Jobs in PENDING state |
| `flyquery_schema_objects_total` | Total schema objects in KB |
| `flyquery_null_embeddings_total` | Schema objects with NULL embedding (alert on > 0) |

Key alerts:
- `flyquery_ingest_jobs_queued > 20` for > 5 minutes → scale up workers.
- `flyquery_null_embeddings_total > 0` for > 10 minutes → embedding stage failed.
- `flyquery_query_latency_seconds{quantile="0.99"} > 15` → LLM latency degradation.
- `flyquery_cost_cents_total` rate spike → runaway describe budget or unusual query volume.

See [operations-runbook.md](operations-runbook.md) for the full observability
setup and daily health check procedures.
