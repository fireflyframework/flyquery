# Changelog

All notable changes to flyquery are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [CalVer](https://calver.org/) (YY.MM.PP) per the
Firefly Framework convention (memory: `firefly_uses_calver`).

## [26.10.2] - 2026-10-14

### Changed

- Use the public fireflyframework-agentic 26.10.1 wheel with the qualified
  pyfly 26.06.113 runtime. Track the server dependency lock and validate it
  before frozen CI and image installs.
- Apply `FLYQUERY_PROMPT_CACHE` when constructing agents. Enabled mode adds
  Anthropic instruction-cache hints; disabled mode omits this middleware.
  User messages, tool results and generated answers are not memoized.
- Ground queries with bounded value catalogs, scoped relation candidates and
  persisted conversation snapshot pins. Candidate execution probes pass the
  registered-table fence and a bounded result limit before candidate selection.
- Keep nineteen historical shared-source baselines and two explicitly reviewed
  service variants under source-drift checks.

### Fixed

- Reject missing or unauthorized dataset scope before retrieval or model calls,
  recording a caller-scoped rejected audit row without reading dataset metadata.
- Classify original samples before filtering them, and inspect retained profile
  values before embedding. Redact/reject stores an explicit empty-list denial
  so profiles cannot reintroduce protected values into schema knowledge.
- Exclude inactive columns from catalog and retrieval projections. Preserve
  original Parquet files and conversation snapshot selections.
- Refresh the OpenAPI Decimal schemas for the resolved Pydantic runtime and
  align server, actuator, Python and Java SDK release metadata.

A nonempty executed candidate is a selection heuristic, not proof that the SQL
matches the requested entities or filters. The engine does not enforce its
statement-timeout setting or provide an operating system sandbox. Deployment
resource limits do not implement that missing query deadline. Remote object-store
DuckDB reads are not qualified by the local registered-file tests. PII detection
covers sampled and retained profile values; it is not a scan of every source row.

## [26.6.0] - 2026-06-01

### Fixed — Semantic layer brought up to its documented contract

- **The `SEMANTIC_LAYER` fast-path now actually executes.** A published metric's
  compiled SQL is fetched (`SemanticRepository.get_by_name`, tenant+workspace
  scoped), bound via `SemanticCompiler.bind`, and run straight through the AST
  firewall + executor with **no GenerationAgent** — the metric name + version are
  pinned in the query record. Previously the branch silently fell through to the
  LLM because `semantic_repo` was never wired and `get_by_name` did not exist.

### Added

- Nested MetricFlow YAML schema (`metric:` / `dimension:` roots) replacing the
  flat schema; all four metric types (`SIMPLE`, `RATIO`, `DERIVED`, `CUMULATIVE`)
  compile to DuckDB SQL templates with `{extra_filter_clause}` / `{group_by_append}`
  runtime slots filled by `SemanticCompiler.bind`. `count_distinct` is supported.
- Publish-time **sqlglot firewall**: single-SELECT, no DDL/commands/multi-statement,
  no subqueries, anonymous-function allowlist, identifier regex — invalid/unsafe
  definitions return RFC 7807 `400 semantic_compile_error`.
- Real dimensions: own `categorical|time` validator + compiler (grain-aware
  `DATE_TRUNC`); metric `group_by` resolves published dimension names.
- Agent-tier mirrors: `/api/v1/agent/semantic/metrics`, `/api/v1/agent/semantic/dimensions`,
  `/api/v1/agent/glossary` (scopes `flyquery.semantic:author` / `:read`).
- `metadata_json` column on metrics + dimensions (migration `0014`); glossary
  DTOs accept the documented `synonyms` / `related_metrics` keys; glossary
  `related_metrics` surfaced to grounding for SEMANTIC_LAYER routing.

### Changed

- Version rows persist `compiled_sql_template` (no longer NULL); `publish` records
  it on the current version; `update` of a published metric recompiles + re-firewalls.
- Semantic repos/services are tenant+workspace scoped (defense-in-depth over RLS);
  metrics/dimensions `list` gains a `status` filter; `SemanticVersionRead` exposes
  doc-aligned `version_number` / `metric_id`.

## [26.5.14] - 2026-05-31

### Changed

- **Open-sourced under the Apache License 2.0.** Replaced the proprietary
  notice with the full Apache 2.0 `LICENSE` (root + both SDKs) and prepended
  the Apache 2.0 header to every source file. The copyright holder is now
  Firefly Software Foundation, and the repository is public.
- Set the OpenAPI `info.license`, the image `licenses` label, the README
  badge, the bundled SDK spec/`setup.py`, and `pyproject` metadata to Apache-2.0.
- Realigned `__version__` with the packaged release version; refreshed the
  lock-step SHA pins after the header changes.

## [26.5.13] - 2026-05-31

### Changed — agentic 26.05.30 pin + pyright-clean + logger isolation

- `fireflyframework-agentic` is consumed from its published git tag `v26.05.30`
  (unified `content.binary` normalization). flyquery builds its own pgvector
  hybrid retriever.
- `sqlglot` is declared as a direct dependency backing the Text-to-SQL
  pipeline; `openai-embeddings` retained.
- Pinned `mistralai<2.0.0` (pydantic-ai 1.99 transitive pre-release conflict).
- Resolved every `pyright` warning with real fixes (SQLAlchemy `CursorResult`
  cast for DML rowcount, `FileReader.formats` read-only property, Azure embedder
  requires `AZURE_OPENAI_ENDPOINT`, DuckDB `fetchone()` None-guards, avro/sqlglot
  narrowing, controller `executionEnvironments`).
- `migrations/env.py`: `fileConfig(disable_existing_loggers=False)` so migrations
  no longer mute loggers the app created at import time.

## [26.5.12] - 2026-05-28

### Fixed — Re-upload pipeline correctness + LLM rename detection

Four cooperating bug fixes uncovered during multi-version re-upload
testing of the same workbook. No public API or response-shape change:
the PUT endpoint URL, multipart contract and `ReuploadResponse`
DTO are byte-equivalent to `26.5.11`, so the Python and Java SDKs
keep working without regeneration.

1. **`PUT /api/v1/datasets/{ds}/tables/{tbl}:upload` no longer
   corrupts the targeted snapshot of a multi-section workbook.**
   `IngestService.ingest_reupload` now looks up the existing table's
   `sheet_or_json_path` and sanitised `name` (single PK lookup) and
   threads them into Stage 2. `run_parse` filters the proposed-table
   list down to the matching section, with fallback by sanitised name
   so a row insertion that shifts the section range
   (`section[1:697]` → `section[1:698]`) still resolves correctly.
   Before the fix, the parser kept whatever section came first in the
   workbook (usually Sheet1), silently overwriting the targeted
   table's snapshot with unrelated data.

2. **LLM rename-detection agent is actually invoked.** Both call
   sites of `run_reconcile` (`IngestService.ingest` sync path and
   `IngestWorker` async path) now forward `settings=self._settings`.
   Without this, `_invoke_rename_agent` short-circuited on
   `if settings is None: return None`, so the Haiku-backed rename
   resolver never ran and every ambiguous removed-column landed as a
   `RENAMED_CANDIDATE` for human review instead of being auto-confirmed.

3. **`flyquery_schema_changes.llm_rationale` is persisted.**
   `_invoke_rename_agent` now returns the full ranked list
   (`[{name, confidence, rationale}, ...]`) instead of just the top
   `(confidence, name)` tuple. `_detect_renames` returns a third
   `confirmed_rationales` map keyed by old column name.
   `_write_schema_changes` writes the rationale into `RENAMED` rows
   (LLM rationale or "Auto-confirmed by 1-to-1 type signature match"
   for the unambiguous branch) and into `RENAMED_CANDIDATE` rows
   (rationale of the top proposal hoisted for fast audit).

4. **`RENAMED_CANDIDATE.after_json.candidates` carries the LLM's
   ranking.** When the top proposal misses the 0.8 auto-confirm
   threshold, the system now stores the ranked
   `[{name, confidence, rationale}]` list from the agent. The old
   behaviour stored the raw type-group of added columns with no
   discrimination — every `RENAMED_CANDIDATE` for the same type
   showed the same flat list. Operators reviewing pending renames
   now see "best guess first" with the confidence and rationale per
   alternative.

### Changed — Internal-only

- `run_parse` accepts two new keyword params: `target_sheet_or_json_path`
  and `target_name`. Both default to `None`, so call sites that didn't
  ask for targeted-section selection are unaffected. The OpenAPI
  surface is unchanged.
- `_detect_renames` signature changed from
  `tuple[dict, list]` to `tuple[dict, dict, list]`. Internal helper;
  not exported. Callers updated in the same change.

### Fixed — CI

- `ruff format` on `stages/parse.py` and `stages/reconcile.py`
  (line-length wrapping). Caught by the `task lint` step on the
  `26.5.11` PR; rewrapped without behavior change.

## [26.5.11] - 2026-05-24

### Added — Webhook callbacks for every async ingest job

A receiver-side push channel for the async ingest pipeline. The
caller attaches `callback_url` (+ optional `secret` + custom
`headers`) to `POST /api/v1/ingest-jobs` or to
`POST /api/v1/datasets/{ds}/files:async`; on terminal status
(`SUCCEEDED` / `FAILED` / `CANCELLED`) the worker POSTs the
canonical `IngestJobRead` payload to the configured URL.

- **Transactional outbox** -- a new `flyquery_callback_outbox` table
  (migration `0013_job_callbacks`) is written in the SAME transaction
  as the job's status flip. A process crash between the two writes is
  impossible, so a "succeeded" job ALWAYS has its callback queued.
- **`CallbackWorker`** drains the outbox with `FOR UPDATE SKIP LOCKED`
  so N peer workers scale horizontally without colliding. Five-attempt
  exponential backoff (0s, 30s, 5m, 1h, 6h), then `DEAD`. New CLI
  subcommand `flyquery worker callback` and `flyquery worker all` now
  includes it alongside ingest + retention.
- **HMAC-SHA256 signing** -- when a `secret` is provided, every
  request carries `X-Flyquery-Signature: sha256=<hmac>` computed over
  the raw body. Dispatcher applies reserved headers (`Content-Type`,
  `X-Flyquery-Event`, `X-Flyquery-Job-Id`, `X-Flyquery-Signature`)
  LAST so a misconfigured or malicious extra-header bag cannot shadow
  the signature header.
- **Per-request OR per-configuration** -- the per-request bundle takes
  precedence, but `FLYQUERY_DEFAULT_CALLBACK_URL` /
  `FLYQUERY_DEFAULT_CALLBACK_SECRET` /
  `FLYQUERY_DEFAULT_CALLBACK_HEADERS` provide a process-wide default
  receiver so an operator can wire every async job to a central hub
  without touching every caller. Whole-bundle precedence (URL +
  secret + headers move together) prevents accidentally leaking the
  default secret to a different receiver.
- **`GET /api/v1/ingest-jobs/{id}/callbacks`** -- paginated audit
  trail. One row per delivery attempt with URL, event type
  (`ingest.succeeded` / `ingest.failed`), status (`PENDING` /
  `DELIVERED` / `FAILED` / `DEAD`), attempt count, last HTTP status
  code + last error, and next scheduled retry. Supports `?status=`
  filter.
- **SDK helpers**:
  - Python: `client.upload_async(..., callback_url=, callback_secret=,
    callback_headers=)` + `client.list_job_callbacks(job_id, ...)`
    (and `_sync` mirrors). The auto-generated `IngestJobsApi.list_callbacks`
    + `CallbackConfig` / `CallbackDeliveryRead` /
    `CallbackDeliveryListResponse` models are also exposed.
  - Java: `client.ingestJobs().listCallbacks(...)` from the
    regenerated `IngestJobsApi`. `CallbackConfig` model can be set
    on `IngestJobCreate.callback` for `createJob(...)`.
- **New docs**: [`docs/callbacks.md`](docs/callbacks.md) -- full
  contract, receiver example with signature verification, retry
  schedule, ops runbook for DEAD rows. Cross-linked from
  `docs/async-ingest.md` + `docs/workers.md`.

### Fixed — Critical correctness bugs surfaced by end-to-end testing

- **Publisher DI was silently in-memory** -- `core/configuration.py`
  had a stale `@bean ingest_publisher` factory that called
  `_resolve_eda_publisher()` at factory-eval time (before
  `EdaAutoConfiguration` wired the EventPublisher). The factory won
  precedence over the `@service` registration on `IngestPublisher`,
  so every running process held `self._publisher = None` and every
  `publish_ingest_requested` silently hit the in-memory branch.
  Workers never received `IngestRequested` events; async jobs sat in
  `PENDING` forever and were only rescued by the orphan-PENDING
  reaper 10 minutes later. Factory deleted; the `@service`
  registration now resolves `EventPublisher` via constructor
  injection like flycanon / flyradar.
- **Pyfly DI param-name mismatches** -- pyfly's resolver is name-first
  with type-fallback. `IngestService(publisher: IngestPublisher, ...)`
  did not match the snake-cased bean name `ingest_publisher`. Renamed
  to `ingest_publisher` on `IngestService` + `IngestJobService`. Also
  renamed `repository` / `repo` -> snake-cased bean name on
  `SchemaObjectService`, `SchemaChangeService`, `RelationService`,
  `SemanticService`, `SemanticDimensionsService`, `WorkspaceService`
  for forward-safety.
- **`triggered_by="WORKER"` violated `ck_snapshots_trigger`** -- the
  CHECK constraint accepts only `USER` / `AGENT` / `SCHEDULED` /
  `REPARSE`. Every async PARSE_AND_INGEST job failed at reconcile
  with `CheckViolationError`. Worker now writes `REPARSE` for the
  by-worker path (`workers.py:488`).
- **`governance_json` / `synonyms_json` DTO polymorphism** -- legacy
  rows from a prior `NULL || dict` jsonb-concat bug stored
  `governance_json` as `[null, {...}]`. The DTO had been widened to
  `dict | list | None` as a band-aid; that ambiguity leaked into
  every consumer and broke `GET /tables/{id}/objects` with a Pydantic
  422. Fixed properly:
  - DTOs tightened to `synonyms_json: list[str]` /
    `governance_json: dict[str, Any]`.
  - New normaliser `core/services/storage/jsonb_normalize.py` coerces
    any historical shape to canonical at every consumer + producer
    seam (DTO `field_validator` + `reconcile` stage write path).
  - Migration `0012_normalize_jsonb_shapes` heals existing polluted
    rows.
- **`flyquery_examples` insert syntax** -- `:embedding::vector`
  confused SQLAlchemy's bind parser (text parsed the second `:` as a
  new bind), so asyncpg received a literal `:embedding` token and
  raised `PostgresSyntaxError`. Every successful NL query crashed
  with a 500 after the SQL executed (auto-learning save path).
  Changed to `CAST(:embedding AS vector)`.
