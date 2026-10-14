# flyquery — CI/CD

## Table of Contents

1. [Overview](#1-overview)
2. [Workflow: PR gate](#2-workflow-pr-gate)
3. [Workflow: Docker publish](#3-workflow-docker-publish)
4. [Workflow: SDK publish](#4-workflow-sdk-publish)
5. [Workflow: Lock-step check](#5-workflow-lock-step-check)
6. [Tag-triggered releases](#6-tag-triggered-releases)
7. [Branch protection recommendations](#7-branch-protection-recommendations)
8. [Concurrent worker considerations](#8-concurrent-worker-considerations)
9. [Required secrets](#9-required-secrets)

---

## 1. Overview

flyquery's CI mirrors flycanon's workflow structure:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-gate` | Every PR + push to main | lint, test-unit, test-integration, openapi-drift |
| `docker-publish` | Tag `v*.*.*` | Build + push Docker image to GHCR |
| `publish-sdk-python` | Tag `v*.*.*` | Generate + publish `flyquery-sdk` to PyPI |
| `publish-sdk-java` | Tag `v*.*.*` | Generate + publish `io.firefly:flyquery-sdk` to Maven |
| `lockstep-check` | Every PR + push to main | Diff lock-step modules against canon/radar SHAs |

All workflows use `uv` for Python dependency management. The `uv.lock` file
is gitignored (per `project_uv_lock_gitignored` memory); CI uses `uv sync`
(not `--frozen`).

---

## 2. Workflow: PR gate

Runs on every pull request and push to `main`.

```yaml
# .github/workflows/pr-gate.yml (structure)

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check src/ tests/
      - run: uv run mypy src/flyquery/

  test-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest tests/unit/ -m 'not llm and not integration' --tb=short -q

  test-integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: ci
        options: --health-cmd pg_isready
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest tests/integration/ -m 'not llm and not s3 and not gcs and not azure_blob' --tb=short -q
        env:
          FLYQUERY_DATABASE_URL: postgresql+asyncpg://postgres:ci@localhost:5432/flyquery

  openapi-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: task openapi-snapshot
      - run: git diff --exit-code openapi.json || (echo "openapi.json drifted"; exit 1)
```

### Test counts (26.5.10)

- 311 tests in `tests/` (up from 258 in 26.5.4 -- +21 added in 26.5.10
  and the rest landed across the 26.5.5 -> 26.5.9 patches).
- New tests in 26.5.10 worth flagging:
  - [`tests/unit/test_retention_worker.py`](../tests/unit/test_retention_worker.py)
    (9 tests) -- happy paths, TTL=0 short-circuits, per-step failure
    isolation, publisher-blip isolation, cooperative shutdown.
  - [`tests/unit/test_ingest_worker_concurrency.py`](../tests/unit/test_ingest_worker_concurrency.py)
    (4 tests) -- semaphore cap enforcement under burst, timed-out
    handler isolation, drain wait, drain-with-cancel (catches the
    `_drain_inflight` `with asyncio.timeout(...)` bug, see
    [concurrency.md](concurrency.md)).
  - [`tests/unit/test_v1_endpoints.py`](../tests/unit/test_v1_endpoints.py)
    (8 tests) -- DTO mapping, `QueryRepository.list_queries` limit
    clamping, `BillingService` period validation, presigned-URL TTL
    guard.
- [`tests/unit/test_no_raw_sql_in_controllers.py`](../tests/unit/test_no_raw_sql_in_controllers.py)
  is a structural CI gate -- it scans every controller for raw SQL
  string literals and fails the build if any leak in (controllers must
  go through repository methods).

### Test marks

| Mark | Excluded in CI by default | When to include |
|------|--------------------------|----------------|
| `llm` | Yes | Only in nightly LLM-gated runs (requires API keys) |
| `integration` | No (runs in PR gate) | Requires `pgvector` service |
| `s3` | Yes | Requires MinIO or AWS credentials |
| `gcs` | Yes | Requires fake-gcs-server or GCP credentials |
| `azure_blob` | Yes | Requires Azurite or Azure credentials |

---

## 3. Workflow: Docker publish

Triggered on tags matching `v*.*.*` (CalVer: `v26.5.3`).

```yaml
# .github/workflows/docker-publish.yml (structure)

on:
  push:
    tags: ['v*.*.*']

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/fireflyframework/flyquery:${{ github.ref_name }}
            ghcr.io/fireflyframework/flyquery:latest
```

The `Dockerfile` uses a multi-stage build:
1. `builder` — installs Python deps via `uv sync`.
2. `runtime` — minimal image; copies only the installed packages.
3. `docker-entrypoint.sh` handles `RUN_MIGRATIONS=true` at boot.

---

## 4. Workflow: SDK publish

Both SDK publish workflows are tag-triggered and depend on the OpenAPI spec.

### Python SDK

```yaml
# .github/workflows/publish-sdk-python.yml (structure)

on:
  push:
    tags: ['v*.*.*']

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          # Generate from committed openapi.json
          docker run --rm -v $(pwd):/out openapitools/openapi-generator-cli generate \
            -i /out/openapi.json -g python -o /out/sdks/python \
            --additional-properties=packageName=flyquery_sdk,packageVersion=$TAG
      - run: cd sdks/python && pip install build && python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: sdks/python/dist/
```

Package: `flyquery-sdk` on PyPI. Apache-2.0 license.

### Java SDK

```yaml
# .github/workflows/publish-sdk-java.yml (structure)

on:
  push:
    tags: ['v*.*.*']

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: '25'
          distribution: 'temurin'
      - run: |
          docker run --rm -v $(pwd):/out openapitools/openapi-generator-cli generate \
            -i /out/openapi.json -g java -o /out/sdks/java \
            --additional-properties=groupId=io.firefly,artifactId=flyquery-sdk
      - run: cd sdks/java && mvn deploy -DskipTests
        env:
          MAVEN_USERNAME: ${{ secrets.MAVEN_USERNAME }}
          MAVEN_PASSWORD: ${{ secrets.MAVEN_PASSWORD }}
```

Package: `io.firefly:flyquery-sdk` on the Firefly Maven registry.
Apache-2.0 license.

---

## 5. Workflow: Lock-step check

Runs on every PR and push to `main`. Blocks if any lock-step module in flyquery
has drifted from its pinned SHA in flycanon or flyradar.

```yaml
# .github/workflows/lockstep-check.yml (structure)

jobs:
  lockstep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: uv run python scripts/check_lockstep.py
        env:
          FLYCANON_REF: ${{ vars.FLYCANON_PINNED_SHA }}
          FLYRADAR_REF: ${{ vars.FLYRADAR_PINNED_SHA }}
```

The script checks:
1. Fetches the pinned SHA of flycanon and flyradar from GitHub vars.
2. Downloads the lock-step files from those SHAs.
3. Diffs byte-by-byte against flyquery's copies.
4. Exits non-zero if any file drifts.

Fixing a lock-step drift: see
[troubleshooting.md § 12](troubleshooting.md#12-lock-step-drift-ci-failure).

---

## 6. Tag-triggered releases

flyquery uses CalVer (YY.MM.Patch). See the `firefly_uses_calver` memory.

```
26.5.2 → current release
26.5.3 → next patch (docs completion, CHANGELOG update)
26.6.0 → June 2026 first release
```

### Release steps

```bash
# 1. Update CHANGELOG.md with new section
# 2. Bump version in pyproject.toml
sed -i 's/version = "26.5.2"/version = "26.5.3"/' pyproject.toml

# 3. Update README.md badge
# 4. Commit
git add CHANGELOG.md pyproject.toml README.md
git commit -m "release: 26.5.3"

# 5. Tag (triggers docker-publish + SDK publish workflows)
git tag v26.5.3
git push origin main v26.5.3
```

### CHANGELOG format

Follow Keep a Changelog (keepachangelog.com). Sections: Added, Changed,
Fixed, Deprecated, Removed, Security.

---

## 7. Branch protection recommendations

For the `main` branch:

| Rule | Recommended setting |
|------|-------------------|
| Require PR before merging | Yes |
| Required status checks | `lint`, `test-unit`, `test-integration`, `openapi-drift`, `lockstep-check` |
| Require branches to be up to date | Yes |
| Require linear history | Yes (no merge commits) |
| Restrict force pushes | Yes |
| Require signed commits | Yes (optional; CalVer convention implies GPG or vigilant mode) |

---

## 8. Concurrent worker considerations

### CI test isolation

Integration tests spin up a testcontainers `pgvector/pgvector:pg16` instance
per test session. Each session gets its own database. Tests that validate RLS
must create a non-superuser `flyquery_app` role inside the container (see
[security-model.md § 3](security-model.md#3-postgres-role-split-and-rls)).

### Parallel test jobs

Running `test-unit` and `test-integration` in parallel is safe. They use
separate databases (unit: in-memory SQLite; integration: testcontainers
Postgres).

Do NOT run multiple integration test jobs against the same Postgres instance —
schema migrations and data fixtures are not isolated across parallel sessions
on a shared database.

### DuckDB in CI

DuckDB runs in-process; no CI service required. The default
`FLYQUERY_DUCKDB_MEMORY_LIMIT` of 4 GB may need to be lowered for CI runners
with limited RAM:

```yaml
env:
  FLYQUERY_DUCKDB_MEMORY_LIMIT: "512MB"   # CI runner constraint
```

---

## 9. Required secrets

| Secret / Var | Where used | Notes |
|-------------|-----------|-------|
| `GITHUB_TOKEN` | Docker publish | Auto-provided by GitHub |
| `ANTHROPIC_API_KEY` | LLM-gated tests | Optional; only for `@pytest.mark.llm` |
| `OPENAI_API_KEY` | Embedding tests + fallback model | Optional; only for embedding + llm marks |
| `MAVEN_USERNAME` / `MAVEN_PASSWORD` | Java SDK publish | Firefly Maven registry credentials |
| `PYPI_TOKEN` | Python SDK publish | PyPI API token |
| `FLYCANON_PINNED_SHA` | Lock-step check | GitHub Actions variable (not secret) |
| `FLYRADAR_PINNED_SHA` | Lock-step check | GitHub Actions variable (not secret) |

Secrets are stored in GitHub repository settings → Secrets and variables.
`FLYCANON_PINNED_SHA` and `FLYRADAR_PINNED_SHA` are Variables (not secrets;
they don't need encryption).

## Repository and package namespaces

See [branding.md](branding.md#package-registries) for the canonical source
URLs and the publication checks required before using the new package namespace.
