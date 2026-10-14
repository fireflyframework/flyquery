<div align="center">

<img src="../../docs/assets/logo.png" alt="flyquery" width="100%" />

### **Python SDK** &nbsp;&middot;&nbsp; asyncio &nbsp;&middot;&nbsp; Python 3.9+

</div>

---

Async-first Python client for the
[flyquery](https://github.com/fireflyframework/flyquery) Tabular
Intelligence service — Text-to-SQL over user-uploaded structured
files.

- **Async-first**: every endpoint returns a coroutine; pairs naturally
  with `asyncio`, FastAPI, Starlette, Jupyter's top-level await, or
  any other event-loop host.
- **Pydantic v2-typed request + response models** — full
  IDE-completion + runtime validation on the wire payloads.
- **`aiohttp` under the hood** — pooled connections, retries
  (via `aiohttp-retry`), timeouts you control.
- Carries the firefly four-header wire contract
  (`X-Tenant-Id` / `X-Workspace-Id` / `X-Correlation-Id` /
  `X-Agent-Token`) on every outbound request.
- **18 split API classes** — one per resource family: workspaces,
  datasets, files, tables, schema, relations, semantic, glossary,
  examples, query, conversations, ingest, sql, agent-tokens, meta,
  agent-query, agent-sql, agent-examples.
- No service dependency — the SDK ships its own Pydantic schemas so
  it installs cleanly alongside any client codebase without pulling
  the framework.
- Apache-2.0; auto-generated from `flyquery/openapi.json` via
  [`openapi-generator-cli`](https://openapi-generator.tech/).

## Wire-contract compatibility

Compatible with **flyquery service version `26.5.x`**.

| SDK | Service |
|-----|---------|
| `26.5.4` | `26.5.x` |

## Install

```bash
uv add flyquery-sdk==26.5.4
# or
pip install flyquery-sdk==26.5.4
```

From a sibling-repo checkout (development):

```bash
pip install -e ./sdks/python
```

## Quick start

The SDK ships a hand-written ``FlyqueryClient`` ergonomic wrapper on
top of the generated API classes. It carries the tenant + workspace
context once, exposes bulk + batch helpers the raw OpenAPI client
can't model compactly, and returns the same Pydantic response
models so you keep full type safety.

```python
import asyncio
from flyquery_sdk import FlyqueryClient


async def main() -> None:
    async with FlyqueryClient(
        base_url="https://flyquery.example.com",
        tenant_id="acme-corp",
        workspace_id="finance",
    ) as fly:

        # 1) Idempotent workspace + dataset setup
        ws = await fly.find_or_create_workspace("finance", name="Finance")
        ds = await fly.find_or_create_dataset(
            "orders_2026",
            description="Order fact table + customer dimension.",
        )

        # 2) Upload a single file
        await fly.upload(ds.id, "examples/csv/sales_orders.csv")

        # 3) Or bulk-upload every supported file in a directory --
        #    runs through the same per-file pipeline in PARALLEL on
        #    the server side; per-file failures don't abort the bulk.
        outcome = await fly.upload_directory(ds.id, "examples/")
        print(f"uploaded {outcome.succeeded}/{outcome.total_files}")
        for r in outcome.results:
            print(f"  {r.original_filename}: {r.status} ({len(r.tables)} tables)")

        # 4) Ask one question
        ans = await fly.ask(ds.id, "What was last quarter's total revenue?")
        print(ans.sql)
        print(ans.preview)
        print(ans.explanation)

        # 5) Or ask many in parallel -- one batched HTTP round-trip,
        #    the server fans them out through asyncio.gather. Each
        #    result carries the same shape as ``ans`` above plus a
        #    ``status`` field that distinguishes OK from FAILED.
        batch = await fly.ask_batch(ds.id, [
            "Top 5 customers by revenue?",
            "Average order size by country?",
            "Refund rate this quarter?",
        ])
        for r in batch.results:
            print(f"#{r.index} {r.status}: {(r.sql or '')[:80]}")


asyncio.run(main())
```

### Bulk file upload

`upload_bulk` and `upload_directory` both call the bulk endpoint
``POST /api/v1/datasets/{id}/files:bulk``. The server processes each
file through the same reconcile → sample → profile → describe →
embed → publish pipeline in parallel and returns one
``BulkFileResult`` per file:

```python
result = await fly.upload_bulk(ds.id, [
    "examples/csv/customers.csv",
    "examples/csv/sales_orders.csv",
    "examples/json/products.json",
    "examples/parquet/transactions.parquet",
])
for r in result.results:
    if r.status == "OK":
        print(f"✓ {r.original_filename} -> file_id={r.file_id} ({len(r.tables)} tables)")
    else:
        print(f"✗ {r.original_filename}: {r.error}")
print(f"summary: {result.succeeded}/{result.total_files} succeeded")
```

### Batch NL queries

Mirror the bulk-file pattern for queries: send N questions, get
N answers back in roughly the time of one question. Each result
carries the same ``sql``, ``preview``, ``explanation``,
``execution_status``, and ``grounded_summary`` fields as the
single-query response.

### Sync helpers (notebooks + CLIs)

Every async method has a ``_sync`` mirror for notebook / CLI
contexts that can't bring up an event loop:

```python
fly = FlyqueryClient(base_url="...", tenant_id="...", workspace_id="...")
res = fly.upload_bulk_sync(dataset_id, paths)
ans = fly.ask_sync(dataset_id, "How many distinct customers?")
```

### Direct access to the generated API

For knobs ``FlyqueryClient`` doesn't expose (pagination beyond
``limit/offset``, custom timeouts on a per-call basis, agent-tier
endpoints), reach through to the generated API classes:

```python
async with FlyqueryClient(...) as fly:
    listing = await fly.workspaces.list_workspaces(q="acme", limit=20)
    raw = fly.api_client  # underlying ApiClient if you need it
```

## Authentication

The flyquery service expects either a user-tier JWT bearer token (on
`/api/v1/*` routes) or an agent-tier `X-Agent-Token` (on
`/api/v1/agent/*` routes). Wire them up on the `Configuration`:

```python
# User-tier (JWT)
config = Configuration(
    host="https://flyquery.example.com",
    access_token="eyJhbGciOiJSUzI1NiIs...",
)

# Agent-tier (long-lived token, agt_<8hex>_<32hex>)
config = Configuration(
    host="https://flyquery.example.com",
    api_key={"X-Agent-Token": "agt_aabbccdd_eeff00112233445566778899aabbccddeeff"},
)
```

Every request **must** carry `X-Tenant-Id` and `X-Workspace-Id`
header parameters — the service uses them to bind the
request-scoped RLS GUCs. They're explicit on every API method;
see the per-method signatures.

For agent-tier write endpoints (uploads, derives, mutations), pass
an `Idempotency-Key` via the `idempotency_key` kwarg — the service
deduplicates on the (token-prefix, key) pair for 24 hours.

## Streaming endpoints (SSE)

`/query/stream` and `/ingest-jobs/{id}/stream` are
Server-Sent Events. The generated method returns a streaming
response you iterate per-line:

```python
async with query.post_query_stream_with_http_info(
    QueryRequest(dataset_id=ds.id, question="how many orders per region?"),
    x_tenant_id="demo", x_workspace_id=ws.id,
) as resp:
    async for line in resp.content:
        decoded = line.decode("utf-8").strip()
        if decoded.startswith("event:"):
            print("stage:", decoded[len("event:"):].strip())
```

The event sequence is documented in
[`docs/pipeline.md`](https://github.com/fireflyframework/flyquery/blob/main/docs/pipeline.md):
`schema_linked → sql_generated → executed → explained → final`,
with an optional `clarification` frame when Grounding confidence is
below threshold.

## Error handling

All API methods raise `flyquery_sdk.ApiException` on non-2xx
responses. The service emits
[RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) ProblemDetails;
parse `ApiException.body` (or `.data` for typed responses) to access
the `code`, `title`, `detail`, and per-field `errors[]`.

```python
from flyquery_sdk.exceptions import ApiException

try:
    await workspaces.create_workspace(...)
except ApiException as exc:
    if exc.status == 409:
        # Workspace slug already exists for this tenant
        ...
    elif exc.status == 403:
        # Missing scope / dataset not in token allowlist
        ...
    else:
        raise
```

Common error codes:

| Status | `code`                    | Meaning                                            |
|--------|---------------------------|----------------------------------------------------|
| 400    | `validation_error`        | Request body failed Pydantic validation            |
| 401    | `unauthenticated`         | Missing/invalid token                              |
| 403    | `scope_denied`            | Token scope insufficient for this operation        |
| 404    | `resource_not_found`      | Dataset / table / workspace not visible under RLS  |
| 409    | `conflict`                | Slug / name collision (per workspace)              |
| 413    | `file_too_large`          | Upload exceeds `FLYQUERY_MAX_FILE_MB`              |
| 507    | `workspace_quota_exceeded`| Workspace storage cap reached                      |
| 503    | `rate_limited`            | Per-token rate limit exceeded                      |

## API reference

The 18 API classes mirror the resource families exposed by the
service. Per-family methods cover the endpoints documented in
[`docs/api-reference.md`](https://github.com/fireflyframework/flyquery/blob/main/docs/api-reference.md).

| API class                | Resource family                  |
|--------------------------|----------------------------------|
| `WorkspacesApi`          | `/api/v1/workspaces`             |
| `DatasetsApi`            | `/api/v1/datasets`               |
| `FilesApi`               | `/api/v1/datasets/{id}/files`    |
| `TablesApi`              | `/api/v1/tables`                 |
| `SchemaApi`              | `/api/v1/schema-objects`         |
| `RelationsApi`           | `/api/v1/datasets/{id}/relations`|
| `SemanticApi`            | `/api/v1/semantic/*`             |
| `GlossaryApi`            | `/api/v1/glossary`               |
| `ExamplesApi`            | `/api/v1/examples`               |
| `QueryApi`               | `/api/v1/query/*`                |
| `ConversationsApi`       | `/api/v1/conversations`          |
| `IngestApi`              | `/api/v1/ingest-jobs`            |
| `SqlApi`                 | `/api/v1/sql:execute`            |
| `AgentTokensApi`         | `/api/v1/agent-tokens`           |
| `MetaApi`                | `/actuator/health`, `/version`   |
| `AgentQueryApi`          | `/api/v1/agent/query/*`          |
| `AgentSqlApi`            | `/api/v1/agent/sql:execute`      |
| `AgentExamplesApi`       | `/api/v1/agent/examples`         |

## Regenerating

The SDK is auto-generated from the service's OpenAPI spec. To pull
the latest:

```bash
# From the flyquery repo root:
task openapi-snapshot   # writes openapi.json
task sdk:python         # regenerates this directory
```

Hand-written files (`README.md`, `pyproject.toml`) are preserved
across regeneration via `.openapi-generator-ignore`.

## Development

```bash
cd sdks/python
uv venv
uv pip install -e ".[dev]"
pytest tests/         # smoke tests
mypy flyquery_sdk     # type-check
```

## License

Apache-2.0. See [LICENSE](LICENSE).

The upstream **flyquery service** is also released under the Apache
License 2.0; the SDK is the Apache-licensed wire-protocol client.

## Links

- Service repo: <https://github.com/fireflyframework/flyquery>
- Documentation index: [`docs/README.md`](https://github.com/fireflyframework/flyquery/blob/main/docs/README.md)
- API reference: [`docs/api-reference.md`](https://github.com/fireflyframework/flyquery/blob/main/docs/api-reference.md)
- Wire payloads: [`docs/payload-reference.md`](https://github.com/fireflyframework/flyquery/blob/main/docs/payload-reference.md)
- Changelog: [`CHANGELOG.md`](https://github.com/fireflyframework/flyquery/blob/main/CHANGELOG.md)
