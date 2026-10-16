# Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0
"""Read-only agent controls with MockTransport, never a socket or provider."""

import asyncio
import socket
from uuid import UUID

import httpx
import pytest
from flyquery_sdk import agent_read_client as module

WS, DS, TABLE, OBJECT, SNAPSHOT = [str(UUID(int=n)) for n in range(1, 6)]
TOKEN = "agt_fictional_offline_test"
STAMP = "2026-10-16T00:00:00Z"


def table():
    return dict(
        id=TABLE,
        tenant_id="fixture",
        workspace_id=WS,
        dataset_id=DS,
        source_file_id=None,
        name="checks",
        qualified_name="checks",
        kind="UPLOADED",
        sheet_or_json_path=None,
        current_snapshot_id=SNAPSHOT,
        description=None,
        description_source=None,
        business_owner=None,
        is_active=True,
        created_at=STAMP,
        updated_at=STAMP,
        n_columns=0,
    )


def dataset():
    return dict(
        id=DS,
        tenant_id="fixture",
        workspace_id=WS,
        name="checks",
        description=None,
        drift_policy="AUTO",
        default_locale=None,
        ingest_policy_json={},
        status="ACTIVE",
        created_at=STAMP,
        updated_at=STAMP,
        metadata_json={},
    )


def object_row():
    return dict(
        id=OBJECT,
        tenant_id="fixture",
        workspace_id=WS,
        table_id=TABLE,
        snapshot_id=SNAPSHOT,
        kind="COLUMN",
        qualified_name="checks.value",
        data_type="TEXT",
        is_nullable=True,
        description=None,
        description_source=None,
        pii_tag=None,
        pii_source=None,
        business_owner=None,
        is_active=True,
        created_at=STAMP,
        last_changed_at=STAMP,
        governance_json={},
        synonyms_json=[],
    )


def client(handler, **kwargs):
    return module.AgentReadClient(
        base_url="https://flyquery.example",
        tenant_id="fixture",
        workspace_id=WS,
        dataset_id=DS,
        agent_token=TOKEN,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("No real network permitted")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.mark.asyncio
async def test_missing_safe_client_has_real_get_only_contract():
    assert module is not None, "The separate bounded GET-only agent client is missing"
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "GET" and not request.content
        assert request.headers["X-Agent-Token"] == TOKEN
        assert request.headers["X-Workspace-Id"] == WS and request.headers["X-Tenant-Id"] == "fixture"
        value = (
            dataset()
            if "/datasets/" in request.url.path and not request.url.path.endswith("/tables")
            else object_row()
            if "/schema-objects/" in request.url.path
            else dict(items=[table()], total=1)
            if request.url.path.endswith("/tables")
            else table()
        )
        return httpx.Response(200, json=value)

    async with client(handle) as agent:
        assert str((await agent.get_dataset()).id) == DS
        assert (await agent.list_tables()).items[0].n_columns == 0
        assert str((await agent.get_table(TABLE)).current_snapshot_id) == SNAPSHOT
        assert str((await agent.get_object(TABLE, OBJECT)).id) == OBJECT
        assert agent._http.follow_redirects is False and agent._http._trust_env is False
        assert agent._http._mounts == {}
    assert all(r.url.path.startswith("/api/v1/agent/") for r in requests)
    assert not {"ask", "upload", "execute", "export", "get_query_result"} & set(dir(module.AgentReadClient))


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant_id", "workspace_id", "dataset_id", "id"])
async def test_foreign_table_is_never_returned(field):
    value = table()
    value[field] = "foreign" if field == "tenant_id" else str(UUID(int=99))
    async with client(lambda _: httpx.Response(200, json=value)) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_table(TABLE)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant_id", "workspace_id", "dataset_id"])
async def test_mixed_page_is_refused_whole(field):
    value = table()
    value[field] = "foreign" if field == "tenant_id" else str(UUID(int=99))
    async with client(lambda _: httpx.Response(200, json=dict(items=[table(), value]))) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.list_tables()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant_id", "workspace_id", "table_id", "id", "snapshot_id"])
async def test_exact_object_checks_parent_snapshot_and_scope(field):
    value = object_row()
    value[field] = "foreign" if field == "tenant_id" else str(UUID(int=99))
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=table() if "/tables/" in request.url.path else value)

    async with client(handle) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_object(TABLE, OBJECT)
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 404, 429, 500, 503])
async def test_error_never_redirects_retries_writes_or_reflects(status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://other.example/private"}, text=TOKEN)

    async with client(handle) as agent:
        with pytest.raises(module.AgentReadError) as error:
            await agent.get_dataset()
    assert len(requests) == 1 and requests[0].method == "GET" and TOKEN not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["large", "encoding", "json", "type", "token", "rows", "boolean"])