- **CallbackWorker triggered pyfly's ApplicationRunner convention**
  -- a bean method named `run()` is auto-invoked at API startup with
  a positional `args` parameter. Renamed to `run_forever()` so the
  callback drain runs ONLY under the dedicated CLI command.
- **Callback dispatcher header ordering** -- caller-supplied extra
  headers were applied AFTER our reserved keys, allowing
  `extra_headers={"X-Flyquery-Signature": "evil"}` to shadow the real
  signature. Reversed: reserved keys are applied LAST.

### Changed

- `POST /api/v1/ingest-jobs` now declares its request body via
  `Valid[Body[IngestJobCreate]]` (was: manual `request.json()` decode).
  This publishes `IngestJobCreate` + the nested `CallbackConfig`
  schemas into `openapi.json` so SDK generators see them. Wire
  contract unchanged; existing 200/422 behaviour identical.
- `pyfly.yaml`, `pyproject.toml`, `Taskfile.yml`, both SDK
  `pyproject.toml` / `setup.py` / `pom.xml` / `build.gradle`, README
  badge, and `app.py` decorator all now read `26.5.11`. (Also fixed
  the `app.py` drift from `26.5.0`.)

## [26.5.10] - 2026-05-24

### Added — Release-quality polish (final pass)

- **Version sync across every artifact**: ``pyproject.toml``,
  ``pyfly.yaml``, ``sdks/python/pyproject.toml``, ``sdks/java/pom.xml``,
  ``Taskfile.yml`` (the ``packageVersion`` / ``artifactVersion``
  additional-properties), and the README version badge all now read
  ``26.5.10``. CI also rewrites these from the git tag at publish
  time (see ``publish-sdks.yaml``), so a future tag-only release
  stays consistent even if a developer forgets to bump locally.
