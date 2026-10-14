# flyquery — Deployment Topology

## Table of Contents

1. [Overview](#1-overview)
2. [Single-node (docker-compose)](#2-single-node-docker-compose)
3. [Multi-node (separate services)](#3-multi-node-separate-services)
4. [HA considerations](#4-ha-considerations)
5. [Service port reference](#5-service-port-reference)

---

## 1. Overview

flyquery separates into three runtime processes (one was added in 26.5.10):

| Process | CLI | Role |
|---------|-----|------|
| `flyquery-api` | `flyquery serve` | HTTP server — handles uploads, queries, schema annotation, stats |
| `flyquery-ingest-worker` | `flyquery worker ingest` | Ingest worker — consumes `flyquery.ingest` EDA topic, runs 10-stage pipeline |
| `flyquery-retention-worker` | `flyquery worker retention` | Periodic janitor — stuck-job reaper, TTL deletes, PURGED dataset hard-delete |

All three connect to the same Postgres and object storage. The API does
not run ingestion stages; it only publishes the EDA event that triggers
the ingest worker. The retention worker doesn't run pipeline stages
either — it polls on a fixed interval and only writes recovery /
cleanup SQL.

For dev / docker-compose convenience, `flyquery worker all` runs both
workers in a single asyncio event loop — **dev only**, production must
split them.

See [deployment.md](deployment.md) for environment variables and
migration steps. See [async-ingest.md](async-ingest.md) for ingest
worker internals. See [workers.md](workers.md) for the full worker
fleet picture (scaling, recovery, observability hooks).

---

## 2. Single-node (docker-compose / dev)

All components on one host. Appropriate for development, demos, and
small-scale on-prem POCs. The dev form uses `flyquery worker all` so
both workers ride one event loop — this is **not** the production
shape (see § 3 for the production split).

```
┌─────────────────────────────────────────────────────────────────────┐
│                          docker-compose host                        │
│                                                                     │
│  ┌─────────────────┐   ┌─────────────────────┐   ┌────────────────┐ │
│  │  flyquery-api   │   │ flyquery-worker     │   │  postgres      │ │
│  │  :8520          │   │ (CMD: worker all)   │   │  :5432         │ │
│  │                 │   │                     │   │  pgvector ext. │ │
│  │  uploads /      │   │  IngestWorker +     │   │  flyquery_*    │ │
│  │  queries /      │   │  RetentionWorker    │   │  tables        │ │
│  │  annotation /   │   │  in one asyncio     │   └────────────────┘ │
│  │  conversations  │   │  event loop         │                      │
│  └────────┬────────┘   │  (DEV ONLY)         │   ┌────────────────┐ │
│           │            └──────────┬──────────┘   │ local-fs blobs │ │
│           └────── EDA  ───────────┘              │ /var/lib/      │ │
│                  (Postgres LISTEN/NOTIFY)        │   flyquery     │ │
│                                                  └────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

External:
  Browser / API client → http://host:8520/api/v1/...
  LLM API            → https://api.anthropic.com
  Embedding API      → https://api.openai.com
```

### docker-compose.yml excerpt

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: flyquery
      POSTGRES_USER: flyquery_admin
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  flyquery-api:
    image: ghcr.io/firefly-operationos/flyquery:26.5.10
    command: flyquery serve
    ports:
      - "8520:8520"
    environment:
      FLYQUERY_DATABASE_URL: postgresql+asyncpg://flyquery_app:${APP_PW}@postgres:5432/flyquery
      FLYQUERY_OBJECT_STORE: local
      FLYQUERY_OBJECT_STORE_BASE: /var/lib/flyquery/blobs
      FLYQUERY_EDA_ADAPTER: postgres
    depends_on: [postgres]
    volumes:
      - blobs:/var/lib/flyquery/blobs

  flyquery-worker:
    image: ghcr.io/firefly-operationos/flyquery:26.5.10
    command: flyquery worker all   # DEV ONLY -- production splits into two services
    environment:
      FLYQUERY_DATABASE_URL: postgresql+asyncpg://flyquery_app:${APP_PW}@postgres:5432/flyquery
      FLYQUERY_OBJECT_STORE: local
      FLYQUERY_OBJECT_STORE_BASE: /var/lib/flyquery/blobs
      FLYQUERY_INGEST_WORKER_CONCURRENCY: "4"
    depends_on: [postgres]
    volumes:
      - blobs:/var/lib/flyquery/blobs

volumes:
  pgdata:
  blobs:
```

---

## 3. Multi-node (production — separate services)

Production topology. Each component runs on its own infrastructure.
Suitable for Kubernetes, ECS, or bare-metal servers.

```
                         ┌──────────────────────────────┐
External clients ──────► │   Load balancer / ingress    │
                         │   (TLS termination)           │
                         └──────────────┬───────────────┘
                                        │ :8520
                         ┌──────────────▼───────────────┐
                         │   flyquery-api  (N replicas)  │
                         │                               │
                         │   stateless; horizontal scale │
                         └─┬────────────────────────┬───┘
                           │                        │
                           │ publish on             │ SQL + pgvector
                           │ flyquery.ingest        ▼
                           ▼                ┌────────────────────────┐
   ┌────────────────────────────┐           │     Postgres           │
   │  flyquery-ingest-worker    │           │     (managed or self-  │
   │  (M replicas;              │           │      hosted)           │
   │   CMD: worker ingest)      │           │     pgvector ext.      │
   │                            │           │                        │
   │  EDA subscribe +           │◄─────────►│  flyquery_* tables     │
   │  atomic PENDING → RUNNING  │           │  pgvector HNSW index   │
   │  per job claim             │           │  LISTEN/NOTIFY outbox  │
   └────────────┬───────────────┘           └────────────────────────┘
                │                                       ▲
                │ read/write                            │
                ▼                                       │
   ┌────────────────────────┐                           │
   │   Object Storage       │                           │
   │   S3 / GCS / Azure     │                           │
   │                        │                           │
   │  {tenant}/{ws}/        │                           │
   │    files/              │                           │
   │    tables/             │                           │
   │    derived/            │                           │
   │    results/            │     ┌─────────────────────┴───────────┐
   └────────────────────────┘     │  flyquery-retention-worker      │
                                  │  (1 replica; CMD: worker         │
                                  │   retention)                     │
                                  │                                  │
                                  │  Periodic loop (default 5min):   │
   ┌──────────────────────┐       │   - reap stuck RUNNING jobs      │
   │   Redis (optional)   │       │   - republish orphan PENDING     │
   │   rate limiter +     │       │   - TTL delete ingest/audit/cost │
   │   idempotency store  │       │   - PURGING dataset hard-delete  │
   └──────────────────────┘       └──────────────────────────────────┘
```

### Component sizing (starting point — small prod)

| Component | Starting size | Scale trigger |
|-----------|--------------|--------------|
| `flyquery-api` | 2 replicas, 2 vCPU, 4 GB RAM | p95 latency > 2 s |
| `flyquery-ingest-worker` | 1 replica, 2 vCPU, 8 GB RAM, `_CONCURRENCY=4` | queue depth > 20 |
| `flyquery-retention-worker` | 1 replica, 1 vCPU, 1 GB RAM | n/a — single instance |
| Postgres | db.t3.large (AWS) / n1-standard-2 (GCP) | Connection pool saturation |
| Redis | cache.t3.micro | Only needed with redis adapter |
| Object storage | Serverless (S3/GCS/Azure Blob) | N/A |

### Mid prod (steady ingest pressure)

| Component | Size | Notes |
|---|---|---|
| `flyquery-api` | 4 replicas, 2 vCPU, 4 GB RAM | |
| `flyquery-ingest-worker` | 3 replicas, 2 vCPU, 8 GB RAM, `_CONCURRENCY=4` | 12 concurrent jobs total |
| `flyquery-retention-worker` | 1 replica, 1 vCPU, 1 GB RAM | Sweep is cheap; one is enough |
| Postgres | db.r5.xlarge | More RAM for HNSW + describe-heavy workloads |

### Large prod / HA

| Component | Size | Notes |
|---|---|---|
| `flyquery-api` | 8+ replicas behind LB, autoscaled on p95 | |
| `flyquery-ingest-worker` | 6+ replicas, 4 vCPU, 16 GB RAM, `_CONCURRENCY=4` | 24+ concurrent jobs total. See [scale-and-performance.md](scale-and-performance.md) for the `N × _CONCURRENCY` formula. |
| `flyquery-retention-worker` | 1 (or 2 for redundancy — sweep is idempotent) | Don't autoscale; the sweep races itself fine but more processes don't help. |
| Postgres | db.r5.2xlarge Multi-AZ / Cloud SQL HA | |

Ingest workers need more RAM than API nodes because DuckDB runs
in-process during ingestion stages and embedding models may load in
RAM (if using local reranker). The retention worker stays small — it
only runs `UPDATE`s and `DELETE`s plus the occasional bus republish.

---

## 4. HA considerations

### API tier

Stateless; multiple replicas behind a load balancer. No sticky sessions
required. Health check endpoint: `GET /actuator/health`.

### IngestWorker tier

Multiple workers safely process different jobs (atomic PENDING → RUNNING
update on `flyquery_ingest_jobs`). No sticky sessions or leader election
required. Worker crashes are recovered by the RetentionWorker (see
below) — its `_reap_stuck_running` step resets jobs with `started_at`
older than `processing_lease_s` (default 1800s) back to PENDING and
republishes them.

**Graceful shutdown:**

```
SIGTERM → flyquery-ingest-worker
  1. Stop accepting new jobs
  2. Complete current stage for in-flight jobs (up to FLYQUERY_INGEST_SHUTDOWN_GRACE_S = 30 s)
  3. Exit cleanly
  Jobs not completed return to PENDING via the RetentionWorker sweep.
```

### RetentionWorker tier

One process per cluster is enough — the sweep is idempotent (every
operation is `UPDATE … WHERE status='RUNNING'` or `DELETE … WHERE
created_at < cutoff` with per-step failure isolation, see
[`retention_worker.py:114`](../src/flyquery/core/services/retention/retention_worker.py)).
Two is fine but redundant. Don't autoscale.

**Graceful shutdown:**

```
SIGTERM → flyquery-retention-worker
  1. request_stop() sets an asyncio.Event
  2. Current sweep finishes (sweeps are short)
  3. Sleep loop exits at the next interval boundary
```

If the retention worker is offline for hours, the impact is only that
stuck jobs aren't reaped and event ledgers grow. No data loss; no API
impact.

### Postgres

Use a managed service (RDS Multi-AZ, Cloud SQL HA, Azure Database with
zone-redundant standby) or configure Patroni/Repmgr for self-hosted.

flyquery does NOT use any Postgres-specific features beyond pgvector HNSW
indexes and LISTEN/NOTIFY. A standard HA setup is sufficient.

### Object storage

Use provider-native redundancy (S3 Multi-AZ, GCS multi-region, Azure ZRS).
Enable versioning for point-in-time recovery.

### Redis (if used)

Use Redis Sentinel or Redis Cluster for HA. flyquery's use of Redis (rate
limiter + idempotency) is non-critical: losing Redis state does not cause
data loss, only transient rate-limit state reset.

If Redis becomes unavailable and `FLYQUERY_RATE_LIMIT_BACKEND=redis`, the
service falls back to the in-memory rate limiter automatically (`auto` mode).

### EDA adapter and HA

With `FLYQUERY_EDA_ADAPTER=postgres` (default):
- Outbox events survive Postgres failover (they're in the database).
- LISTEN/NOTIFY connections are re-established on reconnect.
- No messages are lost on Postgres failover.

With `FLYQUERY_EDA_ADAPTER=redis` or `kafka`:
- Messages can be lost on Redis restart (not durable).
- Kafka provides durable, replicated topics; use for strict at-least-once
  delivery across replicas.

---

## 5. Service port reference

| Port | Component | Protocol | Notes |
|------|-----------|----------|-------|
| 8520 | `flyquery-api` | HTTP | REST API + SSE + Swagger UI (`/docs`) |
| n/a  | `flyquery-ingest-worker` | — | No listening port. Subscribes to the EDA bus + claims jobs from `flyquery_ingest_jobs`. Health is observed via Postgres + structured logs. |
| n/a  | `flyquery-retention-worker` | — | No listening port. Polling loop; emits `retention_sweep_completed` log lines per pass. |
| 5432 | Postgres | TCP | Internal only; not exposed externally |
| 6379 | Redis | TCP | Internal only |

Firefly Framework port conventions:
- flycanon: 8500
- flyradar: 8510
- flyquery: 8520

When updating [deployment.md](deployment.md), cross-link to this document for
topology diagrams.
