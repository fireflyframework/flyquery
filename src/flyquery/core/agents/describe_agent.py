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

"""DescribeAgent — generates business-friendly descriptions + synonyms for columns.

Used in Stage 7 to populate description + synonyms_json for columns where
description IS NULL. Runs in batches capped by FLYQUERY_DESCRIBE_BATCH.
Cost is tracked per run and stops when FLYQUERY_DESCRIBE_BUDGET_CENTS_PER_RUN
is hit.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from flyquery.core.agents.builder import build_agent

# Semantic type taxonomy. Each ingested column gets one of these
# classifications, written by the DescribeAgent alongside the
# business description + synonyms. The grounding agent, explainer,
# and SDK clients use it to render results properly (e.g. format a
# ``currency`` column with the right separator, show a ``percentage``
# with %, plot a ``date`` on a time axis, treat ``iban`` as
# PII-sensitive).
#
# The taxonomy is curated -- it leaves out long-tail physical units
# (temperature / weight / volume) because those rarely show up in
# the BvD / SaaS exports flyquery targets, and adding them dilutes
# the LLM's choice space. Add to this list deliberately, then update
# the YAML prompt + bump the prompt ``version``.
SemanticType = Literal[
    # --- General text -------------------------------------------------
    "text",  # free-form short strings, labels, captions
    "name",  # person / organization names
    "description",  # long narrative text, multi-sentence
    "tag",  # short categorical labels, open set
    "enum",  # categorical, closed set
    "language_code",  # ISO 639 (``en``, ``es``)
    # --- Identifiers --------------------------------------------------
    "identifier",  # UUID, surrogate keys, generic IDs
    "code",  # alphanumeric business codes (SKU, ISIN, GICS)
    "tax_id",  # national tax / VAT / company-registration IDs
    "iban",  # IBAN bank-account identifiers
    "version",  # SemVer / CalVer / build numbers
    # --- Quantities ---------------------------------------------------
    "integer",  # arbitrary integer values
    "count",  # counts of discrete things (rows, items, events)
    "decimal",  # arbitrary decimals (no business meaning)
    "score",  # composite scores (risk, sentiment, KPI)
    "ratio",  # 0-1 unitless fractions
    "percentage",  # 0-100 values labelled as %
    "rate",  # interest / FX / discount rates (often %)
    # --- Money --------------------------------------------------------
    "amount",  # monetary value WITHOUT explicit currency col
    "currency",  # monetary value WITH explicit currency col
    "currency_code",  # ISO 4217 (``USD``, ``EUR``)
    # --- Time ---------------------------------------------------------
    "date",  # calendar date (no time)
    "datetime",  # timestamp with time component
    "time",  # clock time without date
    "year",  # year only (``2024``)
    "quarter",  # quarter bucket (``Q1 2024``, ``2024-Q1``)
    "month",  # month bucket
    "week",  # week bucket (ISO week)
    "duration",  # minutes / days / months span
    "timezone",  # IANA timezone string
    # --- Boolean ------------------------------------------------------
    "boolean",  # true/false, yes/no
    "flag",  # boolean-ish status (active/inactive, on/off)
    # --- Contact ------------------------------------------------------
    "email",  # email address
    "phone",  # phone number
    "url",  # web URL
    "image_url",  # URL that resolves to an image
    "file_path",  # local FS / object-store path
    # --- Geo ----------------------------------------------------------
    "address",  # multi-field street address
    "city",  # city name
    "state",  # state / province / region within a country
    "postal_code",  # ZIP / postcode
    "country",  # country name (long form)
    "country_code",  # ISO 3166 country codes
    "region",  # multi-country region (EMEA, APAC)
    "industry_sector",  # NACE / NAICS / GICS sector classification
    "geo_coordinate",  # latitude / longitude
    # --- Tech ---------------------------------------------------------
    "ip_address",  # IPv4 / IPv6
    "json",  # structured JSON blobs
    # --- Default ------------------------------------------------------
    "unknown",  # truly uncertain; default
]


class DescribedColumn(BaseModel):
    qualified_name: str
    description: str  # 1-2 sentences, business-flavoured
    synonyms: list[str]  # 3-8 alternative business names
    semantic_type: SemanticType = Field(
        default="unknown",
        description=(
            "Business / semantic classification of the column's values. "
            "Lets the explainer + SDK format results properly: an "
            "``amount`` column gets thousand separators, a ``percentage`` "
            "gets a % suffix, a ``date`` is plotted on a time axis. "
            "Distinct from the storage ``data_type`` (VARCHAR / DOUBLE / "
            "TIMESTAMP) -- two DOUBLE columns can be ``amount`` vs "
            "``percentage`` vs ``rate`` with very different presentation."
        ),
    )


class DescribedObjects(BaseModel):
    columns: list[DescribedColumn]


def build_describe_agent(settings):
    """Build a DescribeAgent for Stage 7.

    Instructions loaded from ``resources/prompts/describe.yaml``.
    """
    from flyquery.core.agents.prompt_loader import load_prompt

    prompt = load_prompt("describe")
    return build_agent(
        name="flyquery-describe",
        model=settings.describe_model,
        output_type=DescribedObjects,
        instructions=prompt.instructions,
        settings=settings,
        # Deterministic descriptions/semantic types: identical columns on
        # re-ingest must produce identical metadata, no schema-change churn.
        extra_settings={"temperature": 0.0},
    )
