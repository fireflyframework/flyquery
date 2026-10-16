# SDKs

flyquery provides Python and Java clients generated from the release's
[OpenAPI snapshot](../openapi.json). Both include typed resource APIs and a
handwritten convenience client for common operations.

| Client | Runtime | Distribution | Guide |
|---|---|---|---|
| `flyquery_sdk` | Python 3.9+, asyncio | Wheel and source distribution on GitHub Releases | [Python SDK](../sdks/python/README.md) |
| `flyquery-sdk` | Java 25, Spring WebFlux | GitHub Packages; release JAR assets | [Java SDK](../sdks/java/README.md) |

The Python SDK installs independently of the server. Import its convenience
client with `from flyquery_sdk.client import FlyqueryClient`. Generated classes
are available through `flyquery_sdk.api` and models through `flyquery_sdk.models`.
The Java convenience client is
[`com.firefly.flyquery.FlyqueryClient`](../sdks/java/src/main/java/com/firefly/flyquery/FlyqueryClient.java).

## Installation and versions

Install the Python wheel from the canonical GitHub Release, rather than assuming
that a package with the same name on PyPI is maintained by this project:

```bash
uv add https://github.com/fireflyframework/flyquery/releases/download/v26.10.3/flyquery_sdk-26.10.3-py3-none-any.whl
```

Keep service and client versions aligned. The published release above is
`26.10.3`; this source prepares `26.10.4`, whose publication and native acceptance
are pending. Read the release notes and API snapshot before upgrading. The
repository retains earlier releases and their original assets.

## Scope and authentication

User APIs require `x_tenant_id` and `x_workspace_id` parameters. The convenience
client supplies them for its own methods. Generated method calls require those
arguments explicitly, even if default headers have been configured. Use a
workspace UUID for dataset operations; keep a separate client per scope instead
of changing private client fields.

Scope headers select the tenant and workspace. Configure authentication at the
deployment boundary and use bearer credentials for routes that require them.
Generated agent APIs call `/api/v1/agent/*` with an issued `x_agent_token`; the
token's permissions constrain the operation. Adding an agent-token header to a
user-route helper does not change which route it calls. The
[security model](security-model.md) explains token issuance and permissions.

Table reads report a current snapshot only when it belongs to the same table,
dataset, tenant and workspace. If the retained pointer is missing or does not
resolve within that scope, `current_snapshot_id` and `n_columns` are `null`.
This means the current snapshot is unavailable through this read; it does not
repair the stored pointer or establish that no snapshot exists. A valid snapshot
with zero columns still reports its ID and `n_columns: 0`.

Lookup-or-create helpers fall back to creation only after a 404. Other errors
propagate, and a concurrent creator can return a 409. For mutating operations,
use the API's idempotency-key mechanism where appropriate.

## Operations

### Bounded agent reads in candidate 26.10.4

`flyquery_sdk.agent_read_client.AgentReadClient` provides four GET-only methods:
`get_dataset()`, `list_tables()`, `get_table(table_id)` and
`get_object(table_id, object_id)`. This addition is not in the published 26.10.3
SDK. Use the qualified 26.10.4 candidate source with a compatible service until
its release is published.

The client fixes one tenant, workspace and dataset at construction. Supply an
issued agent token with `flyquery.datasets:read` and `flyquery.schema:read` as
needed. The methods call only `/api/v1/agent/*`; there is no user-tier credential
fallback. Every returned record must match the configured scope. An object also
must match its requested parent table and the snapshot observed in that parent
read. Missing or mismatched scope refuses the whole response, including a mixed
catalog page.

HTTPS, no redirects, no retries and no environment proxies apply independently.
The default operation deadline is 10 seconds, including both GETs for an object;
the maximum configurable deadline is 30 seconds. Responses default to 256 KiB,
with an upper bound of 1 MiB, and catalogs allow at most 100 items. A larger
catalog is refused rather than silently truncated. The catalog route is a full
list: declared `has_more: true`, a nonzero offset, or a total different from the
item count refuses the response. Missing or null pagination metadata is accepted
for compatibility with the full-list endpoint. The default transport pool allows
at most four connections and two idle keepalive connections. Errors and 404 never trigger
a write, a new query or another provider. Returned content containing this
client's agent token is refused without reflecting it in the exception.

These records are reported observations, not an atomic snapshot across GETs or
an authorization guarantee beyond the service's actual token checks. Snapshot
history DTOs omit some scope fields; this client does not expose that history.
Agent GET routes for prepared query results do not exist yet, so this client
offers no query-result, natural-language, SQL, upload, export or execution method.
The existing `FlyqueryClient` and generated APIs keep their current contracts.

| Operation | Python entry point |
|---|---|
| Workspace and dataset setup | `find_or_create_workspace`, `find_or_create_dataset` |
| File and directory uploads | `upload`, `upload_bulk`, `upload_directory` |
| Natural-language questions | `ask`, `ask_batch`; generated `QueryApi` or `AgentQueryApi` |
| Direct SQL against registered tables | `SqlExecuteApi`, `AgentSqlExecuteApi` |
| Schemas and metadata | Generated `SchemaObjectsApi`, `SchemaChangesApi`, semantic and relation APIs |
| Execution history and result downloads | `recent_queries`, `get_query`, `fetch_query_result` |
| Audit, cost and workspace statistics | Generated resource APIs and convenience methods |
| Streaming events | Generated `*_without_preload_content` methods; release the underlying response afterward |

Bulk uploads and batch queries return per-item outcomes. Inspect those outcomes
in addition to the HTTP status. Natural-language questions and ingestion stages
can use configured model providers; direct SQL skips the question-generation
pipeline and requires `allow_direct_sql` on the workspace.

Python generated calls raise `ApiException`; HTTPX-backed convenience methods
raise HTTPX transport or status exceptions. The Python guide gives examples for
both. Its constructor timeout applies to HTTPX helpers; generated calls accept
`_request_timeout`. A client timeout does not establish server-side execution
cancellation or an operating system sandbox.

## Regeneration and checks

```bash
uv run python scripts/openapi_snapshot.py
task sdk:python
task sdk:java
```

The Python generator ignore file preserves the handwritten client, documentation,
examples and test directory. Release metadata is kept in lockstep with the server
and generator settings. PR CI runs the SDK's import and real-loopback HTTP tests;
SDK publication also runs those tests before building the wheel and source
archive. Service integration tests require their own databases and object store.

See the [Python examples](../sdks/python/examples/README.md),
[Java guide](../sdks/java/README.md) and [consumer recipes](consumers.md).
