# Copyright 2024-2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
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

"""Stage 9 -- embed: build embedding text per schema object + refresh content_tsv.

For each ``flyquery_schema_objects`` row in the snapshot:

* Build embedding text:
  ``"<qualified_name>: <data_type>\\n<description>\\nSynonyms: <list>"``.
* Call the configured embedding provider via
  :func:`flyquery.core.services.retrieval.embedder.build_embedder`.
  Supported providers (selected by ``settings.embedding_provider``):
  ``ollama``, ``openai``, ``cohere``, ``voyage``, ``azure``,
  ``google``, ``mistral``, ``bedrock``, ``null``.
* Persist ``embedding`` + ``embedding_model`` when a vector was returned.
* Always refresh ``content_tsv`` via PostgreSQL ``to_tsvector`` so
  BM25 retrieval works even when the provider is down or set to
  ``null``.

When the provider is unavailable (missing API key, unreachable
endpoint), the stage logs a warning and writes ``NULL`` vectors --
ingestion does not fail, retrieval gracefully degrades to BM25 over
``content_tsv``.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flyquery.core.services.retrieval.embedder import (
    Embedder,
    NullEmbedder,
    build_embedder,
)

if TYPE_CHECKING:
    from flyquery.config import FlyquerySettings

logger = logging.getLogger(__name__)


async def run_embed(
    *,
    tenant_id: str,
    snapshot_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    settings: FlyquerySettings | None = None,
    embedder: Embedder | None = None,
) -> dict:
    """Execute Stage 9: embed + index.

    Parameters
    ----------
    tenant_id
        Tenant scope for RLS.
    snapshot_id
        Schema snapshot to embed.
    session_factory
        Async sessionmaker for the persistence layer.
    settings
        When provided, used to build the configured embedder via
        :func:`build_embedder`. Optional so existing call sites that
        haven't been updated keep working (they fall back to the
        Null embedder).
    embedder
        Direct embedder override -- used by tests to inject a stub
        without touching settings.

    Returns
    -------
    dict
        ``{embeddings_written, objects_processed, model}``.
    """
    if embedder is None:
        embedder = build_embedder(settings) if settings is not None else NullEmbedder()

    # Load all schema_objects for this snapshot
    async with session_factory() as s:
        result = await s.execute(
            sa.text(
                # profile_json/sample_values_json are pulled in so the embed
                # text (and thus content_tsv) covers the column's actual
                # VALUES, making value-bearing columns retrievable by
                # BM25/vector -- e.g. a question for "Total Revenue" finds
                # the column whose distinct values include it.
                """
                SELECT id, qualified_name, data_type, description, synonyms_json,
                       profile_json, sample_values_json
                FROM flyquery_schema_objects
                WHERE snapshot_id = :sid AND tenant_id = :tenant AND is_active = true
                ORDER BY kind, qualified_name
                """
            ),
            {"sid": snapshot_id, "tenant": tenant_id},
        )
        rows = [dict(r) for r in result.mappings().all()]

    # Batch-embed for throughput: one provider call per snapshot instead
    # of one per row. For tiny snapshots this is the same; for hundreds
    # of columns it cuts wall-clock dramatically.
    embed_texts = [_build_embed_text(row) for row in rows]
    vectors: list[list[float] | None] = await embedder.embed_batch(embed_texts) if rows else []

    embeddings_written = 0
    for row, embed_text, vector in zip(rows, embed_texts, vectors, strict=True):
        if vector is not None:
            embeddings_written += 1
        await _update_object(
            object_id=row["id"],
            embed_vector=vector,
            model_name=embedder.model if vector is not None else None,
            embed_text=embed_text,
            tenant_id=tenant_id,
            session_factory=session_factory,
        )

    logger.info(
        "stage=embed snapshot_id=%s objects=%d embeddings_written=%d model=%s",
        snapshot_id,
        len(rows),
        embeddings_written,
        embedder.model,
    )
    return {
        "embeddings_written": embeddings_written,
        "objects_processed": len(rows),
        "model": embedder.model,
    }


def _build_embed_text(row: dict) -> str:
    parts = [row.get("qualified_name") or ""]
    if row.get("data_type"):
        parts[0] += f": {row['data_type']}"
    if row.get("description"):
        parts.append(row["description"])
    synonyms = row.get("synonyms_json")
    if synonyms:
        if isinstance(synonyms, list):
            parts.append("Synonyms: " + ", ".join(str(s) for s in synonyms))
        elif isinstance(synonyms, dict):
            flat = list(synonyms.values())
            if flat:
                parts.append("Synonyms: " + ", ".join(str(s) for s in flat))
    values = _render_values(row)
    if values:
        parts.append(values)
    return "\n".join(p for p in parts if p)


def _render_values(row: dict, *, max_chars: int = 300) -> str:
    """Compact rendering of a column's actual VALUES for the embed corpus.

    Indexing the values (not just name + description) is what lets a
    question like "Total Revenue" retrieve the column whose distinct set
    contains that literal.

    PII safety: prefer the PII-gated ``sample_values_json`` -- the pii_tag
    stage wipes it to ``[]`` when a redact/reject policy fires, so an empty
    list here means "do not surface raw samples". When no gated samples are
    recorded we may use ``profile_json.top_values``. An explicitly empty
    sample list blocks that fallback, including for low-cardinality data.
    The result is capped to ``max_chars`` either way.
    """
    seen: set[str] = set()
    uniq: list[str] = []

    # Preferred source: PII-gated samples (empty list = intentionally wiped).
    samples = row.get("sample_values_json")
    if samples == []:
        return ""
    if isinstance(samples, list) and samples:
        for v in samples:
            if v is None:
                continue
            s = str(v)
            if s not in seen:
                seen.add(s)
                uniq.append(s)
    else:
        # Fallback: stored distinct set (aggregate, low-cardinality).
        prof = row.get("profile_json")
        top_values = (prof or {}).get("top_values") if isinstance(prof, dict) else None
        for tv in top_values or []:
            v = tv.get("value") if isinstance(tv, dict) else tv
            if v is None:
                continue
            s = str(v)
            if s not in seen:
                seen.add(s)
                uniq.append(s)

    if not uniq:
        return ""
    body = " | ".join(uniq)
    if len(body) > max_chars:
        # Trim on a value boundary so we never emit a half-truncated literal.
        body = body[:max_chars].rsplit("|", 1)[0].strip() + " …"
    return f"Values: {body}"


async def _update_object(
    *,
    object_id: uuid.UUID,
    embed_vector: list[float] | None,
    model_name: str | None,
    embed_text: str,
    tenant_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Persist embedding (if available) + refresh content_tsv."""
    # Build tsvector search text from embed_text (or qualified_name + description)
    tsv_input = embed_text[:4096]  # PostgreSQL tsvector limit guard

    async with session_factory() as s, s.begin():
        if embed_vector is not None:
            # Store the embedding vector as a PostgreSQL vector literal
            vec_str = "[" + ",".join(f"{v:.8f}" for v in embed_vector) + "]"
            await s.execute(
                sa.text(
                    """
                    UPDATE flyquery_schema_objects
                    SET
                        embedding = CAST(:vec AS vector),
                        embedding_model = :model,
                        content_tsv = to_tsvector('english', :tsv_input)
                    WHERE id = :oid AND tenant_id = :tenant
                    """
                ),
                {
                    "vec": vec_str,
                    "model": model_name,
                    "tsv_input": tsv_input,
                    "oid": object_id,
                    "tenant": tenant_id,
                },
            )
        else:
            await s.execute(
                sa.text(
                    """
                    UPDATE flyquery_schema_objects
                    SET content_tsv = to_tsvector('english', :tsv_input)
                    WHERE id = :oid AND tenant_id = :tenant
                    """
                ),
                {
                    "tsv_input": tsv_input,
                    "oid": object_id,
                    "tenant": tenant_id,
                },
            )