- **Python ``FlyqueryClient`` v1 helpers**: ``recent_queries``,
  ``get_query``, ``fetch_query_result``, ``billing_rollup``,
  ``workspace_stats``, ``audit_log``, ``cost_log``, ``upload_async``
  + sync mirrors. New typed accessors for ``QueriesApi``,
  ``BillingApi``, ``StatsApi``, ``AuditEventsApi``, ``CostEventsApi``.
  ``.openapi-generator-ignore`` extended to preserve ``client.py`` +
  ``tests/`` across regenerations.
- **Java ``FlyqueryClient`` v1 accessors**: new ``queries()``,
  ``billing()``, ``stats()``, ``auditEvents()``, ``costEvents()``
  methods that return the typed ``*Api`` instances. The 7th wrapper
  unit test now asserts all five are non-null.
- **Docker label fixed**: the ``org.opencontainers.image.description``
  was the flycanon string ("Operational Knowledge Repository"); it's
  now flyquery's actual one-liner.

### Fixed

- **Missing return-type annotations on 8 controllers** dropped the
  associated response schemas (``BatchQueryResponse``,
  ``BulkFileUploadResponse``, agent-tier ``AnswerResponse`` /
  ``SqlExecuteResponse`` / ``ConversationRead`` / ``ExampleRead`` /
  ``CancelResponse``) from the published OpenAPI spec, which in
  turn made both SDK regenerators emit empty / inline classes.
  Restored every annotation; spec grew 81 -> 85 schemas after the
  fix. Java SDK build had been failing with ``AnyOf cannot find
  symbol`` until this was corrected; now builds clean.
- ``QueryHistoryItem.created_at`` / ``QueryDetailRead.created_at``
  / ``QueryResultRead.ttl_expires_at`` are now typed ``datetime``
  instead of ``Any`` (the earlier ``Any`` produced unusable
  ``AnyOf`` Java classes).

### Added — v1 roadmap endpoints

The four "v1+" placeholders from the original audit are now live.
All build on tables + entities that already existed; the new code
is read endpoints + rollup services + DTOs.

| Endpoint | Purpose |
|---|---|
| ``GET /api/v1/queries`` | Paginated query history. Filters: ``dataset_id``, ``execution_status``, ``semantic_path_taken``, ``date_from``, ``date_to``. Page size clamped to [1, 200]. Returns ``Paginated[QueryHistoryItem]`` (compact: no heavy JSONB cols). |
| ``GET /api/v1/queries/{id}`` | Full single-query payload incl. every candidate proposal, model identifier (grounding/generation/critic/explainer), clarification frame, PII findings, error envelope. Cross-tenant probing maps to 404 (same as missing). |
| ``GET /api/v1/queries/{id}/result`` | Re-download preview + presigned Parquet URL. URL is ``None`` when TTL elapsed (default 24h) or presign fails -- consumer must rerun. |
| ``GET /api/v1/billing`` | Cost rollup over ``flyquery_cost_events``. ``period`` = ``day`` \| ``week`` \| ``month``; ``date_from``, ``date_to`` bound the window. Returns ``BillingRollup`` with split ``ingest_cost_cents`` / ``query_cost_cents`` / ``other_cost_cents`` per bucket plus ``total_cost_cents``. |
| ``GET /api/v1/stats`` | Compact workspace summary: ``storage_used_bytes``, ``dataset_count``, ``table_count``, ``query_count_last_30d``, ``token_count_last_30d``, ``ingest_job_count_pending``. |

### Added — Worker architecture (parity with flycanon + flyradar)

