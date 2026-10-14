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

"""Replace FastAPI's auto-generated OpenAPI with pyfly's richer schema.

The pyfly FastAPI adapter registers every controller method behind a
single ``lazy_endpoint(request: Request)`` shim so the DI container can
resolve the controller bean on first hit. The side-effect is that
FastAPI's built-in OpenAPI introspector sees only that shim -- no
request body, no response model, no tags, no docstring.

This module bridges the gap. After the FastAPI app is built we install
a custom ``app.openapi`` callable that:

1. Collects per-route metadata from the original controller signatures
   via pyfly's :class:`ControllerRegistrar.collect_route_metadata`.
2. Renders the spec through pyfly's :class:`OpenAPIGenerator`.
3. Enriches the result with rich global tags (with business +
   technical descriptions) and the OpenAPI ``info`` block we want
   Swagger / ReDoc to display.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from pyfly.context.application_context import ApplicationContext
from pyfly.web.adapters.starlette.controller import ControllerRegistrar
from pyfly.web.openapi import OpenAPIGenerator

logger = logging.getLogger(__name__)


#: Per-tag descriptions rendered on the Swagger / ReDoc landing page.
#: Each entry mixes the business intent with the technical contract so
#: the docs read like a runbook, not just a wire reference.
TAG_DESCRIPTIONS: dict[str, str] = {
    "Sources": (
        "Source intake. The front door for binary content -- DOCX, "
        "XLSX, PPTX, PDF, RTF, ODT/ODS/ODP, HTML, Markdown, plain "
        "text, CSV, TSV, JSON, XML, EPUB, raster images (PNG, JPEG, "
        "GIF, WebP, HEIC, AVIF, TIFF, SVG, BMP) routed through "
        "Tesseract OCR, ZIP / 7Z / TAR / GZ archives expanded inline, "
        "EML / MSG emails decomposed into body + attachments, and "
        "WebVTT / SRT transcripts. The intake pipeline sniffs the "
        "actual media type from magic bytes, runs the binary "
        "normaliser, loads through the per-format SourceLoader, "
        "chunks, embeds, and indexes BM25 + dense vectors keyed by "
        "chunk_id. SHA-256 hashing makes ingestion idempotent on "
        "content."
    ),
    "Knowledge": (
        "Canonical knowledge items. The validated, versioned units "
        "downstream consumers should treat as ground truth. Every "
        "create / update appends a new version row; supersession and "
        "retirement are final transitions. Every lifecycle event is "
        "audited and broadcast on the ``flyquery.knowledge`` topic, "
        "so projections (dashboards, copilots, compliance feeds) "
        "stay in lock-step without polling."
    ),
    "Candidates": (
        "Pre-canonical knowledge proposals. The consolidation stage "
        "feeds source chunks to an LLM (FireflyAgent over "
        "pydantic-ai) that emits structured "
        "CandidateProposals with chunk-anchored citations and a "
        "self-rated confidence score. Operators (or an automated "
        "policy) accept proposals to materialise a new knowledge "
        "version, reject them with a reason, or merge them into "
        "existing items. Every decision flows through the audit log."
    ),
    "Query": (
        "Hybrid search + grounded retrieval-augmented answering. "
        "``/search`` returns the raw RRF-fused hit list (BM25 + "
        "dense vectors). ``/query`` runs the same retrieval, then "
        "asks the configured answer model to write an answer using "
        "ONLY the retrieved chunks -- citations include only the "
        "chunks the model actually relied on. Both surfaces share "
        "the same filter model (source_id, knowledge_item_id, "
        "domain, jurisdiction, tags, statuses)."
    ),
    "Taxonomy": (
        "Domain + jurisdiction taxonomy. Seed inserts one root per "
        ":class:`Domain` value at first boot; callers attach "
        "finer-grained children at runtime (sub-processes, "
        "jurisdiction sub-trees). The tree is read flat in "
        "breadth-first order via the ``depth`` column so the API "
        "round-trip is index-only."
    ),
    "Audit": (
        "Append-only audit log. Every mutation in flyquery "
        "(``source.ingested``, ``knowledge.published``, "
        "``candidate.accepted``, ...) writes a row here with the "
        "actor, the correlation id from the originating request, "
        "and a free-form payload. The same payload is broadcast on "
        "the ``flyquery.audit`` topic for compliance projections."
    ),
    "Version": (
        "Service identity, model selection, and backend choices. "
        "Surfaces the deployed CalVer, the embedding + answer model "
        "ids actually in use, the vector backend (pgvector by "
        "default), and the EDA adapter. Used by smoke tests and "
        "operations dashboards."
    ),
}


def install_openapi(
    app: FastAPI,
    context: ApplicationContext,
    *,
    title: str,
    version: str,
    description: str,
) -> None:
    """Replace ``app.openapi`` with a pyfly-driven generator.

    Cached after the first call -- FastAPI's own ``openapi()`` method
    caches via ``app.openapi_schema`` and our override follows the
    same contract.
    """
    registrar = ControllerRegistrar()
    generator = OpenAPIGenerator(title=title, version=version, description=description)

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        route_metadata = registrar.collect_route_metadata(context)
        spec = generator.generate(route_metadata=route_metadata)

        # Enrich tag entries with human-readable descriptions.
        if spec.get("tags"):
            for tag in spec["tags"]:
                name = tag.get("name")
                if name and name in TAG_DESCRIPTIONS:
                    tag["description"] = TAG_DESCRIPTIONS[name]

        # Add the deployment's contact info + servers + license to
        # the info block so the docs landing page is usable on its
        # own (without a separate page).
        info = spec.setdefault("info", {})
        info.setdefault(
            "contact",
            {
                "name": "Firefly Framework",
                "url": "https://github.com/fireflyframework/flyquery",
            },
        )
        info.setdefault(
            "license",
            {
                "name": "Apache-2.0",
                "url": "https://github.com/fireflyframework/flyquery/blob/main/LICENSE",
            },
        )

        # Servers block: lets Swagger UI's "Try it out" send to the
        # right host without manual editing.
        spec.setdefault(
            "servers",
            [
                {"url": "/", "description": "This service"},
            ],
        )

        app.openapi_schema = spec
        logger.info(
            "openapi schema generated (paths=%d, schemas=%d, tags=%d)",
            len(spec.get("paths", {})),
            len((spec.get("components") or {}).get("schemas", {})),
            len(spec.get("tags", [])),
        )
        return spec

    app.openapi = _custom_openapi  # type: ignore[method-assign]
