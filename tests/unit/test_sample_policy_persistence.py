# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Sampling must preserve a privacy decision before dropping its evidence."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from flyquery.core.services.ingestion.stages import sample


@pytest.mark.parametrize("policy", ["redact", "reject"])
@pytest.mark.parametrize("values", [["fixture@example.test"], ["ordinary", "fixture@example.test"]])
async def test_original_pii_finding_applies_policy_before_sample_persistence(monkeypatch, policy, values):
    column_id = uuid.uuid4()
    monkeypatch.setattr(
        sample,
        "_load_columns",
        AsyncMock(
            return_value=[
                {
                    "id": column_id,
                    "qualified_name": "records.note",
                    "pii_tag": None,
                    "description": "Synthetic text",
                    "data_type": "VARCHAR",
                }
            ]
        ),
    )
    monkeypatch.setattr(sample, "_read_parquet_column", Mock(return_value=values))
    events = []

    async def apply(**kwargs):
        events.append(("policy", kwargs))

    async def persist(*args):
        events.append(("persist", args))

    monkeypatch.setattr(sample, "_apply_tag_and_policy", apply, raising=False)
    monkeypatch.setattr(sample, "_persist_samples", persist)
    await sample.run_sample(
        tenant_id="native",
        snapshot_id=uuid.uuid4(),
        parquet_key="owned.parquet",
        session_factory=Mock(),
        settings=SimpleNamespace(pii_scanner="regex", pii_policy_samples=policy, sample_n=10),
    )
    assert [event[0] for event in events] == ["policy", "persist"]
    assert events[0][1]["tag_name"] == "EMAIL"
    assert events[0][1]["source"] == "REGEX"
    assert events[0][1]["policy"] == policy
    assert events[1][1][1] == []


@pytest.mark.parametrize(
    "policy,scanner,values,expected",
    [
        ("redact", "regex", ["alpha", "beta"], ["alpha", "beta"]),
        ("redact", "disabled", ["fixture@example.test"], ["fixture@example.test"]),
        ("warn", "regex", ["ordinary", "fixture@example.test"], ["ordinary"]),
        ("warn", "regex", ["fixture@example.test"], []),
    ],
)
async def test_sampling_retains_clean_values_and_explicit_opt_out(
    monkeypatch, policy, scanner, values, expected
):
    monkeypatch.setattr(
        sample,
        "_load_columns",
        AsyncMock(
            return_value=[
                {
                    "id": uuid.uuid4(),
                    "qualified_name": "records.note",
                    "pii_tag": None,
                    "description": "Synthetic text",
                    "data_type": "VARCHAR",
                }
            ]
        ),
    )
    monkeypatch.setattr(sample, "_read_parquet_column", Mock(return_value=values))
    persist = AsyncMock()
    apply = AsyncMock()
    monkeypatch.setattr(sample, "_persist_samples", persist)
    monkeypatch.setattr(sample, "_apply_tag_and_policy", apply, raising=False)
    await sample.run_sample(
        tenant_id="native",
        snapshot_id=uuid.uuid4(),
        parquet_key="owned.parquet",
        session_factory=Mock(),
        settings=SimpleNamespace(pii_scanner=scanner, pii_policy_samples=policy, sample_n=10),
    )
    assert persist.await_args.args[1] == expected
    if policy == "warn":
        assert apply.await_args.kwargs["policy"] == "warn"
    else:
        apply.assert_not_awaited()


async def test_previously_tagged_column_denies_profile_fallback_without_reading_file(monkeypatch):
    monkeypatch.setattr(
        sample,
        "_load_columns",
        AsyncMock(
            return_value=[
                {
                    "id": uuid.uuid4(),
                    "qualified_name": "records.note",
                    "pii_tag": "EMAIL",
                    "description": "Synthetic text",
                    "data_type": "VARCHAR",
                }
            ]
        ),
    )
    read = Mock(side_effect=AssertionError("A known PII column must not be sampled"))
    persist = AsyncMock()
    monkeypatch.setattr(sample, "_read_parquet_column", read)
    monkeypatch.setattr(sample, "_persist_samples", persist)
    await sample.run_sample(
        tenant_id="native",
        snapshot_id=uuid.uuid4(),
        parquet_key="owned.parquet",
        session_factory=Mock(),
        settings=SimpleNamespace(pii_scanner="regex", pii_policy_samples="redact", sample_n=10),
    )
    read.assert_not_called()
    assert persist.await_args.args[1] == []