- **``RetentionWorker``** at ``core/services/retention/retention_worker.py``.
  Periodic loop (default ``retention_scan_interval_s = 300s``) with six
  responsibilities:
    1. **Stuck-RUNNING ingest job reaper** -- jobs with
       ``started_at`` older than ``processing_lease_s`` (default
       1800s) are reset to PENDING and republished onto the bus. This
       is the crashed-worker recovery primitive flyquery was missing.
    2. **Orphan-PENDING reaper** -- jobs in PENDING for longer than
       ``orphan_queued_grace_s`` (default 600s) are republished in
       case the original event never made it to the bus.
    3. **TTL deletes** for ``flyquery_ingest_events`` (30d),
       ``flyquery_audit_events`` (365d), ``flyquery_cost_events`` (365d).
       Set any to ``0`` to disable that window (keep forever).
    4. **PURGING dataset hard-delete** -- dataset rows whose
       ``updated_at`` predates ``dataset_purge_tombstone_days``
       (default 90d) get the SQL row deleted (the object-store walk
       already ran at purge time).
  Step-level failure isolation -- one concern raising never aborts
  the rest of the sweep.
- **``flyquery worker {ingest|retention|all}`` CLI** -- three
  subcommands that bootstrap the DI context, resolve the right
  worker bean, install SIGTERM/SIGINT handlers, and run forever.
  ``all`` is a dev convenience that runs both in one process.
- **New settings** in ``config.py``:
  ``retention_scan_interval_s``, ``retention_ingest_events_days``,
  ``retention_audit_events_days``, ``retention_cost_events_days``,
  ``processing_lease_s``, ``orphan_queued_grace_s``,
  ``dataset_purge_tombstone_days``.
- **New repository methods** to support the worker:
  ``IngestJobRepository.list_stuck_running_ids`` /
  ``reap_stuck_running`` / ``list_orphaned_pending_ids`` /
  ``delete_events_older_than``;
  ``AuditEventRepository.delete_older_than``;
  ``CostEventRepository.delete_older_than``;
  ``DatasetRepository.delete_purged_older_than``.

### Added — Schema detection deep-dive doc (``docs/schema-detection.md``)

Comprehensive 6,200-word operator-facing guide covering:
- Format detection precedence (extension-first, magic-byte fallback)
- Per-format strategies (CSV delim sniff, XLSX multi-section walker,
  JSON object-vs-array, schema-bearing formats)
- Sample-based type inference + locale-aware date hints
- Column-name proposer agent (3-level trigger logic)
- Drift detection with RENAMED_CANDIDATE state machine + 0.8
  auto-confirm threshold (currently a module constant, not a
  tunable -- flagged as a gap)
- PII tagging (regex / presidio / disabled) + HUMAN override
- Description + embedding generation
- A worked example (multi-sheet "Q1 Dashboard.xlsx" with merged
  cells)
- Troubleshooting + settings reference

Spec-vs-code mismatch flagged: ``drift_policy`` only has ``AUTO`` and
``MANUAL`` in the code; ``STRICT`` is documented but not implemented.

### Added — Worker architecture doc (``docs/workers.md``)

4,351-word operator-facing doc covering:
- What runs where (API + IngestWorker + RetentionWorker)
- Concurrency primitives (Semaphore + wait_for + Event + inflight set)
- Horizontal scaling formula
- Backpressure model
- Crashed-worker recovery
- Cooperative cancellation
- Observability hooks
- RLS bypass requirement
- Worker CLI reference + deployment topologies (dev / small prod /
  mid prod / K8s with HPA)
- Failure modes catalog

### Changed

- ``pyproject.toml`` version 26.5.9 -> 26.5.10
- ``pyfly.yaml`` ``pyfly.app.version`` 26.5.9 -> 26.5.10
- OpenAPI spec: 90 paths / 74 schemas -> **95 paths / 81 schemas / 32 tags**
- Both SDKs regenerated (Python + Java)

### Fixed

- **Production bug in ``IngestWorker._drain_inflight``**: the
  post-cancel cleanup used ``with asyncio.timeout(5)`` -- but
  ``asyncio.timeout`` is an ASYNC context manager, ``with`` raises
  ``TypeError``. Replaced with ``asyncio.wait_for(...)`` + a
  warning log if the hard timeout elapses. The bug was latent
  because no test exercised the cancel path until 26.5.10.
- DTO datetime fields (``QueryHistoryItem.created_at``,
  ``QueryDetailRead.created_at`` / ``finalised_at``,
  ``QueryResultRead.ttl_expires_at``) are now typed as ``datetime``
  instead of ``Any``. The earlier ``Any`` produced ``AnyOf`` Java
  classes that openapi-generator didn't fully scaffold.

### Added — Tests (+21 tests, total 311)

- ``tests/unit/test_retention_worker.py`` (9 tests) -- happy paths,
  TTL=0 short-circuits, per-step failure isolation, publisher-blip
  isolation, cooperative shutdown.
- ``tests/unit/test_ingest_worker_concurrency.py`` (4 tests) --
  semaphore cap enforcement under burst, timed-out handler isolation,
  drain wait + drain cancel.
- ``tests/unit/test_v1_endpoints.py`` (8 tests) -- DTO mapping,
  ``QueryRepository.list_queries`` limit clamping, BillingService
  period validation, presigned-URL TTL guard.

### CI requirements (operator action)

This release is structured to pass the existing CI pipeline
(``pr-gate.yaml``) without intervention. To verify locally before
push:

```bash
task lint
task test:unit
task test:integration   # needs Docker (Postgres + Redis + MinIO)
uv run python scripts/check_lockstep.py
```

Production deployment requires updating the Docker entrypoint /
systemd / k8s manifests to spawn ``flyquery worker retention``
alongside ``flyquery worker ingest``. The single-process
``flyquery worker all`` form is dev-only.

### Attribution

Released by ancongui.

---

## [26.5.9] - 2026-05-24

### Added — Repository extraction (audit issues 4.2 + 4.3 complete)

Every controller in ``src/flyquery/web/controllers/`` is now a thin
HTTP adapter -- **zero ``sa.text(...)`` calls remain anywhere under
that tree**. The eight repositories from the
``docs/superpowers/specs/refactor-repository-layer.md`` plan all
landed:

