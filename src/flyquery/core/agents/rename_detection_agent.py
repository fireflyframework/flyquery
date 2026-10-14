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

"""RenameDetectionAgent — Stage 3 deep-dive for ambiguous column renames.

When reconcile finds a removed column that could match multiple new columns
(ambiguous rename candidate), this agent receives:
  - The removed column (name, description, samples)
  - A list of candidate new columns (with description + samples)

It returns a ranked list of RenameProposals. The top proposal is auto-confirmed
if confidence ≥ 0.8; otherwise a RENAMED_CANDIDATE row is written for human review.
"""

from __future__ import annotations

from pydantic import BaseModel

from flyquery.core.agents.builder import build_agent


class RenameProposal(BaseModel):
    removed_column: str
    new_column: str
    confidence: float  # 0..1
    rationale: str


class RenameProposals(BaseModel):
    items: list[RenameProposal]


# Auto-confirm threshold: if top proposal ≥ this confidence, reconcile
# treats it as confirmed without human review.
AUTO_CONFIRM_THRESHOLD = 0.8


def build_rename_detection_agent(settings):
    """Build a RenameDetectionAgent for Stage 3 ambiguous rename resolution.

    Instructions loaded from ``resources/prompts/rename_detection.yaml``.
    """
    from flyquery.core.agents.prompt_loader import load_prompt

    prompt = load_prompt("rename_detection")
    return build_agent(
        name="flyquery-rename-detector",
        model=settings.rename_detect_model,
        output_type=RenameProposals,
        instructions=prompt.instructions,
        settings=settings,
        # Rename detection is a short task; cap output tokens tightly
        max_output_tokens=2048,
        # Deterministic: the same removed/candidate pair must always
        # resolve the same way so re-ingests don't flip-flop renames.
        extra_settings={"temperature": 0.0},
    )
