<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark) and (max-width: 600px)" srcset="docs/assets/brand/banner-dark-mobile.svg">
  <source media="(max-width: 600px)" srcset="docs/assets/brand/banner-light-mobile.svg">
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/banner-dark.svg">
  <img src="docs/assets/brand/banner-light.svg" alt="flyquery by Firefly" width="100%">
</picture>

### **Tabular Intelligence**

**Conversational SQL over the files your business actually has.**

Drop a CSV, XLSX, JSON or Parquet into a workspace. flyquery infers
the schema, materialises the file as columnar Parquet on object
storage and indexes it in a long-lived knowledge base of tables,
columns, AI-proposed joins, business glossary and semantic-layer
metrics — then answers natural-language questions through a
multi-agent pipeline (Grounding → Generation → Critic → Explainer)
that produces governed DuckDB SQL with row-level audit, tenant
isolation and per-token scopes. One HTTP service, multi-tenant from
the first call. Format coverage: CSV, TSV, XLSX, XLS, ODS, JSON,
JSONL, Parquet, Avro, ORC, Arrow and Feather, plus their `.gz`,
`.zip` and `.bz2` variants.

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org)
[![Java 25](https://img.shields.io/badge/java%20sdk-25-orange)](sdks/java/README.md)
[![pyfly](https://img.shields.io/badge/runtime-fireflyframework--pyfly-orange)](https://github.com/fireflyframework/fireflyframework-pyfly)
[![agentic](https://img.shields.io/badge/genai-fireflyframework--agentic-purple)](https://github.com/fireflyframework/fireflyframework-agentic)
[![OpenAPI](https://img.shields.io/badge/api-openapi%203.1-green)](docs/api-reference.md)
[![DuckDB](https://img.shields.io/badge/query%20engine-duckdb-yellow)](docs/architecture.md)
[![pgvector](https://img.shields.io/badge/vector--store-pgvector-336791)](docs/architecture.md)
[![Version](https://img.shields.io/badge/version-26.6.0-green.svg)](#)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

</div>

---

> **In a hurry?** &nbsp;Jump to the [**Quickstart →**](QUICKSTART.md) &nbsp;·&nbsp; SDK paths: [Python](sdks/python/README.md) · [Java](sdks/java/README.md) &nbsp;·&nbsp; Wire payloads: [**Payload reference →**](docs/payload-reference.md)

---

## Why this service exists

Analysts answering ad-hoc questions live in two worlds:

1. **Spreadsheets** — fast to start, impossible to govern. Excel and CSV
   tabs accumulate in inboxes; nobody knows which version is current,
   which column means what, or whether the numbers can be trusted.
2. **Warehouses + BI tools** — governed but expensive. Onboarding a
   new dataset means an ETL ticket, a dbt model, a schema review, and
   weeks before the first dashboard ships.

flyquery is the **middle path**. Drop a CSV (or XLSX, or JSON, or
Parquet) into a workspace; flyquery materialises it as Parquet on
object storage, derives a typed schema, samples + profiles each
column, runs a PII pass, proposes joins to your other tables, and
fits it to a long-lived knowledge base. Then you ask in English. A
multi-agent pipeline (Grounding → Generation → Critic → Explainer)
produces governed DuckDB SQL, runs it in a sandboxed connection
under per-token scopes, returns rows + a chart hint, and keeps a
conversation thread for drill-down.

You get the governance of a warehouse (RLS, audit, scopes,
versioned schemas, semantic-layer metrics) and the time-to-first-
answer of a spreadsheet (upload, ask, done).

What makes this non-trivial:

- **Structured data is messy.** Real-world files have inconsistent headers,
  mixed date formats, merged cells, compressed archives, and multi-sheet XLSX
  with completely different schemas per sheet.
- **Re-uploads break queries.** Column renames across versions silently break
  historical analytics. flyquery detects drifts, preserves annotations, and
  pins historical queries to specific Parquet snapshots.
- **SQL generation is unreliable.** A single-pass LLM call mis-identifies
  tables, invents columns, and silently drops GROUP BY. flyquery uses a
  four-agent pipeline with an AST firewall and self-correcting Critic to ensure
  only valid, scoped SQL executes.

---

## Why not part of flycanon?

flycanon and flyquery are deliberately separate services that solve fundamentally
different problems. Combining them would create a coherent-looking mess.

**flycanon** is the operational knowledge repository for **unstructured** content
(documents, HTML, PDFs, audio transcripts). Its model is: docs → chunks →
embeddings → hybrid retrieval → grounded answers with citations. The query
language is natural-language-to-RAG. The storage engine is pgvector + BM25 over
text chunks. The retrieval primitive is semantic chunk retrieval with candidate
scoring. The user-facing concepts are knowledge items, candidates, and
supersession.

**flyquery** handles **structured tabular data**. Its model is: file → typed
schema → Parquet on object storage → DuckDB SQL via multi-agent pipeline. The
query language is natural-language-to-SQL. The storage engine is Parquet on
object storage queried in-process by DuckDB. The retrieval primitive is
schema-element retrieval + table resolution + AST firewall. The user-facing
concepts are datasets, tables, snapshots, examples, and metrics.

The query languages, storage engines, retrieval primitives, and user-facing
concepts conflict on every layer. Keeping them separate lets each service be sharp
at its one job. Cross-service handoff happens via the agent tier with idempotency;
see [`docs/integration-with-firefly-os.md`](docs/integration-with-firefly-os.md).

---

## The shape of the system

```
                        User / Agent caller
                               │
                  REST API  /api/v1/*
                               │
         ┌─────────────────────┼──────────────────────┐
         │                     │                      │
   Upload surface         Query surface         Schema annotation
  POST /datasets/{id}/files  POST /query         PUT /schema-objects/{id}
  PUT  /tables/{id}:upload   POST /conversations  POST /examples/{id}:approve
         │                     │
         ▼                     ▼
  [IngestWorker]       [QueryService]
  10-stage async         Hybrid Retrieval
  pipeline               GroundingAgent
  (EDA topic)            GenerationAgent
         │               DuckDB Executor
         ▼               CriticAgent
  Parquet on             ExplainerAgent
  ObjectStore                  │
  (LocalFs/S3/GCS/Azure)       ▼
         │               AnswerResponse + SSE
         ▼               + presigned Parquet URL
  Postgres + pgvector
  (schema KB, relations,
   examples, audit)
```

Three tiers: **upload surface** (async ingest into object storage + schema KB),
**query surface** (multi-agent NL→SQL over Parquet), **annotation surface**
(human governance of descriptions, PII tags, relations, examples).

---

## Quickstart

The commands below use a local stack (`task dev` starts Postgres + Redis + MinIO).
See [QUICKSTART.md](QUICKSTART.md) for the full walkthrough including credentials,
MinIO bucket setup, and environment variables.

```bash
# 1. Boot
task dev && task migrate && task serve
```

```bash
# 2. Create a workspace and dataset
TENANT=acme
WS_ID=$(curl -s -X POST http://localhost:8520/api/v1/workspaces \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: $TENANT" \
  -d '{"name": "analytics", "description": "Q1 analytics"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

DS_ID=$(curl -s -X POST http://localhost:8520/api/v1/datasets \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: $TENANT" -H "X-Workspace-Id: $WS_ID" \
  -d '{"name": "q1_sales", "description": "Q1 sales export"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

```bash
# 3. Upload a CSV
JOB_ID=$(curl -s -X POST \
  "http://localhost:8520/api/v1/datasets/$DS_ID/files" \
  -H "X-Tenant-Id: $TENANT" -H "X-Workspace-Id: $WS_ID" \
  -F "file=@sales_q1.csv" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['ingest_job_id'])")
```

```bash
# 4. Stream ingest progress (SSE — Ctrl-C when you see "SUCCEEDED")
curl -N "http://localhost:8520/api/v1/ingest-jobs/$JOB_ID/stream" \
  -H "X-Tenant-Id: $TENANT" -H "X-Workspace-Id: $WS_ID"
```

```bash
# 5. Ask a question
curl -s -X POST http://localhost:8520/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: $TENANT" -H "X-Workspace-Id: $WS_ID" \
  -d "{\"question\": \"Total revenue by region for Q1\", \"dataset_id\": \"$DS_ID\"}" \
  | python3 -m json.tool
# → {
#     "answer": "Total Q1 revenue is $4.2M. Northeast led at $1.8M (43%).",
#     "executed_sql": "SELECT region, SUM(revenue) FROM sales_q1 GROUP BY region",
#     "chart_hint": "bar",
#     "result_url": "https://minio.local/flyquery/results/..."
#   }
```

---

## Capabilities

| Capability | Detail |
|------------|--------|
| **12 file formats** | CSV, TSV, XLSX, XLS, ODS, JSON, JSONL, Parquet, Avro, ORC, Arrow, Feather |
| **Compression** | .gz, .zip, .bz2 transparently unwrapped |
| **10-stage pipeline** | Receive → Parse → Reconcile → Sample → Profile → Relations → Describe → PII → Embed → Publish |
| **4-agent query pipeline** | GroundingAgent → GenerationAgent → CriticAgent → ExplainerAgent |
| **AST firewall** | sqlglot + DuckDB double-check; single-statement SELECT only on uploaded tables |
| **Schema knowledge base** | pgvector HNSW + BM25 + cross-encoder reranker |
| **Semantic layer** | OSI/MetricFlow YAML metrics, deterministic SQL compilation |
| **Conversation memory** | Multi-turn drill-down with snapshot pinning |
| **Multi-tenancy** | Postgres RLS on all tables; two-role split (admin/app) |
| **Auto-learning** | First-shot OK queries auto-propose `(question, SQL)` examples |
| **PII scanning** | regex/Presidio; warn/redact/reject policy |
| **Agent surface** | Full `/api/v1/agent/*` mirror with `X-Agent-Token` + `Idempotency-Key` |
| **SDKs** | Python (`flyquery-sdk`) and Java (`com.firefly:flyquery-sdk`) auto-generated from OpenAPI |

---

## Documentation

All docs live in [`docs/`](docs/). Start with:

| Document | Purpose |
|----------|---------|
| [**docs/README.md**](docs/README.md) | Navigation hub — reading paths by intent |
| [docs/architecture.md](docs/architecture.md) | System design, pipelines, hexagonal ports |
| [docs/api-reference.md](docs/api-reference.md) | REST surface — every endpoint, header, scope |
| [docs/pipeline.md](docs/pipeline.md) | Upload + query pipelines end-to-end with diagrams |
| [docs/ingestion.md](docs/ingestion.md) | 10-stage ingestion detail |
| [docs/file-formats.md](docs/file-formats.md) | Per-format reader matrix |
| [docs/semantic-layer.md](docs/semantic-layer.md) | MetricFlow YAML + compilation |
| [docs/payload-reference.md](docs/payload-reference.md) | DTO catalog |
| [docs/security-model.md](docs/security-model.md) | RLS, tokens, AST firewall, PII policy |
| [docs/deployment.md](docs/deployment.md) | Ops reference |
| [docs/conversations.md](docs/conversations.md) | Multi-turn query memory + drill-down |
| [docs/eda-events.md](docs/eda-events.md) | Events published: flyquery.ingest + flyquery.schema |
| [docs/glossary.md](docs/glossary.md) | Term definitions |
| [docs/firefly-intelligence-system.md](docs/firefly-intelligence-system.md) | flycanon + flyradar + flyquery cross-narrative |
| [docs/embeddings.md](docs/embeddings.md) | Provider-agnostic embedder (Ollama / OpenAI / Cohere / …) |
| [docs/semantic-types.md](docs/semantic-types.md) | 49-label semantic-type taxonomy for ingested columns |
| [docs/prompt-engine.md](docs/prompt-engine.md) | YAML + Jinja2 prompt files under `src/flyquery/resources/prompts/` |
| [docs/cost-tracking.md](docs/cost-tracking.md) | Usage surfacing per agent stage in query / ingest responses |
| [examples/README.md](examples/README.md) | Synthetic CSV / JSON / JSONL / XLSX / Parquet fixtures + smoke recipe |

Full index with reading paths: [**docs/README.md →**](docs/README.md)

---

## Local dev

```bash
task dev          # docker compose up postgres + redis + minio
task migrate      # alembic upgrade head
task serve        # uvicorn flyquery.main:app --reload
```

### Running tests

```bash
task lint
task test:unit
task test:integration
```

Integration tests require Docker (testcontainers spins up `pgvector/pgvector:pg16`).
Tests marked `@pytest.mark.s3` / `@pytest.mark.gcs` / `@pytest.mark.azure_blob`
need local credentials or MinIO/fake-gcs/Azurite — see [`QUICKSTART.md`](QUICKSTART.md).

Tests marked `@pytest.mark.llm` require `ANTHROPIC_API_KEY`. Exclude them in CI
with `-m 'not llm'`.

---

## Architecture quick-take

flyquery uses a **two-tier storage design**: Parquet on object storage (LocalFs in
dev; S3/GCS/Azure Blob in production) queried by DuckDB in-process per request.
Postgres stores all metadata, embeddings, relations, audit, and agent tokens.
There is no persistent DuckDB database — every query ATTACHes Parquet snapshots
fresh, eliminating shared mutable state between requests.

The **hexagonal adapter ring** means every external boundary (object store, file
reader, vector store, PII scanner, semantic compiler, rate limiter) is a Python
`Protocol`; the domain core never depends on a concrete implementation.

Lock-step modules (`web/conventions/*`, `agent_deps.py`, `agent_token_service.py`,
`builder.py`) are byte-equivalent with flycanon and flyradar. A CI gate
(`scripts/check_lockstep.py`) blocks PRs that drift.

See [docs/architecture.md](docs/architecture.md) for the full picture.

---

## Repository and identity

Source, issues and release downloads are hosted under the
[fireflyframework organization](https://github.com/fireflyframework/flyquery).
See [identity and package registries](docs/branding.md) for banner provenance
and the distinction between source transfers and historical package namespaces.

## License

flyquery is released under the [Apache License 2.0](LICENSE) —
copyright 2024-2026 Firefly Software Foundation.

The bundled Python SDK (`sdks/python/`) and Java SDK (`sdks/java/`) ship
their own Apache License 2.0 files.
