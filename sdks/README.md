<div align="center">

<img src="../docs/assets/brand/banner-light.svg" alt="flyquery" width="100%" />

### **SDKs**

</div>

---

Wire-protocol clients for the
[flyquery](https://github.com/fireflyframework/flyquery) Tabular
Intelligence service. Both SDKs are auto-generated from the
service's [`openapi.json`](../openapi.json) committed snapshot via
[`openapi-generator-cli`](https://openapi-generator.tech/) and ship
under **Apache-2.0** — the same license as the upstream service.

Each SDK exposes **18 split API classes**, one per resource family
(workspaces, datasets, files, tables, schema, relations, semantic,
glossary, examples, query, conversations, ingest, sql, agent-tokens,
meta, agent-query, agent-sql, agent-examples), and carries the
firefly four-header wire contract
(`X-Tenant-Id` / `X-Workspace-Id` / `X-Correlation-Id` /
`X-Agent-Token`) on every outbound request.

| | Python SDK | Java SDK |
|---|---|---|
| **Path** | [`sdks/python/`](./python/) | [`sdks/java/`](./java/) |
| **Coordinates** | `flyquery-sdk` on PyPI | `com.firefly:flyquery-sdk` (Maven) |
| **Latest version** | `26.5.12` | `26.5.12` |
| **Runtime** | Python 3.9+ | Java 25 (LTS) + Spring Boot 3.5.9 |
| **HTTP client** | `aiohttp` + `aiohttp-retry` (asyncio) | Spring WebFlux `WebClient` + Reactor Netty (reactive) |
| **Model layer** | Pydantic v2 | Jackson |
| **Streaming** | `async for` over `aiohttp` response body | `Flux<ServerSentEvent>` |
| **Wire-contract compat** | flyquery `26.5.x` | flyquery `26.5.x` |
| **License** | Apache-2.0 | Apache-2.0 |
| **README** | [Python README](./python/README.md) | [Java README](./java/README.md) |

## Install

**Python**

```bash
uv add flyquery-sdk==26.5.12
# or: pip install flyquery-sdk==26.5.12
```

**Java (Maven)**

```xml
<dependency>
    <groupId>com.firefly</groupId>
    <artifactId>flyquery-sdk</artifactId>
    <version>26.5.12</version>
</dependency>
```

## Regenerate

Both SDKs regenerate from `openapi.json`. From the repo root:

```bash
task openapi-snapshot   # refresh openapi.json from the running app definition
task sdk:python         # regenerate sdks/python/
task sdk:java           # regenerate sdks/java/
```

Hand-curated files (`README.md`, `pyproject.toml`, `pom.xml`) are
preserved across regeneration via each SDK's
`.openapi-generator-ignore`.

## Wire-contract compatibility

Compatible with **flyquery service version `26.5.x`**. The
service's [`tests/integration/test_openapi_snapshot.py`](../tests/integration/test_openapi_snapshot.py)
drift gate fails the build if a route is added without a matching
`openapi.json` regeneration, so the SDKs never lag the service for
long.

## Publishing

Both SDKs publish on tag (`v*`) via the dedicated workflows:

- [`.github/workflows/publish-sdk-python.yml`](../.github/workflows/publish-sdk-python.yml)
- [`.github/workflows/publish-sdk-java.yml`](../.github/workflows/publish-sdk-java.yml)

See [`docs/cicd.md`](../docs/cicd.md) for the full release flow.
