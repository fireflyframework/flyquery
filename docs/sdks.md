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

Keep service and client versions aligned. This release uses version `26.10.3`;
read the release notes and API snapshot before upgrading. The repository also
retains earlier releases and their original assets.

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

Lookup-or-create helpers fall back to creation only after a 404. Other errors
propagate, and a concurrent creator can return a 409. For mutating operations,
use the API's idempotency-key mechanism where appropriate.

## Operations

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
