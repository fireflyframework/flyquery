# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""PII outside the sampled prefix must not bypass the profile boundary."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from flyquery.core.services.ingestion.stages import pii_tag


@pytest.mark.parametrize(
    "policy,scanner", [("redact", "regex"), ("reject", "regex"), ("warn", "regex"), ("redact", "disabled")]
)
async def test_profile_values_are_classified_before_retrieval(monkeypatch, policy, scanner):
    samples = [f"ordinary-{i}" for i in range(8)]
    column_id = uuid.uuid4()
    monkeypatch.setattr(
        pii_tag,
        "_load_columns",
        AsyncMock(
            return_value=[
                {
                    "id": column_id,
                    "qualified_name": "records.note",
                    "sample_values_json": samples,
                    "description": "Synthetic text",
                    "data_type": "VARCHAR",
                    "profile_json": {
                        "top_values": [{"value": v} for v in samples + ["fixture@example.test"]]
                    },
                }
            ]
        ),
    )
    apply = AsyncMock()
    monkeypatch.setattr(pii_tag, "_apply_tag_and_policy", apply)
    result = await pii_tag.run_pii_tag(
        tenant_id="native",
        snapshot_id=uuid.uuid4(),
        session_factory=Mock(),
        settings=SimpleNamespace(pii_scanner=scanner, pii_policy_samples=policy),
    )
    if scanner == "disabled":
        assert result["columns_tagged"] == 0
        apply.assert_not_awaited()
    else:
        assert result["columns_tagged"] == 1
        assert apply.await_args.kwargs["tag_name"] == "EMAIL"
        assert apply.await_args.kwargs["policy"] == policy
