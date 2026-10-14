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

"""Observability primitives shared across every pipeline stage.

* :func:`timed_agent_run` -- async context manager that records the
  per-stage latency and propagates the W3C correlation context into
  the agent's structured logs.
* :func:`build_agent_middleware` -- the configured provider prompt-cache
  policy. Agentic supplies logging and observability defaults separately.
* :func:`log_outbound` -- thin wrapper around :func:`structlog.get_logger`
  to emit the ``outbound_call`` line for every LLM / webhook call.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fireflyframework_agentic.agents.prompt_cache import PromptCacheMiddleware

logger = logging.getLogger(__name__)


def _prompt_cache_enabled() -> bool:
    """Read ``FLYQUERY_PROMPT_CACHE`` and decide if caching is on.

    Default ``"on"``. Set to ``"off"`` / ``"0"`` / ``"false"`` to skip
    attaching the middleware (handy for A/B benchmarking and disaster
    rollback). Case-insensitive.
    """
    raw = os.environ.get("FLYQUERY_PROMPT_CACHE", "on").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def build_agent_middleware() -> list[PromptCacheMiddleware]:
    """Read the switch for each agent; cache only static instructions.

    Agentic already supplies logging and observability. Without a tenant
    cache authority, do not mark conversation/tool content or share an OpenAI
    routing key. This middleware never stores model responses in flyquery.
    """
    if not _prompt_cache_enabled():
        return []
    return [
        PromptCacheMiddleware(
            cache_system_prompt=True,
            cache_last_message=False,
            cache_tool_definitions=False,
            cache_ttl_seconds=300,
            openai_cache_key="",
        )
    ]


@asynccontextmanager
async def timed_agent_run(stage: str, **extra: Any) -> AsyncIterator[dict[str, Any]]:
    """Context manager recording latency of a stage's agent call.

    Yields a dictionary the caller can populate with extra fields
    (token counts, agent name, model used). On exit the manager emits
    a single structured ``stage_completed`` log line with the latency
    and every populated field -- one log entry per stage call.
    """
    started = time.monotonic()
    context: dict[str, Any] = {"stage": stage, **extra}
    try:
        yield context
        context["status"] = context.get("status", "success")
    except Exception as exc:  # noqa: BLE001 - we re-raise after logging
        context["status"] = "failed"
        context["error"] = str(exc)
        raise
    finally:
        context["latency_ms"] = int((time.monotonic() - started) * 1000)
        logger.info("stage_completed", extra=context)


def log_outbound(
    *,
    kind: str,
    target: str,
    duration_ms: int,
    cost_usd: float | None = None,
    status: str = "success",
    **extra: Any,
) -> None:
    """Emit a structured ``outbound_call`` log entry.

    Used for every LLM call, webhook delivery, and external HTTP call
    out of the service. Mirrors the field set callers see in the
    transaction-audit dashboard.
    """
    payload = {
        "event": "outbound_call",
        "kind": kind,
        "target": target,
        "duration_ms": duration_ms,
        "status": status,
        **extra,
    }
    if cost_usd is not None:
        payload["cost_usd"] = round(cost_usd, 6)
    logger.info("outbound_call", extra=payload)
