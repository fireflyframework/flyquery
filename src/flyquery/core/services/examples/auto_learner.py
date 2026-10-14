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

"""AutoLearner: promote first-shot OK runs to AGENT_LEARNED, quality=PROPOSED."""

from __future__ import annotations

import uuid
from typing import Any

from flyquery.interfaces.examples import ExampleCreate


class AutoLearner:
    """Proposes an examples row after a successful first-shot query run.

    Skips when:
    - ``retries > 0`` (query required critic refinement)
    - PII findings were detected in the result
    - the query returned no rows (``row_count`` is 0, when provided)

    Called by QueryService (Phase D) after a successful execution.
    """

    def __init__(self, examples_service: Any) -> None:
        self._service = examples_service

    async def maybe_propose(
        self,
        *,
        tenant_id: str,
        workspace_id: uuid.UUID,
        dataset_id: uuid.UUID | None,
        question: str,
        generated_sql: str,
        retries: int,
        pii_findings: list[Any],
        query_id: uuid.UUID,
        row_count: int | None = None,
    ) -> None:
        """Insert a flyquery_examples row when all criteria pass.

        :param tenant_id: tenant identifier
        :param workspace_id: workspace UUID
        :param dataset_id: optional dataset UUID
        :param question: original NL question
        :param generated_sql: SQL that was executed successfully
        :param retries: number of critic refinement loops (must be 0 to propose)
        :param pii_findings: any PII signals detected (must be empty to propose)
        :param query_id: UUID of the parent query record
        :param row_count: number of rows the query returned; when provided it
            must be > 0 to propose (a valid-but-wrong query returning 0 rows
            would otherwise poison grounding). When ``None`` the row gate is
            skipped to preserve behaviour for callers that do not pass it.
        """
        if retries > 0:
            return
        if pii_findings:
            return
        if row_count is not None and row_count <= 0:
            return
        await self._service.create(
            tenant_id,
            workspace_id,
            ExampleCreate(
                question=question,
                generated_sql=generated_sql,
                dataset_id=dataset_id,
                citations_json={"query_id": str(query_id)},
            ),
            source="AGENT_LEARNED",
            quality="PROPOSED",
            actor="agent",
        )
