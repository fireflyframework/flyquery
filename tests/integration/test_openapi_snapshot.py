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

import json
from pathlib import Path

import pytest


@pytest.mark.integration
def test_openapi_snapshot_matches_running_app():
    from flyquery.main import app

    expected = app.openapi()
    snapshot_path = Path(__file__).parent.parent.parent / "openapi.json"
    actual = json.loads(snapshot_path.read_text())
    # We accept differences in `info.version` (CalVer-bumped) but the
    # paths + components must match exactly.
    assert actual.get("components") == expected.get("components"), (
        "OpenAPI schema drift! Run `task openapi-snapshot` before building SDKs."
    )
    expected_keys = set(expected.get("paths", {}).keys())
    actual_keys = set(actual.get("paths", {}).keys())
    assert expected_keys == actual_keys, (
        f"OpenAPI drift! Run `task openapi-snapshot`. Diff: {expected_keys ^ actual_keys}"
    )


@pytest.mark.integration
def test_openapi_snapshot_includes_header_parameters():
    """Guards that the on-disk spec carries flyquery's header parameters.

    ``scripts/openapi_snapshot.py`` must preserve the ``_wrapped_openapi``
    shim installed by ``flyquery.main`` (rather than pyfly's bare
    generator), so the spec keeps every header parameter and generated
    SDKs can enforce the four-header contract.
    """
    snapshot_path = Path(__file__).parent.parent.parent / "openapi.json"
    actual = json.loads(snapshot_path.read_text())
    params = actual.get("components", {}).get("parameters", {})
    schemes = actual.get("components", {}).get("securitySchemes", {})

    expected_params = {
        "TenantIdHeader",
        "WorkspaceIdHeader",
        "AgentTokenHeader",
        "CorrelationIdHeader",
        "IdempotencyKeyHeader",
    }
    expected_schemes = {"TenantContext", "WorkspaceContext", "AgentToken"}

    missing_params = expected_params - set(params.keys())
    missing_schemes = expected_schemes - set(schemes.keys())
    assert not missing_params, (
        f"openapi.json missing header parameters {missing_params}. Run `task openapi-snapshot`."
    )
    assert not missing_schemes, (
        f"openapi.json missing security schemes {missing_schemes}. Run `task openapi-snapshot`."
    )


@pytest.mark.integration
def test_openapi_snapshot_attaches_headers_to_operations():
    """Every mutating operation should carry an Idempotency-Key parameter
    reference, and every /api/v1/agent/* op should require AgentToken."""
    snapshot_path = Path(__file__).parent.parent.parent / "openapi.json"
    actual = json.loads(snapshot_path.read_text())

    missing_idempotency: list[str] = []
    missing_agent_token: list[str] = []
    missing_tenant: list[str] = []

    for path, item in actual.get("paths", {}).items():
        is_agent = "/agent/" in path
        for verb, op in item.items():
            if verb.lower() not in {"get", "post", "put", "delete", "patch"}:
                continue
            param_refs = {p.get("$ref") for p in op.get("parameters", []) if isinstance(p, dict)}
            is_mutating = verb.lower() in {"post", "put", "delete", "patch"}
            if is_mutating and "#/components/parameters/IdempotencyKeyHeader" not in param_refs:
                missing_idempotency.append(f"{verb.upper()} {path}")
            if is_agent and "#/components/parameters/AgentTokenHeader" not in param_refs:
                missing_agent_token.append(f"{verb.upper()} {path}")
            if not is_agent and "#/components/parameters/TenantIdHeader" not in param_refs:
                missing_tenant.append(f"{verb.upper()} {path}")

    assert not missing_idempotency, (
        f"Mutating operations missing IdempotencyKeyHeader: {missing_idempotency[:5]}"
    )
    assert not missing_agent_token, f"Agent operations missing AgentTokenHeader: {missing_agent_token[:5]}"
    assert not missing_tenant, f"User-tier operations missing TenantIdHeader: {missing_tenant[:5]}"


@pytest.mark.integration
def test_sse_endpoints_declare_event_stream_content():
    """Regression: SDK generators emitted Mono<Void> / un-parsed body for
    streaming endpoints because the spec didn't declare ``text/event-stream``.
    Every endpoint in flyquery.web.openapi_sse.SSE_ENDPOINTS must now ship
    that content-type on its 200 response.
    """
    from flyquery.web.openapi_sse import SSE_ENDPOINTS

    snapshot_path = Path(__file__).parent.parent.parent / "openapi.json"
    actual = json.loads(snapshot_path.read_text())

    missing: list[str] = []
    for verb, path in SSE_ENDPOINTS:
        op = actual.get("paths", {}).get(path, {}).get(verb, {})
        content = op.get("responses", {}).get("200", {}).get("content", {})
        if "text/event-stream" not in content:
            missing.append(f"{verb.upper()} {path}")

    assert not missing, (
        f"SSE endpoints missing text/event-stream content-type: {missing}. Run `task openapi-snapshot`."
    )