| Repository | Migrated from |
|---|---|
| ``SchemaObjectRepository`` + ``SchemaObjectService`` | inline SQL in ``schema_objects_controller`` |
| ``SchemaChangeRepository`` + ``SchemaChangeService`` | inline SQL in ``schema_changes_controller`` (with typed ``SchemaChangeNotFound`` / ``SchemaChangeWrongState`` exceptions) |
| ``RelationRepository`` + ``RelationService`` + new ``interfaces/relations.py`` DTOs | inline SQL in ``relations_controller`` |
| ``TableRepository`` + ``SchemaSnapshotRepository`` + ``TableService`` | inline SQL across 7 endpoints in ``tables_controller`` |
| ``IngestEventRepository`` | promoted from the ``emit_*`` helpers in ``events.py``; helpers stay as thin wrappers |
| ``FileRepository`` | inline SQL in ``stages/receive.py`` + ``workers._load_file`` |
| ``IngestJobRepository.merge_request_json()`` | inline SQL in ``files_controller._flag_already_received`` (the ``already_received`` flag the async upload sets to skip Stage 1) |
| New repo + helpers on ``SchemaSnapshotRepository`` (``get_current_snapshot_for_dataset_table`` + ``create_snapshot_and_promote``) | inline SQL in ``sql_execute_controller._apply_dml_mutation`` (DML copy-on-write for DERIVED tables) |
| New ``TableRepository.list_kinds_for_dataset_by_names`` | inline SQL in ``sql_execute_controller._resolve_derived_tables`` |

(``QueryResultRepository``, ``ConversationTurnRepository``,
``SemanticVersionRepository`` were already part of the existing
``QueryRepository`` / ``ConversationRepository`` / ``SemanticRepository``
beans -- they cover both their primary table and the secondary one
the audit flagged separately.)

### Added — CI gate

