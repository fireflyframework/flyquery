# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""SDK wire-contract checks over a real loopback socket, without a service dependency."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

import pytest
from flyquery_sdk.client import FlyqueryClient
from flyquery_sdk.exceptions import ApiException


@contextmanager
def resource_server(resource: str, lookup_status: int):
    events = []
    workspace_id = str(uuid4())
    body: dict[str, Any] = {
        "id": str(uuid4()),
        "tenant_id": "sdk-fixture",
        "name": "Finance",
        "created_at": "2026-10-14T00:00:00Z",
        "updated_at": "2026-10-14T00:00:00Z",
        "metadata_json": {},
    }
    if resource == "workspace":
        body.update(
            slug="finance",
            status="ACTIVE",
            storage_used_bytes=0,
            allow_direct_sql=False,
            default_locale="en-US",
            kms_key_uri=None,
            retention_days=None,
        )
    else:
        body.update(
            workspace_id=workspace_id,
            description=None,
            status="ACTIVE",
            drift_policy="AUTO",
            ingest_policy_json={},
            default_locale=None,
        )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            events.append({"method": self.command, "headers": dict(self.headers), "path": self.path})
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(lookup_status, body if lookup_status == 200 else {"detail": "fixture status"})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.reply(201, body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", workspace_id, events
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["workspace", "dataset"])
@pytest.mark.parametrize("lookup_status", [200, 404])
async def test_lookup_or_create_preserves_context(resource, lookup_status):
    with resource_server(resource, lookup_status) as (origin, workspace_id, events):
        async with FlyqueryClient(
            base_url=origin, tenant_id="sdk-fixture", workspace_id=workspace_id
        ) as client:
            result = await (
                client.find_or_create_workspace("finance")
                if resource == "workspace"
                else client.find_or_create_dataset("Finance")
            )
        assert result.tenant_id == "sdk-fixture"
        assert [event["method"] for event in events] == (["GET"] if lookup_status == 200 else ["GET", "POST"])
        for event in events:
            assert event["headers"]["X-Tenant-Id"] == "sdk-fixture"
            assert event["headers"]["X-Workspace-Id"] == workspace_id


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["workspace", "dataset"])
@pytest.mark.parametrize("lookup_status", [401, 403, 409, 500])
async def test_lookup_failure_never_becomes_a_create(resource, lookup_status):
    with resource_server(resource, lookup_status) as (origin, workspace_id, events):
        async with FlyqueryClient(
            base_url=origin, tenant_id="sdk-fixture", workspace_id=workspace_id
        ) as client:
            with pytest.raises(ApiException) as failure:
                await (
                    client.find_or_create_workspace("finance")
                    if resource == "workspace"
                    else client.find_or_create_dataset("Finance")
                )
        assert failure.value.status == lookup_status
        assert [event["method"] for event in events] == ["GET"]
