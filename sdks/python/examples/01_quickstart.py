#!/usr/bin/env python
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

"""End-to-end quickstart: workspace + dataset + bulk upload + batch query.

Run against a local flyquery (``docker compose up`` + ``uvicorn
flyquery.main:app``) on port 8520. Uses synthetic fixtures under ``../../../examples``. Configure
a tenant, workspace and model providers before running it.

Usage::

    python sdks/python/examples/01_quickstart.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from flyquery_sdk.client import FlyqueryClient

ROOT_FIXTURES = Path(__file__).resolve().parent.parent.parent.parent / "examples"


async def main() -> None:
    async with FlyqueryClient(
        base_url=os.environ.get("FLYQUERY_URL", "http://127.0.0.1:8520"),
        tenant_id=os.environ["FLYQUERY_TENANT_ID"],
        workspace_id=os.environ["FLYQUERY_WORKSPACE_ID"],
    ) as fly:
        ds = await fly.find_or_create_dataset(
            "quickstart",
            description="Synthetic CSV / JSON / XLSX / Parquet from examples/.",
        )
        print(f"dataset   = {ds.id}")

        # --- bulk upload every example fixture ---
        outcome = await fly.upload_directory(str(ds.id), str(ROOT_FIXTURES))
        print(f"\nbulk-upload: {outcome.succeeded}/{outcome.total_files} succeeded")
        for r in outcome.results:
            print(f"  - {r.original_filename:35s} {r.status:>6s}  ({len(r.tables)} tables)")

        # --- batch query ---
        batch = await fly.ask_batch(
            str(ds.id),
            [
                "How many customers do we have?",
                "What is the total revenue across all orders?",
                "What is the most common event type in the logs?",
            ],
        )
        print(f"\nbatch-query: {batch.succeeded}/{batch.total_queries} succeeded")
        for r in batch.results:
            sql = (r.sql or "").split("\n", 1)[0][:100]
            print(f"  #{r.index} {r.status:>6s}: {sql}")
            if r.explanation:
                print(f"      → {r.explanation[:150]}")


if __name__ == "__main__":
    asyncio.run(main())
