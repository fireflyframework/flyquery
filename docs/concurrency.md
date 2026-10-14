# flyquery — Concurrency

## Table of Contents

1. [Overview](#1-overview)
2. [AsyncSession scoping](#2-asyncsession-scoping)
3. [RLS GUC binding via after_begin hook](#3-rls-guc-binding-via-after_begin-hook)
4. [EDA worker concurrency](#4-eda-worker-concurrency)
5. [DuckDB per-request isolation](#5-duckdb-per-request-isolation)
6. [ObjectStore async patterns](#6-objectstore-async-patterns)
7. [Transactional boundaries](#7-transactional-boundaries)
8. [Race conditions and mitigations](#8-race-conditions-and-mitigations)

---

## 1. Overview

flyquery is an async-first service built on FastAPI + SQLAlchemy async +
asyncpg. Understanding the concurrency model matters when:

- Running multiple API replicas.
- Running multiple worker processes.
- Writing tests that validate RLS isolation.
- Extending the service with new stages or endpoints.

The key principles:

1. **One AsyncSession per request.** Sessions are never shared across requests.
2. **RLS GUCs are transaction-scoped.** They reset automatically when the
   connection returns to the pool.
3. **IngestWorker slots claim jobs with `SELECT … FOR UPDATE SKIP LOCKED`.**
   No two slots can process the same job.
4. **DuckDB is in-process per-request.** No shared connection; no shared
   ATTACH state.
5. **ObjectStore operations are async.** Concurrent puts/gets on the same
   key are safe at the storage level; flyquery uses immutable keys (snapshot
   versioning) to avoid write conflicts.

---

## 2. AsyncSession scoping

flyquery uses SQLAlchemy's `AsyncSession` with `async_scoped_session` scoped
to the current asyncio Task (via the lock-step
`web/conventions/db.py`).

```python
# web/conventions/db.py (simplified)
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session, create_async_engine
import asyncio

engine = create_async_engine(settings.database_url, ...)
_session_factory = async_scoped_session(
    sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    scopefunc=asyncio.current_task,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session
```

The `AsyncSession` is:
- Injected into controllers and services via FastAPI `Depends(get_db)`.
- Scoped to the HTTP request's asyncio task.
- Closed (and the connection returned to the pool) when the request completes.

**Do not** store or pass `AsyncSession` across task boundaries. Background
tasks that spawn from a request handler should acquire their own session.

---

## 3. RLS GUC binding via after_begin hook

The `TenantContextMiddleware` extracts `X-Tenant-Id` and `X-Workspace-Id`
from each request. The actual Postgres GUCs (`app.tenant_id`,
`app.workspace_id`) are set via an SQLAlchemy `after_begin` event listener
on the session:

```python
# web/conventions/db.py (after_begin hook, simplified)
from sqlalchemy import event

@event.listens_for(AsyncSession, "after_begin")
def set_tenant_gucs(session, transaction, connection):
    tenant_id = get_current_tenant()    # from context var
    workspace_id = get_current_workspace()
    session.execute(
        text("SET LOCAL app.tenant_id = :t; SET LOCAL app.workspace_id = :w"),
        {"t": tenant_id, "w": workspace_id},
    )
```

`SET LOCAL` scopes the GUC to the current transaction. When the transaction
commits or rolls back, the GUC resets automatically before the connection
returns to the pool. This prevents GUC leakage across requests.

**Critical:** `SET LOCAL` (not `SET SESSION`). `SET SESSION` would persist
the GUC until the connection is closed, which in a connection pool means
until the next request on that connection — a cross-tenant data leak.

---

## 4. EDA worker concurrency

> See [workers.md](workers.md) for the full operator-facing fleet doc.
> This section covers the concurrency primitives — semaphore + atomic
> claim + drain — that make it correct.

### Job claiming

`IngestWorker` claims jobs via an atomic `UPDATE … WHERE status='PENDING'`
on `flyquery_ingest_jobs.status` inside a transaction
(`ingest_job_repository._mark_running`). The `UPDATE` returns the
claimed row's id; if zero rows came back (another worker or the
RetentionWorker beat us to it), the handler short-circuits. This
provides work-queue semantics across both processes (concurrent ingest
workers) AND cross-process recovery (the retention worker's stuck-job
reaper can republish a job onto the bus, and the next worker to pick
it up uses the same atomic claim to dedupe).

### Concurrency primitives

`IngestWorker` uses a four-piece pattern (semaphore + wait_for + Event
+ inflight set) — see
[`workers.py`](../src/flyquery/core/services/ingestion/workers.py):

| Primitive | Role |
|---|---|
| `asyncio.Semaphore(_CONCURRENCY)` | Bounds simultaneous handler tasks. |
| `asyncio.wait_for(handler, timeout=ingest_handler_timeout_s)` | Caps any one job's wall-clock. |
| `asyncio.Event` (`_shutdown`) | Cooperative SIGTERM signal. |
| `self._inflight: set[Task]` | Tracked so the drain step can wait on (or cancel) them. |

This pattern is verified by
[`tests/unit/test_ingest_worker_concurrency.py`](../tests/unit/test_ingest_worker_concurrency.py)
(4 tests: semaphore cap enforcement under burst, timed-out handler
isolation, drain wait + drain cancel).

### Concurrency limits

Each worker process runs `FLYQUERY_INGEST_WORKER_CONCURRENCY` asyncio
coroutines (default 4). Each coroutine is an independent asyncio task with
its own `AsyncSession` and Postgres connection.

With N worker pods each running C coroutines, the total concurrent job
capacity is `N × C`. The Postgres connection pool size should be at least
`N × C + headroom_for_api` connections. See
[scale-and-performance.md § 5](scale-and-performance.md#5-capacity-planning-rules-of-thumb)
for the horizontal-scale formula.

### Worker shutdown sequence

```
SIGTERM received
    │
    ▼
Stop accepting new job claims (set _shutdown Event)
    │
    ▼
_drain_inflight():
   1. asyncio.wait_for(gather(*self._inflight), grace)
   2. on TimeoutError: cancel() each task, then a second 5s
      asyncio.wait_for to give cleanup a chance.
    │
    ▼
Exit
```

Jobs that did not complete are left in `RUNNING`. The
**RetentionWorker** resets them to `PENDING` and republishes them onto
the bus after `processing_lease_s` (default 1800s); see
[`retention_worker.py:162`](../src/flyquery/core/services/retention/retention_worker.py).
This is the recovery primitive for crashed or terminated workers.

### Drain timeout window

`_drain_inflight` uses `asyncio.wait_for(...)` for the post-cancel
cleanup window and logs a warning if the hard timeout elapses
([`workers.py:163`](../src/flyquery/core/services/ingestion/workers.py)).
The regression test that covers the drain-with-cancel path is in
[`tests/unit/test_ingest_worker_concurrency.py`](../tests/unit/test_ingest_worker_concurrency.py).

---

## 5. DuckDB per-request isolation

Each admitted query execution (`POST /query`, `POST /sql:execute`) creates a
fresh in-memory DuckDB connection inside the synchronous worker body.
The asynchronous entry point hands off the request as follows:

```python
import asyncio

async def execute(self, sql, attached_tables, derived_tables=None):
    return await asyncio.to_thread(
        self._sync, sql, dict(attached_tables), dict(derived_tables or {})
    )
```

Properties of this design:

- **No shared state.** There is no persistent DuckDB database on disk. Each
  connection starts empty.
- **Per-request views.** Registered local Parquet paths become views in each
  connection. Concurrent queries do not share view or mutable-table state.
- **Confined file access.** Exact `allowed_paths`, disabled external access
  and extension autoload/install, and locked configuration restrict the
  connection. DERIVED DML writes a new scratch Parquet output and leaves the
  original snapshot unchanged.
- **Memory budget.** `SET memory_limit` configures each connection's budget.
  Size API pods for concurrent query memory and process overhead; this
  setting is not an operating-system process limit. The current executor
  fixes `threads=2` per connection.

The connection is not read-only. SQL admission and snapshot checks precede
execution; see the [SQL read boundary](security-model.md#sql-read-boundary)
for the full policy. Each call has its own positive cooperative deadline
and watchdog, which interrupts only that call's native connection. Cancellation
waits for worker cleanup. The SELECT row cap limits output size, not compute time;
use deployment limits for hard CPU/memory isolation.

**Concurrency concern:** DuckDB in-process with asyncio requires care. DuckDB
operations are synchronous and CPU-bound. They block the asyncio event loop
thread. flyquery moves the synchronous execution body to a worker thread
with `asyncio.to_thread`, as shown above.

This keeps the asyncio event loop responsive for incoming requests while
DuckDB computes.

---

## 6. ObjectStore async patterns

The `ObjectStore` port is fully async. Adapters wrap synchronous provider
SDKs (aiobotocore for S3; gcloud-aio-storage for GCS;
azure-storage-blob async for Azure) in native async clients.

### Concurrent puts

Multiple concurrent uploads (`PUT` operations) to distinct keys are safe.
flyquery uses immutable, versioned keys:
- `tables/{table_id}/v{n}.parquet` — the `v{n}` suffix is derived from the
  snapshot counter; two concurrent ingests for different tables write to
  different keys.
- `files/{file_id}.{ext}` — unique per upload.
- `results/{query_id}.parquet` — unique per query.

There is no overwrite scenario in normal operation. A re-upload increments
`n` and writes to a new key; it does not overwrite the previous snapshot.

### Streaming large files

Stage 2 (parse) streams the uploaded file from object storage to the
FileReader without loading the entire file into memory:

```python
async for chunk in object_store.get(file_key):
    await reader.feed(chunk)
```

The `put` operation in stage 2 also streams:
```python
await object_store.put(parquet_key, parquet_stream_generator, content_type="application/octet-stream")
```

This means a 2 GiB CSV file never occupies 2 GiB of RAM simultaneously
during ingestion.

---

## 7. Transactional boundaries

Understanding where transactions begin and end matters for correctness.

### Request-scoped transaction (API handlers)

Most API handlers use a single transaction for the entire request:

```python
async def create_dataset(body, db: AsyncSession):
    dataset = Dataset(...)
    db.add(dataset)
    audit_event = AuditEvent(...)
    db.add(audit_event)
    await db.commit()  # dataset + audit_event committed together
    return dataset
```

### Multi-stage transactions (IngestWorker)

Each stage has its own transaction. The stage result is committed before the
next stage begins. This means:
- A crash between stage 5 and 6 leaves stage 5 data in the database.
- Stage 6 checks for existing relations before re-inserting.
- All stages are idempotent (except stage 2, which re-reads the original blob).

### Stage 10 atomic snapshot close

Stage 10 is a single transaction that:
1. Updates `flyquery_schema_snapshots.status = READY`.
2. Updates `flyquery_tables.current_snapshot_id = new_snapshot_id`.
3. Inserts the `SchemaUpdated` outbox event.

These three writes commit atomically. Either all three commit or none does.
The query pipeline only reads `current_snapshot_id`; it never sees a table
pointing at a `PARTIAL` snapshot because the pointer only flips in this
atomic transaction.

### RLS and transactions

RLS GUCs are `SET LOCAL` — they apply to the current transaction only.
Each transaction in `IngestWorker` re-sets the GUC at `after_begin`.
This is correct for background workers: the worker sets `tenant_id` and
`workspace_id` from the job record, not from a request header.

---

## 8. Race conditions and mitigations

### Concurrent ingest jobs for the same table

If two `PARSE_AND_INGEST` jobs for the same `table_id` run concurrently
(e.g., two rapid re-uploads):

- Both proceed through stages 1–2 independently.
- Stage 3 (reconcile + snapshot) inserts new snapshot rows. Snapshots are
  uniquely keyed by `(table_id, taken_at, snapshot_hash)`.
- Stage 10 updates `current_snapshot_id`. The last writer wins. The earlier
  snapshot remains in `PARTIAL` status and is cleaned up by a background
  PARTIAL-snapshot sweep after 24 hours.

Mitigation: In practice, the upload endpoint serialises at the HTTP level
(the re-upload path `PUT /tables/{id}:upload` checks for an active RUNNING
job and returns `409 Conflict`).

### Simultaneous describe and annotation

If an operator annotates a column description via `PUT /schema-objects/{id}`
while a `DESCRIBE_PASS` job is running, the operator's annotation
(`description_source=HUMAN`) takes precedence. The `DescribeAgent` only
writes to columns where `description IS NULL`; it skips columns that already
have a description.

### Embedding updates and retrieval

New embeddings written in stage 9 become visible to the retrieval pipeline
only after the pgvector HNSW index is refreshed. The index refresh is a
background operation inside Postgres; there may be a brief window (typically
< 100 ms) where new embeddings are in the table but not yet in the HNSW
index.

This is acceptable: the retrieval pipeline also has a BM25 fallback (via
`content_tsv`), which is available immediately after the row is committed.
