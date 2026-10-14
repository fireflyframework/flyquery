# Copyright 2024-2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for HybridRetriever + SearchIndex."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


class _FixedEmbedder:
    """Deterministic embedder that returns a fixed 1536-dim vector."""

    async def embed(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.1] * 1536

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1536 for _ in texts]


class _NullEmbedder:
    """Embedder that always returns None (simulates missing API key)."""

    async def embed(self, text: str) -> None:  # noqa: ARG002
        return None

    async def embed_batch(self, texts: list[str]) -> list[None]:
        return [None] * len(texts)


async def _seed_table_with_column(
    s: AsyncSession,
    *,
    tenant: str,
    ws_id: uuid.UUID,
    ds_id: uuid.UUID,
    tbl_id: uuid.UUID,
    tbl_name: str,
    col_qname: str,
    tsv_text: str,
    embedding: list[float] | None = None,
) -> None:
    """Insert a table + snapshot + single schema_object column row.

    Uses the admin session (no RLS) so callers don't need to fiddle with
    session-variable plumbing.  All NOT NULL constraints are satisfied.
    """
    snap_id = uuid.uuid4()
    await s.execute(
        sa.text(
            "INSERT INTO flyquery_tables "
            "    (id, tenant_id, workspace_id, dataset_id, name, qualified_name, kind, is_active) "
            "VALUES (:id, :t, :ws, :ds, :name, :qname, 'UPLOADED', true)"
        ),
        {"id": tbl_id, "t": tenant, "ws": ws_id, "ds": ds_id, "name": tbl_name, "qname": tbl_name},
    )
    await s.execute(
        sa.text(
            "INSERT INTO flyquery_schema_snapshots "
            "    (id, tenant_id, workspace_id, dataset_id, table_id, "
            "     snapshot_hash, n_columns, status, triggered_by, created_by) "
            "VALUES (:id, :t, :ws, :ds, :tbl, :hash, 1, 'READY', 'USER', 'test')"
        ),
        {"id": snap_id, "t": tenant, "ws": ws_id, "ds": ds_id, "tbl": tbl_id, "hash": "testhash"},
    )
    # Publish: point the table at this snapshot. Retrieval is scoped to
    # ``current_snapshot_id`` (so re-ingests don't return stale/duplicate
    # columns), so a seeded table must have its current snapshot set -- exactly
    # as the publish stage does in real ingestion.
    await s.execute(
        sa.text("UPDATE flyquery_tables SET current_snapshot_id = :snap WHERE id = :tbl"),
        {"snap": snap_id, "tbl": tbl_id},
    )
    if embedding is not None:
        vec = str(embedding)
        await s.execute(
            sa.text(
                """
                INSERT INTO flyquery_schema_objects
                    (tenant_id, workspace_id, table_id, snapshot_id,
                     kind, qualified_name, source_hash, is_active,
                     content_tsv, embedding)
                VALUES
                    (:t, :ws, :tbl, :snap,
                     'COLUMN', :qname, :hash, true,
                     to_tsvector('english', :tsv_text),
                     CAST(:emb AS vector))
                """
            ),
            {
                "t": tenant,
                "ws": ws_id,
                "tbl": tbl_id,
                "snap": snap_id,
                "qname": col_qname,
                "hash": "colhash",
                "tsv_text": tsv_text,
                "emb": vec,
            },
        )
    else:
        await s.execute(
            sa.text(
                """
                INSERT INTO flyquery_schema_objects
                    (tenant_id, workspace_id, table_id, snapshot_id,
                     kind, qualified_name, source_hash, is_active,
                     content_tsv)
                VALUES
                    (:t, :ws, :tbl, :snap,
                     'COLUMN', :qname, :hash, true,
                     to_tsvector('english', :tsv_text))
                """
            ),
            {
                "t": tenant,
                "ws": ws_id,
                "tbl": tbl_id,
                "snap": snap_id,
                "qname": col_qname,
                "hash": "colhash",
                "tsv_text": tsv_text,
            },
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bm25_only_retrieval(started_app: None) -> None:  # noqa: ARG001
    """BM25-only branch returns hits when schema objects exist."""
    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from flyquery.core.services.retrieval.hybrid_retriever import HybridRetriever
    from flyquery.core.services.retrieval.search_index import SearchIndex

    # Use admin URL (BYPASSRLS) for seeding; app URL for retrieval (mirrors runtime).
    admin_url = os.environ["FLYQUERY_DATABASE_URL_ADMIN"].replace("+psycopg", "+asyncpg")
    db_url = os.environ["FLYQUERY_DATABASE_URL"]
    seed_engine = create_async_engine(admin_url)
    engine = create_async_engine(db_url)
    seed_factory = async_sessionmaker(seed_engine, expire_on_commit=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    tenant = "ten-hybrid"
    ws_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    tbl_id = uuid.uuid4()

    # --- seed workspace + dataset + table + schema_object (admin role bypasses RLS) ---
    async with seed_factory() as s, s.begin():
        await s.execute(
            sa.text(
                "INSERT INTO flyquery_workspaces (id, tenant_id, slug, name, status) "
                "VALUES (:id, :t, :slug, :name, 'ACTIVE')"
            ),
            {"id": ws_id, "t": tenant, "slug": f"hw-{ws_id}", "name": "Hybrid WS"},
        )
        await s.execute(
            sa.text(
                "INSERT INTO flyquery_datasets (id, tenant_id, workspace_id, name, status, drift_policy) "
                "VALUES (:id, :t, :ws, :name, 'ACTIVE', 'WARN')"
            ),
            {"id": ds_id, "t": tenant, "ws": ws_id, "name": "Hybrid DS"},
        )
        await _seed_table_with_column(
            s,
            tenant=tenant,
            ws_id=ws_id,
            ds_id=ds_id,
            tbl_id=tbl_id,
            tbl_name="orders",
            col_qname="orders.total",
            tsv_text="revenue total money sales",
        )
    await seed_engine.dispose()

    async with factory() as session:
        # RLS requires app.tenant_id + app.workspace_id GUCs to be set.
        await session.execute(sa.text(f"SET LOCAL app.tenant_id = '{tenant}'"))
        await session.execute(sa.text(f"SET LOCAL app.workspace_id = '{ws_id}'"))
        idx = SearchIndex(session)
        retriever = HybridRetriever(idx, _NullEmbedder())
        bundle = await retriever.retrieve(
            "total revenue",
            dataset_id=ds_id,
            workspace_id=ws_id,
        )

    assert isinstance(bundle, dict)
    assert "schema_objects" in bundle
    # At least the seeded column should appear (BM25 matches "total revenue")
    assert len(bundle["schema_objects"]) >= 1
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_retrieval_with_embedder(started_app: None) -> None:  # noqa: ARG001
    """Hybrid branch (BM25 + vector) merges results via RRF."""
    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from flyquery.core.services.retrieval.hybrid_retriever import HybridRetriever
    from flyquery.core.services.retrieval.search_index import SearchIndex

    admin_url = os.environ["FLYQUERY_DATABASE_URL_ADMIN"].replace("+psycopg", "+asyncpg")
    db_url = os.environ["FLYQUERY_DATABASE_URL"]
    seed_engine = create_async_engine(admin_url)
    engine = create_async_engine(db_url)
    seed_factory = async_sessionmaker(seed_engine, expire_on_commit=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    tenant = "ten-hybrid2"
    ws_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    tbl_id = uuid.uuid4()

    async with seed_factory() as s, s.begin():
        await s.execute(
            sa.text(
                "INSERT INTO flyquery_workspaces (id, tenant_id, slug, name, status) "
                "VALUES (:id, :t, :slug, :name, 'ACTIVE')"
            ),
            {"id": ws_id, "t": tenant, "slug": f"hv-{ws_id}", "name": "HybVec WS"},
        )
        await s.execute(
            sa.text(
                "INSERT INTO flyquery_datasets (id, tenant_id, workspace_id, name, status, drift_policy) "
                "VALUES (:id, :t, :ws, :name, 'ACTIVE', 'WARN')"
            ),
            {"id": ds_id, "t": tenant, "ws": ws_id, "name": "HybVec DS"},
        )
        await _seed_table_with_column(
            s,
            tenant=tenant,
            ws_id=ws_id,
            ds_id=ds_id,
            tbl_id=tbl_id,
            tbl_name="sales",
            col_qname="sales.amount",
            tsv_text="amount money total",
            embedding=[0.1] * 1536,
        )
    await seed_engine.dispose()

    async with factory() as session:
        await session.execute(sa.text(f"SET LOCAL app.tenant_id = '{tenant}'"))
        await session.execute(sa.text(f"SET LOCAL app.workspace_id = '{ws_id}'"))
        idx = SearchIndex(session)
        retriever = HybridRetriever(idx, _FixedEmbedder())
        bundle = await retriever.retrieve(
            "total amount",
            dataset_id=ds_id,
            workspace_id=ws_id,
        )

    assert len(bundle["schema_objects"]) >= 1
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_glossary_terms_appear_in_bundle(started_app: None) -> None:  # noqa: ARG001
    """Glossary terms seeded in the workspace appear in the retrieved bundle."""
    import os

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from flyquery.core.services.retrieval.hybrid_retriever import HybridRetriever
    from flyquery.core.services.retrieval.search_index import SearchIndex

    admin_url = os.environ["FLYQUERY_DATABASE_URL_ADMIN"].replace("+psycopg", "+asyncpg")
    db_url = os.environ["FLYQUERY_DATABASE_URL"]
    seed_engine = create_async_engine(admin_url)
    engine = create_async_engine(db_url)
    seed_factory = async_sessionmaker(seed_engine, expire_on_commit=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    tenant = "ten-glossary"
    ws_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    tbl_id = uuid.uuid4()

    async with seed_factory() as s, s.begin():
        await s.execute(
            sa.text(
                "INSERT INTO flyquery_workspaces (id, tenant_id, slug, name, status) "
                "VALUES (:id, :t, :slug, :name, 'ACTIVE')"
            ),
            {"id": ws_id, "t": tenant, "slug": f"gl-{ws_id}", "name": "Glossary WS"},
        )
        await s.execute(
            sa.text(
                "INSERT INTO flyquery_datasets (id, tenant_id, workspace_id, name, status, drift_policy) "
                "VALUES (:id, :t, :ws, :name, 'ACTIVE', 'WARN')"
            ),
            {"id": ds_id, "t": tenant, "ws": ws_id, "name": "Glossary DS"},
        )
        # Seed a schema object so schema retrieval does not error
        await _seed_table_with_column(
            s,
            tenant=tenant,
            ws_id=ws_id,
            ds_id=ds_id,
            tbl_id=tbl_id,
            tbl_name="orders",
            col_qname="orders.revenue",
            tsv_text="revenue income earnings",
        )
        # Seed a glossary term
        await s.execute(
            sa.text(
                """
                INSERT INTO flyquery_glossary_terms
                    (id, tenant_id, workspace_id, term, definition,
                     synonyms_json, tags_json, related_columns_json, related_metrics_json)
                VALUES
                    (gen_random_uuid(), :t, :ws, 'revenue',
                     'Total monetary value of all sales in a given period.',
                     '["income","earnings","sales"]'::jsonb, '[]'::jsonb,
                     '[]'::jsonb, '[]'::jsonb)
                """
            ),
            {"t": tenant, "ws": ws_id},
        )
    await seed_engine.dispose()

    async with factory() as session:
        await session.execute(sa.text(f"SET LOCAL app.tenant_id = '{tenant}'"))
        await session.execute(sa.text(f"SET LOCAL app.workspace_id = '{ws_id}'"))
        idx = SearchIndex(session)
        retriever = HybridRetriever(idx, _NullEmbedder())
        bundle = await retriever.retrieve(
            "total revenue",
            dataset_id=ds_id,
            workspace_id=ws_id,
        )

    assert "glossary" in bundle
    assert len(bundle["glossary"]) >= 1
    terms = [h.metadata["term"] for h in bundle["glossary"]]
    assert "revenue" in terms
    await engine.dispose()
