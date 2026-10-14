# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Native Parquet-to-PostgreSQL privacy decisions through retrieval."""

import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import duckdb
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flyquery.core.services.ingestion.stages.embed import run_embed
from flyquery.core.services.ingestion.stages.pii_tag import run_pii_tag
from flyquery.core.services.ingestion.stages.profile import run_profile
from flyquery.core.services.ingestion.stages.sample import run_sample
from flyquery.core.services.retrieval.search_index import SearchIndex
from flyquery.models.entities import Base, Dataset, SchemaObject, SchemaSnapshot, Table, Workspace


class _CaptureEmbedder:
    model = "privacy-fixture-no-provider"
    dimensions = 1536

    def __init__(self):
        self.inputs = []

    async def embed_batch(self, inputs):
        self.inputs.extend(inputs)
        return [None] * len(inputs)


@pytest.mark.integration
@pytest.mark.parametrize(
    "policy,scanner,values",
    [
        ("redact", "regex", ["fixture@example.test"]),
        ("reject", "regex", ["fixture@example.test"]),
        ("redact", "regex", ["ordinary", "fixture@example.test"]),
        ("reject", "regex", ["ordinary", "fixture@example.test"]),
        ("warn", "regex", ["fixture@example.test"]),
        ("warn", "regex", ["ordinary", "fixture@example.test"]),
        ("redact", "disabled", ["fixture@example.test"]),
        ("redact", "regex", ["alpha", "beta"]),
        ("redact", "regex", [f"ordinary-{i}" for i in range(8)] + ["fixture@example.test"]),
        ("reject", "regex", [f"ordinary-{i}" for i in range(8)] + ["fixture@example.test"]),
        ("warn", "regex", [f"ordinary-{i}" for i in range(8)] + ["fixture@example.test"]),
        ("redact", "disabled", [f"ordinary-{i}" for i in range(8)] + ["fixture@example.test"]),
    ],
)
async def test_original_pii_decision_survives_profile_and_retrieval(tmp_path, policy, scanner, values):
    path = tmp_path / "original.parquet"
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE fixture(note VARCHAR)")
        connection.executemany("INSERT INTO fixture VALUES (?)", [(value,) for value in values])
        connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(path)])
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    schema = "privacy_" + uuid.uuid4().hex
    url = os.environ["FLYQUERY_DATABASE_URL_ADMIN"].replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema + ",public"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant = "privacy-" + uuid.uuid4().hex
    workspace, dataset, table, snapshot, column = [uuid.uuid4() for _ in range(5)]
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session, session.begin():
            session.add(Workspace(id=workspace, tenant_id=tenant, slug="privacy", name="Privacy"))
            await session.flush()
            session.add(Dataset(id=dataset, tenant_id=tenant, workspace_id=workspace, name="Synthetic"))
            await session.flush()
            session.add(
                Table(
                    id=table,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    dataset_id=dataset,
                    name="records",
                    qualified_name="records",
                    current_snapshot_id=snapshot,
                )
            )
            await session.flush()
            session.add(
                SchemaSnapshot(
                    id=snapshot,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    dataset_id=dataset,
                    table_id=table,
                    snapshot_hash=original,
                    n_columns=1,
                    n_rows_actual=len(values),
                    status="READY",
                    triggered_by="USER",
                    created_by="privacy-fixture",
                )
            )
            await session.flush()
            session.add(
                SchemaObject(
                    id=column,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    table_id=table,
                    snapshot_id=snapshot,
                    kind="COLUMN",
                    qualified_name="records.note",
                    data_type="VARCHAR",
                    description="Synthetic text",
                    is_active=True,
                    source_hash="privacy-fixture",
                )
            )
        settings = SimpleNamespace(
            pii_scanner=scanner, pii_policy_samples=policy, sample_n=8, profile_row_threshold=1000
        )
        arguments = {
            "tenant_id": tenant,
            "snapshot_id": snapshot,
            "session_factory": sessions,
            "settings": settings,
        }
        await run_sample(**arguments, parquet_key=str(path))
        await run_profile(**arguments, parquet_key=str(path), n_rows_actual=len(values))
        await run_pii_tag(**arguments)
        embedder = _CaptureEmbedder()
        await run_embed(tenant_id=tenant, snapshot_id=snapshot, session_factory=sessions, embedder=embedder)
        async with sessions() as session:
            index = SearchIndex(session)
            hits = await index.all_schema_objects(dataset)
            bm25 = await index.bm25_schema_objects("Synthetic", dataset)
            catalog = await index.column_value_catalog(dataset)
            rendered = json.dumps(
                {
                    "inputs": embedder.inputs,
                    "hits": [hit.__dict__ for hit in hits + bm25],
                    "catalog": catalog,
                },
                default=str,
            )
            stored = await session.get(SchemaObject, column)
            tainted = "fixture@example.test" in values
            if scanner == "regex" and tainted and policy in {"redact", "reject"}:
                assert "fixture@example.test" not in rendered
                assert stored.sample_values_json == []
                assert stored.pii_tag == "EMAIL"
                if policy == "reject":
                    assert stored.is_active is False
                    assert not hits and not catalog and not embedder.inputs
            elif scanner == "disabled":
                assert stored.sample_values_json == values[:8]
                assert stored.pii_tag is None
                assert "fixture@example.test" in rendered
            elif policy == "warn":
                assert stored.pii_tag == "EMAIL"
                assert stored.is_active
                assert stored.sample_values_json == [v for v in values[:8] if "@" not in v]
                if any(value.startswith("ordinary") for value in values):
                    assert "fixture@example.test" in rendered
            else:
                assert stored.sample_values_json == values[:8]
                assert stored.pii_tag is None
                assert all(value in rendered for value in values)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