- **`tests/unit/test_no_raw_sql_in_controllers.py`** -- a two-test
  unit gate that fails the build if any file under
  ``src/flyquery/web/controllers/`` either:
    - calls ``sa.text(`` or ``sqlalchemy.text(`` (raw SQL), or
    - imports the SQL builder directly (``import sqlalchemy`` /
      ``from sqlalchemy import ...``).
  ``async_sessionmaker`` / ``AsyncSession`` imports stay allowed --
  controllers legitimately thread them into services that own
  per-request session lifecycle (the query + sql_execute paths build
  a fresh ``SearchIndex`` / ``TableResolver`` per request).
- **20 new unit tests** spread across the 4 new services
  (``SchemaObjectService`` / ``SchemaChangeService`` / ``RelationService`` /
  ``TableService`` not all individually tested -- happy-path / 404 /
  wrong-state / source-tagging are covered).

### Changed

- ``SqlExecuteController`` now takes ``table_repository`` +
  ``schema_snapshot_repository`` in its DI signature; the two
  module-level DML helpers (``_resolve_derived_tables`` /
  ``_apply_dml_mutation``) became thin wrappers around repo methods.
- ``AgentSqlExecuteController`` mirror-injects the same repos.
- ``ReceiveStage`` and ``IngestWorker._load_file`` delegate to
  ``FileRepository``; the two callsites no longer share parallel SQL.

### Status

The original audit's "no SQLAlchemy in controllers" rule is now
enforced both *culturally* (every controller is a thin adapter) and
*mechanically* (the CI gate above will fail any PR that regresses).
The ``refactor-repository-layer.md`` spec is marked complete.

### Attribution

Released by ancongui.

---

## [26.5.8] - 2026-05-24

### Added

- **`POST /api/v1/datasets/{id}/files:async`** -- async file ingestion
  endpoint. Stage 1 (receive) runs synchronously to persist bytes +
  ``flyquery_files`` row; stages 2-10 are queued as a
  ``PARSE_AND_INGEST`` job that the existing ``IngestWorker``
  processes. Response is 202 with a ``Location`` header pointing at
  ``GET /ingest-jobs/{job_id}``. Use this instead of the sync
  endpoint for files large enough to risk request-thread timeout.
- **Audit + cost event write paths.** New service + repository for
  ``flyquery_audit_events`` and ``flyquery_cost_events`` (entities +
  tables existed since 26.5.0; writers were missing). Both writers
  are best-effort -- a failed event insert never breaks the calling
  operation.
    - ``GET /api/v1/audit-events`` -- paginated audit ledger reader.
    - ``GET /api/v1/cost-events`` -- paginated per-call LLM cost
      ledger reader.
    - First write callsites wired: ``dataset.created``,
      ``dataset.updated``, ``dataset.archived``, ``dataset.purged``.
      More follow as we plumb correlation_id through agent + query
      handlers.
- **`GET /api/v1/glossary/{id}`** + **`GET /api/v1/examples/{id}`**
  -- single-record fetch endpoints. The services already had ``get``;
  controllers just lacked the route.
- **`pyfly.app.name` / `pyfly.app.version` / `pyfly.app.description`**
  in ``pyfly.yaml`` so ``GET /actuator/info`` reports flyquery instead
  of pyfly defaults.
- **`docs/superpowers/specs/refactor-repository-layer.md`** -- carefully
  scoped migration plan for the remaining "controllers do raw SQL"
  follow-up (audit issues 4.2 + 4.3). Sequenced by blast radius so
  each step is a self-contained PR.

### Changed

- **`IngestJobService.enqueue_parse_and_ingest()`** -- new internal
  method that bypasses ``IngestJobCreate.validate_startable()`` for
  the async upload endpoint (PARSE_AND_INGEST has always been
  excluded from the startable allowlist; the async upload is the
  second canonical entry point).
- **`IngestWorker._run_reparse()`** honours a new
  ``request_json.already_received`` flag: when set, Stage 1 is
  skipped (the async upload endpoint already ran it) and the
  existing ``file_id`` is reused -- eliminating a duplicate file
  row + duplicate object-store key per async upload.
- **`IngestWorker._run_reparse()`** now materialises
  ``ObjectStore.get()``'s ``AsyncIterator[bytes]`` into ``bytes``
  before passing to downstream stages (the previous code was bugged
  for the REPARSE / re-queued PARSE_AND_INGEST paths -- never
  exercised in integration tests so the bug went undetected).
- **`docs/api-reference.md`** §5.12 -- the audit + cost event
  endpoints (previously marked "v1+") are now documented as live.
  ``/api/v1/billing`` and ``/api/v1/stats`` remain v1+ but explicitly
  reference ``/cost-events`` as the available raw-data source.
- **`docs/api-reference.md`** §5.12 -- new "Health probes" section
  documenting the pyfly-provided ``/actuator/health/*``,
  ``/actuator/info``, ``/actuator/metrics``, and ``/admin/*`` surface.
  Calls out that consumers should NOT add ad-hoc ``/healthz`` /
  ``/readyz`` -- the actuator already covers them.

### Notes

- ``PARSE_AND_INGEST`` jobs queued by the async endpoint correctly
  reuse the file_id; jobs queued the old way (operator-triggered
  REPARSE) still get a fresh receive (which is correct: REPARSE
  semantics include "produce a new snapshot version").
- The 12 remaining entities without a repository (Table, File,
  SchemaSnapshot, SchemaChange, SchemaObject, Relation, QueryResult,
  ConversationTurn, SemanticVersion, IngestEvent + the lockstep
  AgentToken + the new AuditEvent/CostEvent which DO have repos)
  are tracked in the new spec at
  ``docs/superpowers/specs/refactor-repository-layer.md``. That
  refactor is genuinely a week of careful work; AuditEventRepository
  + CostEventRepository (added here) demonstrate the target shape.

### Attribution

Released by ancongui.

---

## [26.5.7] - 2026-05-24

### Added

- **`Paginated[T]` generic envelope** at
  ``src/flyquery/interfaces/pagination.py`` -- single uniform shape
  (``{items, total, limit, offset, has_more}``) returned by every list
  endpoint. Replaces three inconsistent variants:
    - ``{items, total, limit, offset, has_more}`` -- 4 endpoints
      already shipped this shape.
    - ``{items}`` only -- 8 endpoints have been upgraded.
    - bare ``dict`` / list returns.
  12 typed ``Paginated[T]`` variants now ship in the spec
  (``Paginated[DatasetRead]``, ``Paginated[WorkspaceRead]``,
  ``Paginated[ConversationRead]``, ``Paginated[ExampleRead]``,
  ``Paginated[GlossaryTermRead]``, ``Paginated[SemanticMetricRead]``,
  ``Paginated[SemanticDimensionRead]``, ``Paginated[SemanticVersionRead]``,
  ``Paginated[TableRead]``, ``Paginated[SnapshotRead]``,
  ``Paginated[SchemaObjectRead]``, ``Paginated[SchemaChangeRead]``).
  8 unit tests under ``tests/unit/test_paginated.py``.
- **`DELETE /api/v1/datasets/{id}:purge`** (202 Accepted). Hard-delete
  endpoint that flips ``status`` to ``PURGING`` and walks the
  ``flyquery/{tenant}/{workspace}/{dataset}/`` object-store prefix,
  reclaiming every blob underneath (``files/``, ``tables/``,
  ``derived/``, ``results/``). Mirrors the existing
  ``DELETE /workspaces/{id}:purge`` at the dataset granularity --
  previously only ``DELETE /datasets/{id}`` existed and was soft-only
  (status -> ``ARCHIVED``), leaving Parquet blobs orphaned forever.
- **`PurgeAccepted`** typed envelope at
  ``src/flyquery/interfaces/lifecycle.py`` for purge-style endpoints.
- **3 unit tests** for ``DatasetService.purge`` covering happy path,
  prefix isolation (other datasets / tenants untouched), and the
  empty-store case.

### Changed

- **11 controllers** ported their list endpoints to ``Paginated[T]``:
  datasets, workspaces, tables (list / search), conversations,
  glossary, examples (user + agent), semantic_metrics (list + history),
  semantic_dimensions (list + history). All gain explicit ``limit`` /
  ``offset`` query params where they were missing.
- **`docs/api-reference.md`** -- no API-shape breakage; the new
  envelope is a superset of every previous shape (legacy ``{items}``
  consumers keep working, just get extra fields).
- **OpenAPI spec**: 64 -> 86 paths, 51 -> 66 schemas.

### Notes

- ``Paginated[T]`` carries a ``# noqa: UP046`` because PEP 695 generic
  syntax (``class Paginated[T](BaseModel)``) breaks openapi-generator's
  schema introspection; the older ``Generic[T]`` form is the one that
  generates clean ``Paginated*`` classes in both SDKs.
- ``DatasetService.purge`` leaves the SQL row in place with
  ``status='PURGING'`` so audit / lineage references survive. A
  separate retention job (90-day window, mirroring ``conv_ttl_days``)
  is expected to hard-delete the row. Both SQL retention and
  workspace-level storage credit reclamation are tracked as follow-ups.

### Attribution

Released by ancongui.

---

## [26.5.6] - 2026-05-24

### Added

- **`/api/v1/agent/*` surface expanded from 8 to 28 distinct paths.**
  Agents can now drill down through the same resources as user-tier
  callers, scoped to the matching agent-token scopes. Token + scope
  verification, idempotency keys on writes, and SSE on streams are
  all wired:
    - **`/agent/conversations`** -- POST (create, 201), GET (list),
      GET `{id}`, POST `{id}/turn`. Scopes:
      ``flyquery.conversations:read|write``. Mutating endpoints
      require ``Idempotency-Key``.
    - **`/agent/ingest-jobs`** -- POST (create, 201), GET (list),
      GET `{id}`, GET `{id}/events`, GET `{id}/stream` (SSE),
      POST `{id}:cancel`. Scopes:
      ``flyquery.ingest:read|run``.
    - **`/agent/datasets`** -- GET (list), GET `by-name/{name}`,
      GET `{id}`. Scope: ``flyquery.datasets:read``. Write paths
      stay user-tier (operator policy).
    - **`/agent/datasets/{ds}/tables`**, **`/agent/tables`**,
      **`/agent/tables/{id}`** + `/snapshots`, `/objects`, `/changes`,
      **`/agent/tables/by-name/{name}`**,
      **`/agent/schema-objects/{id}`** -- all GET. Scope:
      ``flyquery.schema:read``.
    - **`/agent/datasets/{ds}/relations`** -- GET. Scope:
      ``flyquery.relations:read``. Approve / reject stay user-tier.
    - **`/agent/query:batch`** -- POST. Mirror of user-tier
      `/query:batch`. ``Idempotency-Key`` required.
- **`sdks/java/src/main/java/com/firefly/flyquery/FlyqueryClient.java`**:
  Java ergonomic wrapper, mirror of `flyquery_sdk.client.FlyqueryClient`.
  Builder sets the four-header contract once (``X-Tenant-Id``,
  ``X-Workspace-Id``, optional ``X-Agent-Token``); ``withIdempotencyKey``,
  ``withAgentToken``, ``withCorrelationId`` return sibling clients
  without mutating the parent. Exposes typed accessors for every
  generated ``*Api`` class. 7 unit tests in
  ``src/test/java/.../FlyqueryClientTest.java``.

### Changed

- **OpenAPI spec**: 64 → 85 paths, 22 → 27 tags after the agent
  surface expansion.
- **Both SDKs regenerated** to surface the new agent endpoints (Python:
  added `agent_conversations_api.py`, `agent_datasets_api.py`,
  `agent_ingest_jobs_api.py`, `agent_relations_api.py`,
  `agent_tables_api.py`; Java: matching `Agent*Api.java` classes).
- **`sdks/java/.openapi-generator-ignore`**: preserves the hand-written
  ``FlyqueryClient.java`` + its test across regenerations.

### Notes

- The agent surface uses a uniform delegation pattern: each agent
  controller takes the corresponding user-tier controller as a
  dependency, verifies token + scope at the boundary, then forwards
  the call. Avoids duplicating handler logic; matches the existing
  ``AgentSqlExecuteController`` shape.
- Idempotency on agent surface mutating endpoints follows the
  ``replay_dedup`` contract from 26.5.5 -- ``Idempotency-Key`` is
  *required* (per agent-tier policy).

### Attribution

Released by ancongui.

---

## [26.5.5] - 2026-05-24

### Added

- **`scripts/openapi_snapshot.py`**: rewritten to defensively re-apply
  `enrich_openapi_with_headers` + `enrich_openapi_with_sse` on the
  dumped spec. The old script silently re-installed pyfly's bare
  generator, which discarded `_wrapped_openapi`; the resulting on-disk
  `openapi.json` shipped without any of the 5 flyquery header
  parameters (`TenantIdHeader`, `WorkspaceIdHeader`, `AgentTokenHeader`,
  `CorrelationIdHeader`, `IdempotencyKeyHeader`) or the 3 securityScheme
  blocks. Both generated SDKs were therefore blind to the four-header
  wire contract. New regression tests in
  `tests/integration/test_openapi_snapshot.py` enforce the surface
  on every snapshot.
- **`src/flyquery/web/idempotent_handler.py`**: new `replay_dedup()`
  helper that wraps a handler in `Idempotency-Key` lookup + record.
  Wired into 5 controllers that previously had zero enforcement
  despite the spec advertising the header:
    - `POST /api/v1/agent/query` (required)
    - `POST /api/v1/agent/sql:execute` (required)
    - `POST /api/v1/agent/examples` (required)
    - `POST /api/v1/datasets/{id}/files:bulk` (optional)
    - `POST /api/v1/query:batch` (optional)
  Lives outside `web/conventions/` (which is lock-step with canon /
  radar) so flyquery can move alone here.
- **`src/flyquery/web/openapi_sse.py`**: enricher that declares
  `text/event-stream` content on every SSE endpoint's 200 response.
  The Java SDK used to emit `Mono<Void>` for `streamJob`; it now emits
  `Mono<String>`. The Python SDK now generates `stream_job` with all 5
  header parameters typed.
- **`Taskfile.yml sdk:all`**: new task chaining
  `openapi-snapshot` -> `sdk:python` -> `sdk:java` so the spec and
  SDKs can't drift.
- **`tests/unit/test_idempotent_handler.py`**: 6 unit tests covering
  cold / warm / missing-key / invalid-key / dict-return paths.

### Changed

- **`Taskfile.yml sdk:python`** + **`sdk:java`**: both tasks now
  `rm -rf` the generated `api/` + `models/` + `docs/` trees BEFORE
  regenerating, so stale split-tag files (e.g. `IngestApi.py` from a
  pre-split spec) no longer accumulate. Python SDK dropped from 29 to
  22 API files; Java dropped from 28 to 22.
- **`sdks/java/pom.xml`**: full metadata refresh:
    - `source/target 1.8` -> Java 25 (`<release>${java.version}</release>`)
    - `spring-boot-version 2.7.17` -> `3.5.9`
    - `jakarta-annotation-version 1.3.5` -> `3.0.0`
    - `useJakartaEe=true` added to `task sdk:java`
      so generated annotations use `jakarta.*` not `javax.*`
    - `<url>` / `<scm>` / `<developers>` repointed from
      openapitools.org to `firefly-operationOS/flyquery`
    - `<license>` `Unlicense` -> `Apache-2.0` (matches `LICENSE`)
- **`sdks/python/tests/test_smoke.py`**: updated for the current split
  taxonomy (`SchemaApi` -> `SchemaChangesApi` + `SchemaObjectsApi`,
  etc.) and a new regression test guards against stale class names
  leaking back on regen.
- **`docs/api-reference.md` section 5.12**: `GET /audit`, `/billing`,
  `/stats`, `/queries`, `/queries/{id}`, `/queries/{id}/result` are
  now explicitly marked `(v1+)` with a status note pointing at the
  cost / audit roadmap -- consistent with the CHANGELOG and `docs/billing.md`.

### Fixed

- The 5 endpoints listed under **Added > idempotent_handler** were
  documented as accepting `Idempotency-Key` for two releases but no
  controller consulted the store. Replays were silently re-running
  multi-LLM pipelines (agent/query) or re-ingesting files (files:bulk).

### Attribution

Released by ancongui.

---

## [26.5.4] - 2026-05-23

### Added

- `config.py`: 13 new env vars that docs already referenced but were missing
  (`FLYQUERY_CONV_TTL_DAYS`, `FLYQUERY_CONV_HISTORY_TURNS`,
  `FLYQUERY_CONV_SUMMARY_MAX_TOKENS`, `FLYQUERY_CONV_SUMMARY_INTERVAL`,
  `FLYQUERY_AUTOLEARN_ENABLED`, `FLYQUERY_INGEST_HEARTBEAT_S`,
  `FLYQUERY_INGEST_MAX_ATTEMPTS`, `FLYQUERY_KAFKA_BOOTSTRAP_SERVERS`,
  `FLYQUERY_EMBEDDING_RATE_LIMIT_RPM`, `FLYQUERY_PII_REGEX_PATTERNS_PATH`,
  `FLYQUERY_PRESIDIO_SPACY_MODEL`, `FLYQUERY_OTEL_ENDPOINT`,
  `FLYQUERY_CONV_SUMMARY_INTERVAL`)
- `sdks/java/LICENSE` + `sdks/python/LICENSE`: Apache 2.0 (SDKs are public)
- `sdks/java/README.md`: updated for Java 25 + Spring Boot 3.5.9 + WebFlux coords

### Changed

- **Java SDK regenerated**: `library=webclient` (Spring WebFlux reactive client),
  package `com.firefly.flyquery` (was `io.firefly.flyquery`),
  groupId `com.firefly` (was `io.firefly`), Java 25, Spring Boot 3.5.9
- `Taskfile.yml sdk:java` task updated accordingly
- `.github/workflows/publish-sdk-java.yml`: java-version 21 → 25
- `sdks/python/pyproject.toml`: license `Proprietary` → `Apache-2.0`
- `sdks/java/pom.xml`: full rewrite with Spring Boot 3.5.9 parent, Java 25 compiler
- `README.md`: "Why this service exists" rewritten; new "Why not part of flycanon?"
  section; full 5-step copy-pasteable quickstart; "Status" section removed;
  "What ships in v0" → "Capabilities" (present tense)
- `openapi.json`: re-snapshotted at version 26.5.4

### Fixed

- `docs/conversations.md`: removed non-existent SSE turn + agent/conversations
  endpoints; marked `GET /conversations/{id}/turns` as v1+; TTL default 30d→90d
- `docs/billing.md`: marked `/api/v1/billing` as v1+ (not in current release);
  replaced fake curl example with real DB query
- `docs/stats.md`: marked `/api/v1/stats` as v1+ (not in current release)
- `docs/async-ingest.md`: heartbeat + stale-job recovery marked v1+ (not yet
  implemented in IngestWorker)
- `docs/auto-learning.md`: fixed grammatical error in FLYQUERY_AUTOLEARN_ENABLED
- `docs/operations-runbook.md`: clarified EMBEDDING_RATE_LIMIT_RPM is defined
  but rate-limit enforcement is v1+
- `src/flyquery/core/services/ingestion/stages/publish.py`: removed stale
  "stub in Phase B" comment (EDA publish is fully implemented)
- `src/flyquery/core/services/ingestion/workers.py`: removed stale
  "(Phase D/E; NotImplementedError for now)" comments
- `src/flyquery/core/services/query/query_service.py`: clarified session-borrowing
  rationale in `_table_kinds_by_name`
- Copyright headers added to all `__init__.py` and new test files

### Attribution

Released by ancongui.

---

## [26.5.3] - 2026-05-23

### Added

- Logo asset (`docs/assets/logo.png`) — "tabular intelligence" mark
- README.md polished to canon depth: logo, badges, architecture summary, nav
  table, status matrix for Plans 1–4, local dev and test instructions
- `docs/README.md` — navigation hub with reading paths by user intent and
  full document catalogue
- `docs/pipeline.md` — upload + 10-stage ingestion and query pipeline
  end-to-end with ASCII diagrams and mode coupling (sync vs async via EDA)
- `docs/async-ingest.md` — IngestWorker lifecycle, 5 job kinds, cooperative
  cancel, retry, dead-letter, sequencing guarantees
- `docs/eda-events.md` — `flyquery.ingest` (IngestRequested) and
  `flyquery.schema` (SchemaUpdated) event schemas, durable Postgres outbox,
  consumer guide
- `docs/conversations.md` — multi-turn query memory, drill-down semantics,
  NL→delta-SQL examples, snapshot pinning, API surface
- `docs/prompts.md` — catalog of 7 agent prompts with verbatim instruction
  text, input shape, and output schema (from source)
- `docs/auto-learning.md` — PROPOSED → APPROVED example cycle, eligibility
  criteria, operator approval flow, v1 roadmap
- `docs/pii.md` — 3 scanners (regex/Presidio/disabled), 3 policies
  (warn/redact/reject), ordering guarantee, late-tag flip, custom regex
- `docs/operations-runbook.md` — cold start, daily checks, common errors,
  GDPR purge, key rotation, backup/restore, scaling, incident template
- `docs/troubleshooting.md` — symptom → root cause → fix for 13 common issues
- `docs/deployment-topology.md` — single-node, multi-node, HA ASCII diagrams
  and port reference
- `docs/cicd.md` — 5 workflows, tag-triggered releases, branch protection,
  concurrent worker considerations, required secrets
- `docs/concurrency.md` — AsyncSession scoping, RLS GUC binding, EDA worker
  concurrency, DuckDB per-request isolation, ObjectStore async patterns
- `docs/consumers.md` — SDK patterns (Python + Java + curl), agent-token
  model, idempotency, error handling, 5 integration recipes
- `docs/integration-with-firefly-os.md` — three-pillar narrative,
  flyradar↔flyquery and flycanon↔flyquery integration patterns
- `docs/glossary.md` — full project terminology dictionary (resource
  hierarchy, query pipeline, ingestion, technical terms)
- `docs/scale-and-performance.md` — throughput numbers, bottlenecks, tuning
  knobs, capacity planning
- `docs/billing.md` — per-query + per-ingest LLM cost, `flyquery_cost_events`
  schema, billing API, v0 observe-only + v1 enforcement roadmap
- `docs/stats.md` — `GET /api/v1/stats` response schema, fields reference,
  dashboard usage patterns
- `docs/quality.md` — full testing strategy: unit, integration, conformance,
  parser fixtures, pipeline tests, LLM-gated, lock-step drift gate

### Changed

- `docs/security.md` renamed to `docs/security-model.md` (canon convention)
- Cross-references in `docs/firefly-intelligence-system.md` updated
- `docs/deployment.md` cross-links to `docs/deployment-topology.md`
- README version badge updated to 26.5.3

---

## [26.5.2] - 2026-05-23

### Added
- Packaging shipped
- `openapi.json` committed snapshot + drift gate (`task openapi-snapshot`)
- Python SDK auto-generated (`sdks/python/`, package `flyquery-sdk`, asyncio library)
- Java SDK auto-generated (`sdks/java/`, `io.firefly:flyquery-sdk:26.5.2`, okhttp-gson)
- Full `docs/` set: architecture, api-reference, ingestion, file-formats, semantic-layer, payload-reference, security, deployment, firefly-intelligence-system
- CI: `publish-sdk-python` + `publish-sdk-java` workflows (tag-triggered)

## [26.5.1] - 2026-05-23

### Added
- Query pipeline shipped
- Examples + Glossary CRUD with auto-promotion (AGENT_LEARNED → PROPOSED)
- Semantic layer: MetricFlow-shape YAML + compiler + history versioning
- Hybrid retriever (BM25 + pgvector + RRF) + cross-encoder reranker over schema KB
- 4-agent query pipeline: GroundingAgent → GenerationAgent → CriticAgent → ExplainerAgent
- AST classifier + ScopeGuard (sqlglot + table-kind enforcement + dataset allowlist)
- DuckDB executor (in-process, ATTACH parquet snapshots, row_cap+1 overflow)
- POST /api/v1/query + :explain + :validate + /query/stream (SSE with clarification frame)
- Conversation memory with drill-down (prior executed_sql + table_qnames + snapshot_pins)
- POST /api/v1/sql:execute behind workspace.allow_direct_sql
- POST /api/v1/tables:derive + DML on DERIVED tables (read-modify-write Parquet)
- Agent-tier mirrors: /api/v1/agent/{query,sql:execute,examples}

## [26.5.0] - 2026-05-23

### Added
- Foundation shipped: bootable service, lock-step modules,
  full RLS-enabled Postgres schema (~20 tables), workspace + dataset
  CRUD, agent-token mint/verify, ObjectStore port + LocalFs + S3
  adapters, CI workflows.

## [26.6.0] - 2026-06-01

### Added
- Foundation scaffold: pyproject + pyfly.yaml + Dockerfile + Taskfile
- Lock-step modules from canon: `web/conventions/*`,
  `web/agent_deps.py`, `web/openapi_override.py`,
  `core/agents/builder.py`, `core/observability/__init__.py`,
  `core/services/auth/{agent_token_service,redis_rate_limiter}.py`,
  `web/controllers/agent_tokens_controller.py`
- Full Alembic schema (~20 tables) with admin/app role split
  + RLS forced on every multi-tenant table
- `flyquery_workspaces` + `flyquery_datasets` CRUD with RLS isolation
- Agent-token mint/list/revoke + flyquery scope catalog
- `ObjectStore` port + `LocalFs` + `S3` adapters
- `scripts/check_lockstep.py` CI gate
