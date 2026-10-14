# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""The factory must apply the configured cache policy to actual agent runs."""

import pytest
from pydantic_ai.models.test import TestModel

from flyquery.config import FlyquerySettings
from flyquery.core.agents.builder import build_agent


class RecordingModel(TestModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings_seen = []

    async def request(self, messages, model_settings, model_request_parameters):
        self.settings_seen.append(dict(model_settings or {}))
        return await super().request(messages, model_settings, model_request_parameters)


def _agent(model):
    return build_agent(
        name="cache-policy-fixture",
        model=model,
        output_type=str,
        instructions="Static synthetic instructions",
        settings=FlyquerySettings(),
    )


async def test_enabled_cache_changes_real_run_settings_without_caching_messages_or_results(monkeypatch):
    monkeypatch.setenv("FLYQUERY_PROMPT_CACHE", "on")
    model = RecordingModel(model_name="claude-sonnet-4-6", custom_output_text="fixture response")
    agent = _agent(model)
    first = await agent.run("Synthetic tenant-one input")
    second = await agent.run("Synthetic tenant-two input", message_history=first.all_messages())
    assert first.output == second.output == "fixture response"
    assert len(model.settings_seen) == 2
    for settings in model.settings_seen:
        assert settings["anthropic_cache_instructions"] == "5m"
        assert "anthropic_cache_messages" not in settings
        assert "anthropic_cache_tool_definitions" not in settings
        assert "openai_prompt_cache_key" not in settings
    names = [type(middleware).__name__ for middleware in agent._middleware]
    assert names.count("PromptCacheMiddleware") == 1
    assert names.count("LoggingMiddleware") == 1
    assert names.count("ObservabilityMiddleware") <= 1


@pytest.mark.parametrize("disabled", ["off", "0", "false", "no", " OFF "])
async def test_switch_is_read_for_each_factory_call_and_disabled_has_no_cache_settings(monkeypatch, disabled):
    monkeypatch.setenv("FLYQUERY_PROMPT_CACHE", "on")
    first_model = RecordingModel(model_name="claude-sonnet-4-6", custom_output_text="first")
    await _agent(first_model).run("Synthetic first input")
    monkeypatch.setenv("FLYQUERY_PROMPT_CACHE", disabled)
    second_model = RecordingModel(model_name="claude-sonnet-4-6", custom_output_text="second")
    await _agent(second_model).run("Synthetic second input")
    assert first_model.settings_seen[0]["anthropic_cache_instructions"] == "5m"
    assert not any("cache" in key for key in second_model.settings_seen[0])


async def test_openai_has_no_shared_cache_routing_key(monkeypatch):
    monkeypatch.setenv("FLYQUERY_PROMPT_CACHE", "on")
    model = RecordingModel(model_name="gpt-4.1", custom_output_text="fixture")
    await _agent(model).run("Synthetic tenant input")
    assert not any("cache" in key for key in model.settings_seen[0])
