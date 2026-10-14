# flyquery — Quality

## Table of Contents

1. [Testing strategy overview](#1-testing-strategy-overview)
2. [Unit tests](#2-unit-tests)
3. [Integration tests](#3-integration-tests)
4. [Object-store conformance tests](#4-object-store-conformance-tests)
5. [File-format parser fixtures](#5-file-format-parser-fixtures)
6. [Pipeline tests](#6-pipeline-tests)
7. [LLM-gated tests](#7-llm-gated-tests)
8. [Lock-step drift CI gate](#8-lock-step-drift-ci-gate)
9. [Agent test mocking notes](#9-agent-test-mocking-notes)
10. [Running the test suite](#10-running-the-test-suite)

---

## 1. Testing strategy overview

| Test category | Mark | What it tests | External deps |
|---------------|------|--------------|--------------|
| Unit | (none / `not integration`) | Domain logic, agent outputs (mocked LLM), in-memory stores | None |
| Integration | `integration` | Full stack against real Postgres + pgvector | testcontainers `pgvector/pgvector:pg16` |
| S3 adapter | `s3` | S3 ObjectStore adapter | MinIO (testcontainers) |
| GCS adapter | `gcs` | GCS ObjectStore adapter | fake-gcs-server |
| Azure Blob adapter | `azure_blob` | Azure Blob ObjectStore adapter | Azurite |
| LLM-gated | `llm` | Real LLM calls | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |
| Parser fixtures | `integration` | Per-format FileReader + edge cases | testcontainers Postgres |
| Pipeline tests | `integration` | End-to-end ingest + query | testcontainers Postgres |

Default CI run excludes `llm`, `s3`, `gcs`, `azure_blob`. Everything else runs.

---

## 2. Unit tests

Location: `tests/unit/`

Run: `uv run pytest tests/unit/ -m 'not llm and not integration' --tb=short -q`

### Coverage targets

- **Domain models** (`core/models/`): Pydantic schema validation, field
  constraints, UUID generation.
- **Agent output parsing**: Each agent's `output_type` is validated against
  malformed LLM responses. Agents are called with a `MagicMock` that returns
  a canned structured output.
- **AST classifier**: Each firewall rule is tested against a SQL snippet.
  Tests cover: multi-statement, DDL, INSERT on UPLOADED table, DML on DERIVED
  without scope, table outside allowlist, forbidden DuckDB function.
- **Scope guard**: Permission intersection logic for all scope combinations.
- **PII scanner (regex)**: Pattern coverage for EMAIL, PHONE, SSN,
  CREDIT_CARD, IP_ADDRESS, DOB. False-positive rate tests on numeric columns.
- **RRF fusion**: Known rank lists fused with known k produce expected
  fusion scores.
- **SemanticCompiler**: MetricFlow YAML → DuckDB SQL for each metric type
  (SIMPLE, RATIO, DERIVED, CUMULATIVE).
- **IngestWorker state machine**: Status transitions, cooperative cancel flag
  detection, heartbeat update.

### In-memory substitutes

| Real component | Unit test substitute |
|---------------|---------------------|
| Postgres + pgvector | SQLite in-memory + pgvector shim |
| ObjectStore | `InMemoryObjectStore` (stores bytes in a dict) |
| DuckDB executor | `MockDuckDBAdapter` (returns canned results) |
| LLM agents | `MagicMock` returning canned `output_type` instances |
| Redis | In-memory dict-based `MemoryIdempotencyStore` |

---

## 3. Integration tests

Location: `tests/integration/`

Run: `uv run pytest tests/integration/ -m 'integration and not llm and not s3 and not gcs and not azure_blob' --tb=short -q`

### Setup

Tests use `pytest-asyncio` + `testcontainers` to spin up a real Postgres
with pgvector:

```python
@pytest.fixture(scope="session")
async def postgres():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        # Run migrations as flyquery_admin
        await run_alembic(admin_url=pg.get_admin_url())
        # Yield connection URL for flyquery_app role
        yield pg.get_connection_url(user="flyquery_app", password="test")
```

**Critical:** The testcontainers default user is `SUPERUSER` (BYPASSRLS).
Integration tests that validate RLS isolation must explicitly use the
`flyquery_app` role. See
[security-model.md § 3](security-model.md#3-postgres-role-split-and-rls).

### RLS isolation tests

```python
@pytest.mark.integration
async def test_rls_cross_tenant_isolation(db_session_tenant_a, db_session_tenant_b):
    # Create a dataset in tenant A
    ds_a = await create_dataset(db_session_tenant_a, name="tenant-a-data")
    
    # Confirm tenant B cannot see it
    datasets_b = await list_datasets(db_session_tenant_b)
    assert ds_a.id not in [d.id for d in datasets_b]
```

### Workspace + dataset CRUD

Full lifecycle tests: create workspace → create dataset → upload file →
check `flyquery_files.status=RECEIVED` → verify RLS → archive dataset →
verify archived dataset is not returned in default list.

### Agent token tests

Mint token → verify with correct secret → verify failure with wrong secret →
check scope enforcement → revoke → verify revoked token fails.

---

## 4. Object-store conformance tests

Location: `tests/integration/object_store/`

Each ObjectStore adapter must pass the shared conformance test pack:

```python
@pytest.mark.parametrize("store", ["local_fs", "s3", "gcs", "azure_blob"])
async def test_put_get_round_trip(store):
    ...

async def test_head_after_put(store): ...
async def test_delete(store): ...
async def test_list_prefix(store): ...
async def test_presign_get(store): ...
async def test_copy(store): ...
async def test_kms_round_trip(store): ...      # skipped for local_fs
async def test_concurrent_puts(store): ...     # 10 concurrent puts to distinct keys
async def test_large_file_streaming(store): ...  # 100 MB streaming put/get
```

S3, GCS, and Azure Blob tests are marked `@pytest.mark.s3`,
`@pytest.mark.gcs`, `@pytest.mark.azure_blob` respectively and are skipped
in the default CI run.

MinIO runs via testcontainers for S3; `fake-gcs-server` for GCS; Azurite for
Azure Blob.

---

## 5. File-format parser fixtures

Location: `tests/integration/parsers/`

For each format, the fixture set contains:

| Fixture type | Content |
|-------------|---------|
| `happy` | Well-formed minimal file; verifies table count and column types |
| `bom_utf8` | UTF-8 BOM; must not appear in column names (CSV/TSV) |
| `mixed_quotes` | Mixed quoting styles in CSV |
| `merged_cell_title_rows` | XLSX with 1–3 merged-cell title rows to skip |
| `multi_sheet` | XLSX with 3 sheets; expects 3 tables |
| `ragged_json` | JSON with unequal record lengths |
| `schema_drift` | Two versions of the same table for reconcile testing |
| `encoding_misdetect` | Latin-1 file with chardet ambiguity |
| `zip_bomb` | ZIP with decompressed size > cap; must be rejected |
| `gzip_pass_through` | .gz CSV; must unwrap and parse correctly |

Each format must pass all applicable fixtures. Any failure is a regression.

### Edge cases of note

- **XLSX merged title rows**: `FLYQUERY_MAX_TITLE_ROWS=3` controls how many
  leading rows are skipped. The fixture `merged_cell_title_rows` has 2 title
  rows followed by the real header.
- **ZIP with multiple entries**: `zip_multi_entry` fixture contains 2 files;
  must be rejected with `ZIP_MULTI_ENTRY` error code.
- **Zip bomb**: decompressed size > `FLYQUERY_MAX_FILE_MB`; must be rejected
  before full decompression.

---

## 6. Pipeline tests

Location: `tests/integration/pipeline/`

Uses a Northwind-style fixture: 4 CSVs (orders, customers, products, employees).

### Test scenarios

| Scenario | What it verifies |
|----------|----------------|
| First-upload happy path | 10-stage completion, snapshot READY, table queryable |
| Re-upload column added | Stage 3 ADDED diff, annotation transplant, new snapshot |
| Re-upload column renamed (ambiguous) | `RENAMED_CANDIDATE` flow, `RenameDetectionAgent` invoked |
| Conversation drill-down | Prior `executed_sql` + `table_qnames` + `snapshot_pins` carry forward |
| Semantic-layer metric usage | `SEMANTIC_LAYER` path taken when metric matches question |
| Write rejected on ingested table | `REJECTED_BY_FIREWALL` on INSERT against UPLOADED table |
| Write allowed on derived table | DML succeeds with `flyquery.derived:write` scope |
| Direct SQL gated by `allow_direct_sql` | `POST /sql:execute` returns 422 when workspace flag = false |

### Conversation drill-down test (key scenario)

```python
@pytest.mark.integration
async def test_drill_down_carries_context(client, northwind_dataset):
    # Turn 1
    conv = await client.conversations.create(dataset_id=northwind_dataset.id)
    r1 = await client.conversations.turn(conv.conversation_id,
                                          question="Total revenue by region")
    assert "region" in r1.executed_sql.lower()
    
    # Turn 2: drill-down — GenerationAgent should add WHERE, not rewrite
    r2 = await client.conversations.turn(conv.conversation_id,
                                          question="Now for Q2 only")
    assert "WHERE" in r2.executed_sql or "where" in r2.executed_sql
    # The prior SQL structure should be preserved (delta, not full rewrite)
    assert "region" in r2.executed_sql.lower()
```

---

## 7. LLM-gated tests

Location: `tests/integration/` (marked `@pytest.mark.llm`)

These tests call real LLM APIs. They are excluded from the default CI run
and run in a separate nightly job.

### What they test

- **GroundingAgent output quality**: Given a realistic schema metadata context
  and a question, the agent selects the correct tables and columns.
- **GenerationAgent correctness**: Generated SQL executes without error
  against the Northwind fixture and returns plausible results.
- **CriticAgent repair**: A deliberately broken SQL is presented with an error
  message; the agent returns a corrected SQL that passes execution.
- **DescribeAgent coverage**: All columns from a 20-column batch receive
  non-empty descriptions that mention the data type.
- **RelationProposerAgent discovery**: The Northwind `customer_id` →
  `customers.id` join is discovered with confidence > 0.7.

### Running locally

```bash
ANTHROPIC_API_KEY=<key> uv run pytest tests/integration/ -m llm --tb=short -q
```

---

## 8. Lock-step drift CI gate

`scripts/check_lockstep.py` checks nineteen normalized historical baselines
and two reviewed service-specific variants. It does not compare live canon
or radar repositories. See the [source-contract scope](architecture.md#9-lock-step-modules)
for the manifest and provenance.

```bash
# Run manually
python scripts/check_lockstep.py
# Exit 1 on source drift or an invalid variant manifest.
```

See [cicd.md](cicd.md) for the workflow configuration.

---

## 9. Agent test mocking notes

**Per the `agent_test_mocking` memory**: `MagicMock(stream.usage())` and
`MagicMock(result.usage())` cause arithmetic errors in the cost-tracking
middleware because `MagicMock` objects don't support numeric operations.

**Correct pattern:**

```python
from unittest.mock import AsyncMock, MagicMock

def mock_agent_result(output):
    result = MagicMock()
    result.data = output
    result.usage.return_value = None   # ← MUST be None or a real Usage object
    return result

# In a test:
grounding_agent = MagicMock()
grounding_agent.run = AsyncMock(return_value=mock_agent_result(
    GroundedContext(path="SYNTHESIS", tables=[...], confidence=0.9, ...)
))
```

If you forget to set `usage.return_value = None`, tests will fail with
`TypeError: unsupported operand type(s) for +: 'MagicMock' and 'int'` in
the cost-tracking middleware.

---

## 10. Running the test suite

```bash
# Fast feedback (no external deps)
task test:unit
# Equivalent: uv run pytest tests/unit/ -m 'not llm and not integration' -q

# Full integration (requires Docker for testcontainers)
task test:integration
# Equivalent: uv run pytest tests/integration/ -m 'integration and not llm and not s3 and not gcs and not azure_blob' -q

# With S3 (requires MinIO via Docker or AWS credentials)
uv run pytest tests/integration/object_store/ -m s3 -q

# LLM-gated (requires API keys)
ANTHROPIC_API_KEY=<key> OPENAI_API_KEY=<key> uv run pytest tests/ -m llm -q

# Full suite (slow; includes all marks)
uv run pytest tests/ --tb=short -q

# Check that currently-passing tests still pass before committing:
uv run pytest tests/ -m 'not llm and not s3 and not gcs and not azure_blob' --tb=no -q | tail -3
```
