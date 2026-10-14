# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Agent schema reads deserialize the same page envelopes as user reads."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentTablesApi
from flyquery_sdk.models import (
    PaginatedSchemaChangeRead,
    PaginatedSchemaObjectRead,
    PaginatedSnapshotRead,
    PaginatedTableRead,
)


@contextmanager
def page_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            payload = json.dumps({"items": [], "total": 0, "limit": 100, "offset": 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,page_type",
    [
        ("list_tables", PaginatedTableRead),
        ("search_tables", PaginatedTableRead),
        ("list_snapshots", PaginatedSnapshotRead),
        ("list_objects", PaginatedSchemaObjectRead),
        ("list_changes", PaginatedSchemaChangeRead),
    ],
)
async def test_agent_table_reads_return_typed_pages(operation, page_type):
    token = "agt_" + "synthetic-local-fixture" * 2
    workspace = str(uuid4())
    with page_server() as (origin, requests):
        async with ApiClient(Configuration(host=origin)) as client:
            client.default_headers.update({"X-Tenant-Id": "sdk-fixture", "X-Workspace-Id": workspace})
            parameters = {"x_agent_token": token, "_request_timeout": 5.0}
            if operation == "list_tables":
                parameters["dataset_id"] = str(uuid4())
            elif operation != "search_tables":
                parameters["table_id"] = str(uuid4())
            result = await getattr(AgentTablesApi(client), operation)(**parameters)
            assert isinstance(result, page_type)
            assert result.items == [] and result.total == 0
        assert len(requests) == 1
        assert requests[0][1]["X-Agent-Token"] == token
        assert requests[0][1]["X-Tenant-Id"] == "sdk-fixture"
        assert requests[0][1]["X-Workspace-Id"] == workspace
