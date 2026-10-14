#!/usr/bin/env python
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

"""Check nineteen normalized historical baselines and two reviewed variants.

The baseline pins are local historical contracts, not a comparison with live
canon main. Only the two listed service-specific paths may use full-file pins
from the versioned manifest; every other path keeps its original baseline.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

LOCKSTEP_FILES = [
    "src/flyquery/web/agent_deps.py",
    "src/flyquery/web/openapi_override.py",
    "src/flyquery/web/conventions/__init__.py",
    "src/flyquery/web/conventions/actor.py",
    "src/flyquery/web/conventions/context.py",
    "src/flyquery/web/conventions/db.py",
    "src/flyquery/web/conventions/deps.py",
    "src/flyquery/web/conventions/errors.py",
    "src/flyquery/web/conventions/exceptions.py",
    "src/flyquery/web/conventions/handlers.py",
    "src/flyquery/web/conventions/headers.py",
    "src/flyquery/web/conventions/http_client.py",
    "src/flyquery/web/conventions/idempotency.py",
    "src/flyquery/web/conventions/middleware.py",
    "src/flyquery/web/conventions/redis_idempotency.py",
    "src/flyquery/web/conventions/validation.py",
    "src/flyquery/core/agents/builder.py",
    "src/flyquery/core/observability/__init__.py",
    "src/flyquery/core/services/auth/agent_token_service.py",
    "src/flyquery/core/services/auth/redis_rate_limiter.py",
    "src/flyquery/web/controllers/agent_tokens_controller.py",
]

SERVICE_VARIANTS = {
    "src/flyquery/core/agents/builder.py",
    "src/flyquery/core/observability/__init__.py",
}


def _service_variants(root: Path) -> dict[str, dict[str, str]]:
    manifest = json.loads((root / "scripts" / "lockstep_variants.v1.json").read_text())
    if not isinstance(manifest, dict) or type(manifest.get("version")) is not int or manifest["version"] != 1:
        raise ValueError("UNSUPPORTED VARIANT VERSION")
    source = manifest.get("canonical_source")
    if (
        not isinstance(source, dict)
        or source.get("repository") != "https://github.com/fireflyframework/flycanon"
        or not isinstance(source.get("revision"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", source["revision"])
    ):
        raise ValueError("INVALID CANONICAL SOURCE")
    variants = manifest.get("variants")
    if not isinstance(variants, dict):
        raise ValueError("INVALID VARIANT MANIFEST")
    if set(variants) - SERVICE_VARIANTS:
        raise ValueError("UNKNOWN VARIANT PATH")
    if set(variants) != SERVICE_VARIANTS:
        raise ValueError("MISSING VARIANT PIN")
    for rel, entry in variants.items():
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("rationale"), str)
            or not entry["rationale"].strip()
        ):
            raise ValueError(f"INVALID VARIANT RATIONALE: {rel}")
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError(f"INVALID VARIANT PIN: {rel}")
    return variants


def _normalise(text: str) -> bytes:
    """Apply the unchanged historic service substitutions used by baseline pins."""
    text = re.sub(r"\bflyquery\b", "flycanon", text)
    text = re.sub(r"\bFLYQUERY\b", "FLYCANON", text)
    text = re.sub(r"\bflyquery_", "canon_", text)
    text = re.sub(r"\bFlyquerySettings\b", "CanonSettings", text)
    return text.encode("utf-8")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        variants = _service_variants(root)
    except (OSError, ValueError) as exc:
        print(f"INVALID VARIANT MANIFEST: {exc}")
        return 1
    pins_path = root / "scripts" / "lockstep_pins.json"
    pins: dict[str, str] = json.loads(pins_path.read_text()) if pins_path.exists() else {}
    drift: list[str] = []
    for rel in LOCKSTEP_FILES:
        p = root / rel
        if not p.exists():
            drift.append(f"MISSING: {rel}")
            continue
        variant = variants.get(rel)
        sha = hashlib.sha256(p.read_bytes() if variant else _normalise(p.read_text())).hexdigest()
        pinned = variant["sha256"] if variant else pins.get(rel)
        if pinned is None:
            drift.append(f"UNPINNED: {rel} -> {sha}")
        elif pinned != sha:
            label = "SERVICE VARIANT DRIFT" if variant else "DRIFT"
            drift.append(f"{label}: {rel}\n    pinned:  {pinned}\n    current: {sha}")
    if drift:
        print("\n".join(drift))
        return 1
    print("lockstep OK: 19 historical baselines and 2 reviewed service variants match pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
