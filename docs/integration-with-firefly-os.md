# flyquery — Integration with Firefly Framework

## Table of Contents

1. [The three-pillar narrative](#1-the-three-pillar-narrative)
2. [flyradar referencing a flyquery dataset](#2-flyradar-referencing-a-flyquery-dataset)
3. [flycanon RAG over flyquery metadata](#3-flycanon-rag-over-flyquery-metadata)
4. [Shared ubiquitous language](#4-shared-ubiquitous-language)
5. [Lock-step modules](#5-lock-step-modules)
6. [Cross-service agent-token patterns](#6-cross-service-agent-token-patterns)
7. [EDA fan-out across services](#7-eda-fan-out-across-services)

---

## 1. The three-pillar narrative

Firefly Framework structures operational intelligence into three pillars:

| Service | Owns | Primary surface |
|---------|------|----------------|
| **flycanon** | Unstructured knowledge — documents, process artefacts, runbooks, notes | Natural-language RAG with citations |
| **flyradar** | Discovery graphs — process topology, bottlenecks, dependency DAGs, signal streams | Discovery jobs + diagnostic queries |
| **flyquery** | Structured files uploaded by operators — CSVs, XLSX, Parquet, JSON | Natural-language Text-to-SQL over Parquet |

Each pillar is independently useful. Together they form a complete operational
intelligence platform:

```
              flycanon                flyradar              flyquery
          (know-it-all KB)      (shows what's broken)   (answers about data)
                │                      │                       │
                │                      │                       │
                └──────────────────────┴───────────────────────┘
                                       │
                              Firefly Framework
                         (unified tenant/workspace model)
```

All three share:
- The same `(tenant_id, workspace_id)` identity model.
- The same `X-Tenant-Id` / `X-Workspace-Id` headers.
- Lock-step `web/conventions/*` modules (byte-equivalent).
- The same agent-token format (`agt_<8hex>_<32hex>`).
- The same CalVer release cadence.

---

## 2. flyradar referencing a flyquery dataset

### Use case

A flyradar discovery identifies that a process bottleneck is correlated with
high order volumes. flyradar wants to query flyquery's `orders` dataset to
quantify the relationship: "On days when ingest queue depth > 100, what is
the average order count?"

### How it works

1. **flyradar holds an agent token** with `flyquery.query:read` and
   `flyquery.schema:read` scopes, scoped to the tenant/workspace.

2. flyradar calls `GET /api/v1/agent/tables/{table_id}` to get the schema
   of the relevant table, enriching its discovery context.

3. flyradar calls `POST /api/v1/agent/query` with the question:

```bash
curl -X POST http://flyquery:8520/api/v1/agent/query \
  -H "X-Tenant-Id: acme" \
  -H "X-Workspace-Id: analytics" \
  -H "X-Agent-Token: agt_radar_..." \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "dataset_id": "ds_orders",
    "question": "Average daily order count on days with order_count > 500"
  }'
```

4. flyradar receives the structured `AnswerResponse` (including
   `executed_sql`, `result_url` for the full Parquet result) and
   incorporates the data into its discovery report.

### Schema discovery first

Before querying, flyradar benefits from knowing which tables and columns are
available:

```python
# flyradar fetches flyquery schema for its own grounding
tables = await flyquery_client.tables.list(dataset_id=ds_id)
for table in tables:
    schema = await flyquery_client.schema_objects.list(
        table_id=table.table_id, kind="COLUMN"
    )
    # Store in flyradar's own knowledge context
```

### Subscribing to schema changes

flyradar subscribes to `flyquery.schema` (SchemaUpdated events) to
invalidate its schema cache when a dataset changes:

```python
@subscribe(topic="flyquery.schema", event="SchemaUpdated")
async def invalidate_flyradar_schema_cache(event: dict, **_):
    await radar_cache.evict(
        namespace="flyquery_schema",
        key=event["table_id"],
    )
```

---

## 3. flycanon RAG over flyquery metadata

### Use case

A flycanon source contains a document: "Our sales metrics are tracked in the
`ds_sales` dataset. Column `revenue_amount` is the total transaction value."
A user asks flycanon: "What columns are relevant for revenue analysis?"

flycanon answers from its own document corpus. If it also has access to
flyquery's schema knowledge, it can ground its answer in the actual schema.

### How it works

1. **flycanon optionally enriches** its RAG answer by calling flyquery's
   schema search:

```python
# In flycanon's AnswerService, if flyquery integration is enabled:
schema_results = await flyquery_client.schema_objects.search(
    query="revenue analysis",
    workspace_id=workspace_id,
    limit=5,
)
# Inject schema metadata into the flycanon grounding context
grounding_context["flyquery_schema"] = schema_results
```

2. flycanon's GroundingAgent uses this enriched context to provide a more
   specific answer: "Based on the flyquery schema, the `revenue_amount` column
   in the `transactions` table is the primary revenue metric."

### Registering flyquery metadata in flycanon (v1+)

A v1+ integration pattern registers flyquery schema objects as flycanon
knowledge items. This allows:

- flycanon's hybrid retrieval to surface schema objects alongside document
  knowledge in a unified answer.
- Users asking flycanon "what data do we have on customer churn?" to receive
  answers that reference both policy documents and actual tables.

The handoff shape (from flycanon's existing `agent/canon/handoff` surface)
is:

```python
# flyquery emits a SchemaUpdated event
# A bridge service or flycanon consumer:
async def on_schema_updated(event: dict, **_):
    schema_objects = await flyquery_client.schema_objects.list(
        table_id=event["table_id"], is_active=True
    )
    for obj in schema_objects:
        await flycanon_client.candidates.create(
            source_id=flyquery_source_id,
            content=f"{obj.qualified_name}: {obj.description}",
            metadata={"table_id": obj.table_id, "kind": obj.kind},
        )
```

This is opt-in per workspace and requires:
- A flycanon source registered for the flyquery dataset.
- A flyquery agent token with `flyquery.schema:read`.
- A flycanon agent token with `flycanon.candidates:write`.

---

## 4. Shared ubiquitous language

Per the `feedback_ubiquitous_language` memory, all three services share the
same naming for the identity hierarchy. No "X by convention means Y" mappings.

| Term | flycanon | flyradar | flyquery |
|------|---------|---------|---------|
| Tenant isolation root | `tenant_id` | `tenant_id` | `tenant_id` |
| Workspace scope | `workspace_id` | `workspace_id` | `workspace_id` |
| Header | `X-Tenant-Id` | `X-Tenant-Id` | `X-Tenant-Id` |
| Header | `X-Workspace-Id` | `X-Workspace-Id` | `X-Workspace-Id` |
| DTO field | `tenant_id`, `workspace_id` | `tenant_id`, `workspace_id` | `tenant_id`, `workspace_id` |

Cross-service calls must pass these headers. RLS on all three services
enforces them at the database level.

---

## 5. Lock-step modules

The source-contract gate preserves nineteen normalized historical shared
baselines. The builder and observability module are service-specific variants
with reviewed full-file pins; the check does not compare live canon/radar main.

| Module | Purpose |
|--------|---------|
| `web/conventions/middleware.py` | `TenantContextMiddleware` — GUC binding |
| `web/conventions/deps.py` | FastAPI dependency helpers |
| `web/conventions/headers.py` | Header extraction |
| `web/conventions/actor.py` | Actor resolution (JWT / agent token) |
| `web/conventions/context.py` | Context var wiring |
| `web/conventions/errors.py` | RFC 7807 error handlers |
| `web/conventions/idempotency.py` | Idempotency-Key enforcement |
| `web/conventions/redis_idempotency.py` | Redis-backed idempotency store |
| `web/conventions/db.py` | AsyncSession factory + after_begin hook |
| `web/conventions/handlers.py` | Exception handler wiring |
| `web/agent_deps.py` | Agent-token FastAPI dependency |
| `web/openapi_override.py` | OpenAPI spec customisation |
| `core/agents/builder.py` | `build_agent` factory |
| `core/observability/__init__.py` | Configured provider prompt-cache policy |
| `core/services/auth/agent_token_service.py` | Token verify logic |
| `core/services/auth/redis_rate_limiter.py` | Redis rate limiter |
| `web/controllers/agent_tokens_controller.py` | Token CRUD endpoints |

Use `task lockstep` to reject drift. Do not copy changes across services
without checking their current APIs. The [architecture guide](architecture.md#9-lock-step-modules)
documents the two bounded variants, their provenance, and the retained baselines.

---

## 6. Cross-service agent-token patterns

### flyradar calling flyquery

flyradar should hold a flyquery agent token with minimal scopes:

```json
{
  "name": "flyradar-discovery",
  "scopes": [
    "flyquery.schema:read",
    "flyquery.query:read",
    "flyquery.relations:read"
  ],
  "workspace_allowlist": ["<workspace_id>"],
  "rate_limit_rpm": 30
}
```

### flycanon calling flyquery

flycanon should hold a flyquery agent token for schema enrichment:

```json
{
  "name": "flycanon-schema-enrichment",
  "scopes": ["flyquery.schema:read"],
  "workspace_allowlist": ["<workspace_id>"],
  "rate_limit_rpm": 10
}
```

### Storing cross-service tokens

Tokens are secrets. Store in the calling service's secrets manager
(AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, HashiCorp Vault).
Do not hardcode in environment files or docker-compose.yml.

---

## 7. EDA fan-out across services

When a user uploads a file to flyquery, the `SchemaUpdated` event published
to `flyquery.schema` can fan out to multiple consumers:

```
flyquery (stage 10)
    │
    ▼
flyquery.schema → SchemaUpdated event
    │
    ├─► flyradar consumer:   invalidate schema cache + optionally re-run discovery
    ├─► flycanon consumer:   optionally register schema objects as knowledge items
    └─► custom consumer:     invalidate BI dashboard cache, notify Slack, etc.
```

The Postgres LISTEN/NOTIFY default adapter supports multiple concurrent
listeners. Each consumer gets its own LISTEN channel (or `EDA_GROUP` in
Kafka mode).

See [eda-events.md](eda-events.md) for the event schema and consumer guide.

For the broader intelligence system narrative see
[firefly-intelligence-system.md](firefly-intelligence-system.md).
