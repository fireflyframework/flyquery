# flyquery — Payload Reference

## Table of Contents

1. [Overview](#1-overview)
2. [Workspace DTOs](#2-workspace-dtos)
3. [Dataset DTOs](#3-dataset-dtos)
4. [File and table DTOs](#4-file-and-table-dtos)
5. [Ingest job DTOs](#5-ingest-job-dtos)
6. [Schema object DTOs](#6-schema-object-dtos)
7. [Query DTOs](#7-query-dtos)
8. [Semantic layer DTOs](#8-semantic-layer-dtos)
9. [Agent token DTOs](#9-agent-token-dtos)
10. [Error DTOs](#10-error-dtos)
11. [v1 ops DTOs (history, billing, stats — new in 26.5.10)](#11-v1-ops-dtos-history-billing-stats--new-in-26510)
12. [Generating schemas from code](#12-generating-schemas-from-code)

---

## 1. Overview

This document provides representative JSON examples for the most-used DTOs.
All field types, required/optional markers, and validation rules are also
available in:
- `openapi.json` — committed OpenAPI snapshot (machine-readable)
- `src/flyquery/interfaces/` — Pydantic model definitions

For complete schema detail, the `openapi.json` is the source of truth.

Common conventions:
- `id` fields are UUID v4 strings (`"01906f2a-..."` format).
- `tenant_id` and `workspace_id` are passed via request headers, not request
  bodies.
- `created_at` / `updated_at` are ISO 8601 UTC timestamps.
- Nullable fields use JSON `null`; absent optional fields default per Pydantic
  model defaults (see source).

---

## 2. Workspace DTOs

### WorkspaceCreate

```json
{
  "slug": "analytics",
  "name": "Analytics",
  "kms_key_uri": null,
  "retention_days": null,
  "allow_direct_sql": false,
  "default_locale": "en-US"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `slug` | `string` | Yes | Alphanumeric + hyphen; unique per tenant; immutable after creation |
| `name` | `string` | Yes | Display name; max 200 chars |
| `kms_key_uri` | `string \| null` | No | CMK/CMEK URI; null = storage-native SSE |
| `retention_days` | `int \| null` | No | null = keep forever |
| `allow_direct_sql` | `boolean` | No | Default `false`; enables `POST /sql:execute` |
| `default_locale` | `string` | No | BCP 47 locale; default `"en-US"` |

### WorkspaceResponse

```json
{
  "id": "01906f2a-0000-7000-a000-000000000001",
  "slug": "analytics",
  "name": "Analytics",
  "allow_direct_sql": false,
  "default_locale": "en-US",
  "storage_used_bytes": 5368709120,
  "kms_key_uri": null,
  "retention_days": 90,
  "created_at": "2026-05-23T12:00:00Z",
  "updated_at": "2026-05-23T12:00:00Z"
}
```

---

## 3. Dataset DTOs

### DatasetCreate

```json
{
  "name": "sales-2026",
  "description": "Annual sales export",
  "drift_policy": "AUTO",
  "ingest_policy_json": {
    "sample_disabled": false,
    "describe_budget_cents_override": 500
  },
  "default_locale": null
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | `string` | Yes | Unique per workspace; alphanumeric + hyphen + underscore |
| `description` | `string \| null` | No | |
| `drift_policy` | `"AUTO" \| "REVIEW"` | No | Default `"AUTO"` |
| `ingest_policy_json` | `object \| null` | No | See [ingestion.md §7](ingestion.md#7-ingest_policy_json-reference) |
| `default_locale` | `string \| null` | No | Overrides workspace locale for this dataset |

### DatasetResponse

```json
{
  "id": "01906f2a-0000-7000-a000-000000000002",
  "name": "sales-2026",
  "description": "Annual sales export",
  "drift_policy": "AUTO",
  "status": "ACTIVE",
  "ingest_policy_json": {},
  "default_locale": null,
  "created_at": "2026-05-23T12:00:00Z",
  "updated_at": "2026-05-23T12:00:00Z"
}
```

---

## 4. File and table DTOs

### FileUploadResponse

Returned by `POST /api/v1/datasets/{id}/files` (202 Accepted):

```json
{
  "file_id": "01906f2b-0000-7000-a000-000000000003",
  "ingest_job_id": "01906f2c-0000-7000-a000-000000000004",
  "tables": [
    {
      "table_id": "01906f2d-0000-7000-a000-000000000005",
      "qualified_name": "sales-2026.orders",
      "sheet_or_json_path": null,
      "n_rows_estimate": 15000,
      "n_columns": 12
    },
    {
      "table_id": "01906f2e-0000-7000-a000-000000000006",
      "qualified_name": "sales-2026.returns",
      "sheet_or_json_path": "Sheet2",
      "n_rows_estimate": 1200,
      "n_columns": 8
    }
  ]
}
```

### TableResponse

```json
{
  "id": "01906f2d-0000-7000-a000-000000000005",
  "dataset_id": "01906f2a-0000-7000-a000-000000000002",
  "source_file_id": "01906f2b-0000-7000-a000-000000000003",
  "name": "orders",
  "qualified_name": "sales-2026.orders",
  "kind": "UPLOADED",
  "sheet_or_json_path": null,
  "current_snapshot_id": "01906f2f-0000-7000-a000-000000000007",
  "description": "Customer orders table",
  "description_source": "AGENT",
  "business_owner": "sales-team",
  "is_active": true,
  "created_at": "2026-05-23T12:00:00Z",
  "updated_at": "2026-05-23T12:05:00Z"
}
```

### SnapshotResponse

```json
{
  "id": "01906f2f-0000-7000-a000-000000000007",
  "table_id": "01906f2d-0000-7000-a000-000000000005",
  "taken_at": "2026-05-23T12:05:00Z",
  "snapshot_hash": "sha256:abc123...",
  "n_columns": 12,
  "n_rows_estimate": 15000,
  "n_rows_actual": 14983,
  "parquet_byte_size": 204800,
  "status": "READY",
  "triggered_by": "USER",
  "created_by": "alice@acme.com"
}
```

---

## 5. Ingest job DTOs

### IngestJobCreate

```json
{
  "job_kind": "DESCRIBE_PASS",
  "dataset_id": "01906f2a-0000-7000-a000-000000000002",
  "table_id": "01906f2d-0000-7000-a000-000000000005"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `job_kind` | `enum` | Yes | `PARSE_AND_INGEST \| REPARSE \| SAMPLE_REFRESH \| DESCRIBE_PASS \| RELATION_PASS` |
| `dataset_id` | `string` | Yes | |
| `table_id` | `string \| null` | No | Required for `REPARSE`, `SAMPLE_REFRESH`; optional for others |
| `file_id` | `string \| null` | No | Required for `REPARSE` |

### IngestJobResponse

```json
{
  "id": "01906f2c-0000-7000-a000-000000000004",
  "job_kind": "PARSE_AND_INGEST",
  "dataset_id": "01906f2a-0000-7000-a000-000000000002",
  "file_id": "01906f2b-0000-7000-a000-000000000003",
  "table_id": null,
  "snapshot_id": "01906f2f-0000-7000-a000-000000000007",
  "status": "SUCCEEDED",
  "attempts": 1,
  "started_at": "2026-05-23T12:00:05Z",
  "finished_at": "2026-05-23T12:05:30Z",
  "elapsed_ms": 325000,
  "cost_cents": 120
}
```

---

## 6. Schema object DTOs

### SchemaObjectUpdate

Sent to `PUT /api/v1/schema-objects/{id}`:

```json
{
  "description": "Gross order amount in USD cents, before tax and discounts",
  "pii_tag": "NONE",
  "business_owner": "finance-team",
  "synonyms_json": ["order value", "gross amount"],
  "governance_json": {
    "sensitivity": "internal",
    "retention_class": "standard"
  }
}
```

### SchemaObjectResponse

```json
{
  "id": "01906f30-0000-7000-a000-000000000008",
  "table_id": "01906f2d-0000-7000-a000-000000000005",
  "snapshot_id": "01906f2f-0000-7000-a000-000000000007",
  "kind": "COLUMN",
  "parent_id": "01906f31-0000-7000-a000-000000000009",
  "qualified_name": "sales-2026.orders.order_amount",
  "data_type": "BIGINT",
  "is_nullable": false,
  "description": "Gross order amount in USD cents, before tax and discounts",
  "description_source": "HUMAN",
  "synonyms_json": ["order value", "gross amount"],
  "pii_tag": "NONE",
  "pii_source": "REGEX",
  "business_owner": "finance-team",
  "sample_values_json": [1999, 4500, 12000, 800, 2399],
  "profile_json": {
    "null_fraction": 0.0,
    "distinct_estimate": 8923,
    "min": 100,
    "max": 99900
  },
  "is_active": true,
  "last_seen_at": "2026-05-23T12:05:00Z"
}
```

---

## 7. Query DTOs

### QueryRequest

```json
{
  "question": "Show top 10 customers by revenue last month",
  "dataset_id": "01906f2a-0000-7000-a000-000000000002",
  "conversation_id": null
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `question` | `string` | Yes | Natural-language question |
| `dataset_id` | `string` | Yes | UUID of the selected dataset |
| `conversation_id` | `string \| null` | No | For multi-turn drill-down |

The current DTO has no `row_cap` or `statement_timeout_ms` fields. The
executor uses `FLYQUERY_DEFAULT_ROW_CAP`; statement timeouts are currently
unenforced. See the [SQL read boundary](security-model.md#sql-read-boundary).

### AnswerResponse

```json
{
  "query_id": "01906f40-0000-7000-a000-000000000010",
  "executed_sql": "SELECT c.name, SUM(o.order_amount) AS revenue\nFROM orders o\nJOIN customers c ON o.customer_id = c.id\nWHERE o.order_date >= '2026-04-01' AND o.order_date < '2026-05-01'\nGROUP BY c.name\nORDER BY revenue DESC\nLIMIT 10",
  "semantic_path_taken": "SYNTHESIS",
  "execution_status": "OK",
  "retries": 0,
  "row_count": 10,
  "elapsed_ms": 2340,
  "clarification_emitted": false,
  "clarification": null,
  "result_preview": [
    {"name": "Acme Corp", "revenue": 1240000},
    {"name": "Global Ltd", "revenue": 980000}
  ],
  "result_parquet_url": "https://storage.example.com/presigned/...",
  "result_url_expires_at": "2026-05-24T12:00:00Z",
  "explanation": "The query joins the orders table to the customers table on customer_id, filters to April 2026 orders, aggregates revenue by customer name, and returns the top 10.",
  "chart_hint": "bar",
  "snapshot_pins": {
    "01906f2d-...": "01906f2f-..."
  },
  "cost_cents": 42
}
```

### ConversationTurnRequest

```json
{
  "question": "Now break that down by region"
}
```

No additional fields needed — the prior turn's `executed_sql`, `table_qnames`,
and `snapshot_pins` are carried automatically from the conversation state.

---

## 8. Semantic layer DTOs

### SemanticMetricCreate

```json
{
  "name": "total_revenue",
  "label": "Total Revenue",
  "description": "Sum of order_amount across completed orders",
  "metric_type": "SIMPLE",
  "dataset_id": "01906f2a-0000-7000-a000-000000000002",
  "definition_yaml": "metric:\n  name: total_revenue\n  type: simple\n  type_params:\n    measure:\n      name: order_amount\n      agg: sum\n    filter: \"order_status = 'COMPLETED'\"\n  group_by:\n    - region\n"
}
```

### SemanticMetricResponse

```json
{
  "id": "01906f60-0000-7000-a000-000000000011",
  "name": "total_revenue",
  "label": "Total Revenue",
  "description": "Sum of order_amount across completed orders",
  "metric_type": "SIMPLE",
  "dataset_id": "01906f2a-0000-7000-a000-000000000002",
  "status": "DRAFT",
  "current_version": 1,
  "definition_yaml": "...",
  "compiled_sql_template": "SELECT region, SUM(order_amount) AS total_revenue\nFROM \"sales-2026\".\"orders\"\nWHERE order_status = 'COMPLETED'\n  {extra_filter_clause}\nGROUP BY region\n  {group_by_append}",
  "created_at": "2026-05-23T12:00:00Z",
  "updated_at": "2026-05-23T12:00:00Z"
}
```

### GlossaryTermCreate

```json
{
  "term": "ARR",
  "definition": "Annual Recurring Revenue",
  "synonyms": ["annual recurring revenue", "annual run rate"],
  "related_metrics": ["total_mrr"]
}
```

---

## 9. Agent token DTOs

### AgentTokenCreate

```json
{
  "name": "etl-pipeline",
  "scopes": [
    "flyquery.files:upload",
    "flyquery.ingest:read",
    "flyquery.query:read"
  ],
  "workspace_allowlist": ["analytics"],
  "dataset_allowlist": null,
  "expires_at": "2027-01-01T00:00:00Z",
  "rate_limit_rpm": 60
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | `string` | Yes | Human-readable label |
| `scopes` | `string[]` | Yes | From the scope catalog; see [api-reference.md §7](api-reference.md#7-scope-catalog) |
| `workspace_allowlist` | `string[] \| null` | No | null = all workspaces the caller can access |
| `dataset_allowlist` | `string[] \| null` | No | null = all datasets |
| `expires_at` | `string \| null` | No | ISO 8601; null = no expiry |
| `rate_limit_rpm` | `int \| null` | No | null or 0 = no limit |

### AgentTokenCreatedResponse

```json
{
  "token_id": "01906f50-0000-7000-a000-000000000012",
  "token": "agt_a1b2c3d4_fedcba9876543210fedcba9876543210",
  "prefix": "agt_a1b2c3d4",
  "name": "etl-pipeline",
  "scopes": ["flyquery.files:upload", "flyquery.ingest:read", "flyquery.query:read"],
  "workspace_allowlist": ["analytics"],
  "expires_at": "2027-01-01T00:00:00Z",
  "created_at": "2026-05-23T12:00:00Z"
}
```

The `token` field is returned **only on creation**. Store it immediately.
Subsequent `GET /agent-tokens` responses return only the `prefix`.

---

## 10. Error DTOs

All errors use RFC 7807 Problem Details:

```json
{
  "type": "https://firefly.dev/problems/validation_error",
  "title": "Request validation failed",
  "status": 400,
  "code": "validation_error",
  "detail": "1 validation error",
  "errors": [
    {
      "path": "definition_yaml",
      "message": "Unknown metric type 'ratio' is not supported in v0"
    }
  ]
}
```

Idempotency replay (same key, different body):
```json
{
  "type": "https://firefly.dev/problems/conflict",
  "title": "Idempotency key conflict",
  "status": 409,
  "code": "conflict",
  "detail": "Idempotency-Key 'abc123' was used for a different request body within the replay window.",
  "errors": []
}
```

Rate limit exceeded:
```json
{
  "type": "https://firefly.dev/problems/rate_limit_exceeded",
  "title": "Rate limit exceeded",
  "status": 429,
  "code": "rate_limit_exceeded",
  "detail": "Token 'agt_a1b2c3d4' exceeded 60 rpm.",
  "errors": []
}
```

---

## 11. v1 ops DTOs (history, billing, stats — new in 26.5.10)

Wire payloads for the v1 query-history, billing, async-upload, and
stats endpoints. All shapes live in
[`src/flyquery/interfaces/query.py`](../src/flyquery/interfaces/query.py),
[`src/flyquery/interfaces/ops.py`](../src/flyquery/interfaces/ops.py),
[`src/flyquery/interfaces/files.py`](../src/flyquery/interfaces/files.py),
and [`src/flyquery/interfaces/pagination.py`](../src/flyquery/interfaces/pagination.py).

### Paginated[T]

Generic envelope used by every list endpoint:

```json
{
  "items": [...],
  "total": 1402,
  "limit": 50,
  "offset": 0
}
```

`limit` is clamped to the per-endpoint maximum (the query-history list
caps it at `200`); `total` is the total count of matching rows, not
just the page.

### QueryHistoryItem

Compact row for `GET /api/v1/queries`. Heavy JSONB columns
(candidates, clarification, PII findings) are omitted so a 50-item
page stays under a few KB.

Fields: `id`, `tenant_id`, `workspace_id`, `dataset_id?`, `question`,
`executed_sql?`, `ast_classification?`, `execution_status?`,
`row_count?`, `elapsed_ms?`, `semantic_path_taken?`, `retries`,
`clarification_emitted`, `created_at`, `finalised_at?`.

### QueryDetailRead

Full single-query payload for `GET /api/v1/queries/{id}`. Includes
every candidate proposal, AST classification, every model identifier
used (`model_grounding` / `model_generation` / `model_critic` /
`model_explainer`), PII findings, clarification frame, retries, and
the final error envelope if any. JSONB columns are passed through as
Python dicts / lists.

### QueryResultRead

Re-download envelope for `GET /api/v1/queries/{id}/result`:

```json
{
  "query_id": "01906f40-...",
  "preview_json": [{"region": "EU", "revenue": 14230}],
  "parquet_presigned_url": "https://...",
  "result_byte_size": 204800,
  "ttl_expires_at": "2026-05-24T12:00:00Z"
}
```

`parquet_presigned_url` is `null` once `ttl_expires_at` has elapsed
(default 24h) or if presign fails — consumer must rerun the query.

### BillingRollup

Response from `GET /api/v1/billing`:

```json
{
  "period": "day",
  "date_from": "2026-05-01T00:00:00Z",
  "date_to": "2026-05-25T00:00:00Z",
  "total_cost_cents": 14230,
  "breakdown": [{"date": "...", "ingest_cost_cents": 200, ...}]
}
```

### BillingBreakdownItem

One bucket of the rollup:

```json
{
  "date": "2026-05-23T00:00:00Z",
  "ingest_cost_cents": 200,
  "query_cost_cents": 14030,
  "other_cost_cents": 0,
  "total_cost_cents": 14230
}
```

Costs are `Decimal` in the model (partial cents are common at the
per-call granularity). Wire is JSON number.

### WorkspaceStats

Response from `GET /api/v1/stats`:

```json
{
  "storage_used_bytes": 524288000,
  "dataset_count": 5,
  "table_count": 23,
  "query_count_last_30d": 312,
  "token_count_last_30d": 412380,
  "ingest_job_count_pending": 0
}
```

### AsyncFileUploadAccepted

`202 Accepted` body from `POST /api/v1/datasets/{id}/files:async`:

```json
{
  "job_id": "01906f2c-...",
  "file_id": "01906f2b-...",
  "dataset_id": "01906f2a-...",
  "status": "PENDING"
}
```

`file_id` is final at this point (Stage 1 ran synchronously); poll
`GET /ingest-jobs/{job_id}` for pipeline status. Response carries a
`Location` header pointing at the ingest-job resource.

### PurgeAccepted

`202 Accepted` envelope for typed dataset/agent-token purge endpoints
(workspaces use a bare-dict response that is byte-equivalent with the
canon/radar lockstep controller — see
[`src/flyquery/interfaces/lifecycle.py`](../src/flyquery/interfaces/lifecycle.py)).

```json
{
  "status": "accepted",
  "tombstone_expires_at": "+90d"
}
```

`tombstone_expires_at` is documented as a human-readable hint today; a
future revision will return an ISO-8601 wall-clock timestamp once the
field is wired to a per-record value. The actual hard-delete happens
in the RetentionWorker after `dataset_purge_tombstone_days` (default
90d); see [workers.md](workers.md).

---

## 12. Generating schemas from code

The Pydantic models in `src/flyquery/interfaces/` can emit their JSON schemas
at any time:

```python
from flyquery.interfaces.workspaces import WorkspaceCreate
print(WorkspaceCreate.model_json_schema())

from flyquery.interfaces.queries import QueryRequest
print(QueryRequest.model_json_schema())
```

Or generate the full OpenAPI document:

```python
from flyquery.main import app
import json
print(json.dumps(app.openapi(), indent=2))
```

The committed `openapi.json` at the repo root is the authoritative snapshot.
Run `task openapi-snapshot` after any interface change to refresh it.