async def test_payload_bounds_and_credentials_before_return(failure):
    def handle(_):
        if failure == "large":
            return httpx.Response(200, content=b" " * 257)
        if failure == "encoding":
            return httpx.Response(200, headers={"Content-Encoding": "fictional"}, content=b"{}")
        if failure == "json":
            return httpx.Response(200, content=b"invalid")
        if failure == "type":
            return httpx.Response(200, json=[])
        if failure == "token":
            return httpx.Response(200, json=dict(items=[], detail=TOKEN))
        if failure == "rows":
            return httpx.Response(200, json=dict(items=[table(), table()]))
        return httpx.Response(200, json=dict(items=[], total=True))

    async with client(handle, max_response_bytes=256 if failure == "large" else 8192, max_items=1) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.list_tables()


@pytest.mark.asyncio
async def test_wall_timeout_no_retry_and_cancellation_preserved():
    attempts = []

    async def handle(request):
        attempts.append(request)
        await asyncio.Event().wait()

    async with client(handle, timeout=0.01) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_dataset()
        task = asyncio.create_task(agent.get_dataset())
        while len(attempts) < 2:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(attempts) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?token=x",
        "https://example.com/#x",
        "file:///tmp/a",
    ],
)
def test_bad_origin_refused_before_transport(url):
    with pytest.raises(ValueError):
        module.AgentReadClient(
            base_url=url, tenant_id="fixture", workspace_id=WS, dataset_id=DS, agent_token=TOKEN
        )


@pytest.mark.asyncio
async def test_bad_id_has_zero_requests_and_repr_has_no_token():
    requests = []
    async with client(lambda r: requests.append(r)) as agent:
        assert TOKEN not in repr(agent)
        with pytest.raises(ValueError):
            await agent.get_table("../queries")
    assert requests == []


@pytest.mark.asyncio
async def test_opaque_quoted_token_is_refused_after_json_decoding():
    token = 'agt_"quoted\\fixture'
    async with module.AgentReadClient(
        base_url="https://flyquery.example",
        tenant_id="fixture",
        workspace_id=WS,
        dataset_id=DS,
        agent_token=token,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=dict(items=[], secret=token))),
    ) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.list_tables()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant_id", "workspace_id", "id"])
async def test_dataset_binding_is_checked(field):
    value = dataset()
    value[field] = "foreign" if field == "tenant_id" else str(UUID(int=99))
    async with client(lambda _: httpx.Response(200, json=value)) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_dataset()


@pytest.mark.asyncio
async def test_unavailable_parent_snapshot_refuses_before_object_get():
    requests = []
    value = table()
    value["current_snapshot_id"] = None

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=value)

    async with client(handle) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_object(TABLE, OBJECT)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_two_request_object_operation_has_one_total_wall_deadline():
    requests = []

    async def handle(request):
        requests.append(request)
        await asyncio.sleep(0.03)
        return httpx.Response(200, json=table() if len(requests) == 1 else object_row())

    async with client(handle, timeout=0.05) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_object(TABLE, OBJECT)
    assert len(requests) == 2


@pytest.mark.parametrize(
    "parameters",
    [
        dict(timeout=True),
        dict(timeout=float("nan")),
        dict(timeout=31),
        dict(max_items=True),
        dict(max_items=101),
        dict(max_response_bytes=True),
        dict(max_response_bytes=1048577),
    ],
)
def test_configuration_bounds_are_exact(parameters):
    with pytest.raises(ValueError):
        client(lambda _: None, **parameters)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["limit", "timeout"])
async def test_stream_is_closed_on_overflow_or_wall_timeout(scenario):
    closed, requests = [], []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{" * 80
            if scenario == "limit":
                yield b"{" * 80
            else:
                await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=Stream())

    async with client(handle, timeout=0.01, max_response_bytes=100) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.get_dataset()
    assert closed == [True] and len(requests) == 1


@pytest.mark.asyncio
async def test_real_default_transport_enforces_connection_and_retry_limits_without_network():
    async with module.AgentReadClient(
        base_url="https://flyquery.example",
        tenant_id="fixture",
        workspace_id=WS,
        dataset_id=DS,
        agent_token=TOKEN,
    ) as agent:
        transport = agent._http._transport
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        assert transport._pool._max_connections == 4
        assert transport._pool._max_keepalive_connections == 2
        assert transport._pool._retries == 0
        assert transport._pool.connections == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        dict(has_more=True),
        dict(offset=1),
        dict(total=2),
        dict(total=0),
        dict(offset=0, total=1, has_more=True),
    ],
)
async def test_declared_incomplete_or_inconsistent_catalog_is_refused_without_continuation(metadata):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=dict(items=[table()], **metadata))

    async with client(handle) as agent:
        with pytest.raises(module.AgentReadError):
            await agent.list_tables()
    assert len(requests) == 1 and requests[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {},
        dict(total=1),
        dict(total=None, offset=None, limit=None, has_more=None),
        dict(offset=0, total=1, has_more=False),
        dict(limit=1, total=1, offset=0, has_more=False),
    ],
)
async def test_complete_or_absent_catalog_metadata_preserves_full_list_contract(metadata):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=dict(items=[table()], **metadata))

    async with client(handle) as agent:
        value = await agent.list_tables()
        assert len(value.items) == 1 and str(value.items[0].id) == TABLE
    assert len(requests) == 1
