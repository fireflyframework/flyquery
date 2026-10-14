# Release runbook

How to ship a new flyquery release. The flow is fully automated --
push a tag, watch CI -- but the local pre-flight is worth running
once so an obvious break doesn't make it past the merge.

## TL;DR

```bash
# Pre-flight (5 min)
task openapi-snapshot
task lint
task test:unit
uv run python scripts/check_lockstep.py
cd sdks/python && uv build && cd ../..      # smoke
cd sdks/java && mvn -B -q -DskipTests package && cd ../..

# Ship
git add -A
git commit -m "release: vYY.MM.PP"
git push origin main
git tag vYY.MM.PP   # e.g. v26.5.10
git push --tags
```

The tag push fans out to two workflows:
1. `docker-publish.yaml` -- multi-arch image to GHCR.
2. `publish-sdks.yaml` -- Java to GitHub Packages, Python wheel +
   sdist to the GitHub Release page.

## Pre-flight checklist (the load-bearing parts)

### 1. Version sync

Every artifact must read the same CalVer string. The five places
that hold a version literal:

| File | Pattern |
|---|---|
| `pyproject.toml` | `version = "26.5.10"` |
| `pyfly.yaml` | `pyfly.app.version: 26.5.10` |
| `sdks/python/pyproject.toml` | `version = "26.5.10"` |
| `sdks/java/pom.xml` | `<version>26.5.10</version>` |
| `Taskfile.yml` | `packageVersion=26.5.10` + `artifactVersion=26.5.10` (two occurrences) |
| `README.md` | `version-26.5.10-green` badge URL |

Note: `publish-sdks.yaml` *also* rewrites the SDK versions from the
git tag at publish time, so a forgotten local bump will not produce
a wrong-version published artifact -- but the local SDK builds in
CI's `sdk-python` / `sdk-java` jobs would still produce a 26.5.9
wheel against a 26.5.10 spec, which is confusing in the build logs.
**Bump everything locally.**

### 2. OpenAPI snapshot

The on-disk `openapi.json` is the source of truth that both SDK
generators consume. Re-snapshot after every controller change:

```bash
task openapi-snapshot
```

The drift gate at `tests/integration/test_openapi_snapshot.py` will
fail CI if you forget.

### Reproducible server dependencies

The server now tracks `uv.lock`. Earlier releases resolved dependencies again
on CI and image builds; those builds could select different transitive versions.
CI and Docker first run `uv lock --check`, then `uv sync --frozen`. The check
rejects a stale project manifest before the frozen install; `--frozen` alone
would not check whether the manifest changed.

The graph uses the public Agentic 26.10.1 wheel and retains the qualified
pyfly 26.06.113 tag. Update dependencies with the normal resolver, review the
lock diff, and rerun the native gates. Do not publish local candidate paths or
replace conflicts with dependency overrides. SDK development locks remain local.

Native query execution and nonempty-candidate selection do not establish that
an answer matches the user's intended entities or filters. Candidate selection
is a heuristic; these safety and dependency checks do not close semantic query
QA or the handling of unmatched literals.

### 3. Lockstep

The gate preserves nineteen normalized historical shared-baseline hashes
and two reviewed service-specific full-file hashes. It validates local
contracts rather than comparing current canon/radar source:

```bash
uv run python scripts/check_lockstep.py
```

If this fails, review the source change and its behavior before changing any
pin. The variant manifest permits only the agent builder and observability
module, with a reason and canonical source provenance. It cannot exempt an
authentication file. See [architecture](architecture.md#9-lock-step-modules).

### 4. SDK regen + builds

```bash
task sdk:python   # rebuild Python SDK
task sdk:java     # rebuild Java SDK
cd sdks/python && uv build && cd ../..
cd sdks/java && mvn -B -q -DskipTests package && cd ../..
```

The Python smoke tests (`sdks/python/tests/test_smoke.py`) cover:
- Every API class imports.
- No stale split-tag classes leak (regression for v26.5.4 where the
  generator left zombie `IngestApi` / `SchemaApi` after the spec
  split).
- `FlyqueryClient` exposes every v1 accessor.

The Java SDK test (`FlyqueryClientTest.java`) covers builder +
sibling-client behaviour + every accessor.

### 5. The CI gates the tag will run

| Workflow | Trigger | Jobs |
|---|---|---|
| `pr-gate.yaml` | every PR + push to main | lint, typecheck (advisory), unit, integration (testcontainers Postgres+Redis+MinIO), lockstep, sdk-python, sdk-java |
| `docker-publish.yaml` | push to main + `v*.*.*` tags | linux/amd64 + linux/arm64 image to GHCR |
| `publish-sdks.yaml` | `v*.*.*` tags only | Java to GitHub Packages, Python wheel/sdist to Release assets |

Green PR checks qualify the source. Publication can still fail on registry
authentication, downloads or packaging; verify the tag workflows and every
published artifact separately before announcing the release.

## Tag + push sequence

```bash
# Final commit
git add -A
git status                       # eyeball
git commit -m "release: v26.5.10

- v1 history/billing/stats endpoints
- RetentionWorker (TTL sweep + stuck-job reaper)
- Worker CLI (ingest|retention|all)
- 21 new tests (311 total)
- Schema-detection + workers docs
- SDK helpers for every v1 endpoint
"

# Push the branch
git push origin main

# Tag the release
git tag -a v26.5.10 -m "v26.5.10: v1 endpoints + RetentionWorker + worker CLI"
git push origin v26.5.10
```

Watch the three workflows on GitHub Actions. Total wall-clock:
~7-10 minutes (integration tests are the longest job at ~5 min).

## Post-release sanity

```bash
# Image is multi-arch -- pull on Apple Silicon + amd64 staging
docker pull ghcr.io/firefly-operationos/flyquery:v26.5.10
docker run --rm ghcr.io/firefly-operationos/flyquery:v26.5.10 flyquery version

# Python SDK from Release asset
uv add https://github.com/fireflyframework/flyquery/releases/download/v26.5.10/flyquery_sdk-26.5.10-py3-none-any.whl

# Java SDK from GitHub Packages
# (settings.xml must have the firefly-operationOS GitHub Packages repo)
mvn dependency:get -Dartifact=com.firefly:flyquery-sdk:26.5.10
```

## Rollback

The deploy is image + SDK -- no in-flight DB migration assumed
(if there's a new Alembic revision, that runs at boot via
`docker-entrypoint.sh`).

To roll back:
1. Re-tag the previous release: `docker tag :v26.5.9 :latest && push`
2. SDK consumers pin to the previous version explicitly (we never
   delete published artifacts).

The migrations chain is forward-compatible by construction
(`migrations/versions/*` is linear; downgrades exist for every
revision).

## Things to verify post-tag

- [ ] `pr-gate` green on main (must run BEFORE the tag push triggers
      `docker-publish` + `publish-sdks`)
- [ ] `docker-publish` produced both arch manifests
- [ ] `publish-sdks` Java job published to GitHub Packages
- [ ] `publish-sdks` Python job uploaded wheel + sdist to the Release
- [ ] GitHub Release page shows the auto-generated notes
- [ ] CHANGELOG.md `[X.Y.Z]` section matches what shipped

## Repository and package namespaces

See [branding.md](branding.md#package-registries) for the canonical source
URLs and the publication checks required before using the new package namespace.
