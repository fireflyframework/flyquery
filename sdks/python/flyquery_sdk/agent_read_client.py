# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Bounded agent-token reads, separate from the user-tier query/upload client."""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError

from flyquery_sdk.models.dataset_read import DatasetRead
from flyquery_sdk.models.paginated_table_read import PaginatedTableRead
from flyquery_sdk.models.schema_object_read import SchemaObjectRead
from flyquery_sdk.models.table_read import TableRead


class AgentReadError(Exception):
    """A read was refused or unavailable; never an instruction to create or rerun."""


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("A UUID string is required")
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError("A UUID string is required") from None


class AgentReadClient:
    """Fixed tenant/workspace/dataset agent reads with no write or query methods.

    ``transport`` is a trusted HTTPX transport seam for controlled offline tests.
    Each operation has a total wall deadline, including the object's parent read.
    Return values are reported observations, not an atomic cross-request snapshot.
    """

    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        workspace_id: str,
        dataset_id: str,
        agent_token: str,
        timeout: float = 10.0,
        max_response_bytes: int = 262144,
        max_items: int = 100,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        try:
            origin = urlsplit(base_url)
            valid = (
                origin.scheme == "https"
                and bool(origin.hostname)
                and origin.username is None
                and origin.password is None
                and origin.path in {"", "/"}
                and not origin.query
                and not origin.fragment
                and origin.port in {None, 443}
                and not any(char.isspace() for char in base_url)
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("An HTTPS origin without credentials, path, query or fragment is required")
        if not isinstance(tenant_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", tenant_id
        ):
            raise ValueError("A bounded tenant identifier is required")
        if not isinstance(agent_token, str) or not re.fullmatch(r"[!-~]{1,4096}", agent_token):
            raise ValueError("A nonempty single-line agent token is required")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("Timeout must be greater than zero and at most 30 seconds")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 1048576:
            raise ValueError("Response bound must be between 1 byte and 1 MiB")
        if type(max_items) is not int or not 1 <= max_items <= 100:
            raise ValueError("Item bound must be between 1 and 100")
        self._tenant = tenant_id
        self._workspace, self._dataset = _uuid(workspace_id), _uuid(dataset_id)
        self._token = agent_token
        self._timeout, self._max_bytes, self._max_items = timeout, max_response_bytes, max_items
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": self._workspace,
                "X-Agent-Token": agent_token,
                "Accept-Encoding": "identity",
            },
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            limits=limits,
            transport=transport
            if transport is not None
            else httpx.AsyncHTTPTransport(retries=0, trust_env=False, limits=limits),
        )

    async def __aenter__(self) -> AgentReadClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str) -> dict[str, Any]:
        async with self._http.stream("GET", "/api/v1/agent" + path) as response:
            if response.status_code != 200:
                raise AgentReadError("Agent read refused or unavailable; no retry or write was attempted")
            if response.headers.get("content-encoding", "identity") != "identity":
                raise AgentReadError("Encoded agent responses are not admitted")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > self._max_bytes):
                raise AgentReadError("Agent response exceeds its byte bound")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > self._max_bytes:
                    raise AgentReadError("Agent response exceeds its byte bound")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise AgentReadError("An agent record or page is required")
        pending: list[Any] = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str) and self._token in item:
                raise AgentReadError("Credential-bearing agent output is refused")
        return value

    async def _operation(self, operation: Any) -> Any:
        try:
            return await asyncio.wait_for(operation, timeout=self._timeout)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, ValidationError, RecursionError):  # noqa: UP041 -- SDK supports Python 3.9's distinct asyncio exception.
            raise AgentReadError(
                "Agent response unavailable or invalid; no retry or write was attempted"
            ) from None

    def _scope(self, value: Any) -> None:
        if value.tenant_id != self._tenant or str(value.workspace_id) != self._workspace:
            raise AgentReadError("Agent response does not match the configured scope")

    async def get_dataset(self) -> DatasetRead:
        """Read only the configured dataset; 404 never triggers creation."""
        return await self._operation(self._dataset_read())

    async def _dataset_read(self) -> DatasetRead:
        value = DatasetRead.model_validate(await self._get("/datasets/" + self._dataset))
        self._scope(value)
        if str(value.id) != self._dataset:
            raise AgentReadError("Agent dataset identity does not match")
        return value

    async def list_tables(self) -> PaginatedTableRead:
        """Read one bounded catalog response; reject an oversized or mixed page whole."""
        return await self._operation(self._tables_read())

    async def _tables_read(self) -> PaginatedTableRead:
        raw = await self._get("/datasets/" + self._dataset + "/tables")
        if not isinstance(raw.get("items"), list) or len(raw["items"]) > self._max_items:
            raise AgentReadError("Agent catalog exceeds its item bound")
        for key in ("total", "limit", "offset"):
            if raw.get(key) is not None and (type(raw[key]) is not int or raw[key] < 0):
                raise AgentReadError("Invalid agent pagination metadata")
        if raw.get("has_more") is not None and type(raw["has_more"]) is not bool:
            raise AgentReadError("Invalid agent pagination metadata")
        if (
            raw.get("has_more") is True
            or raw.get("offset") not in (None, 0)
            or (raw.get("total") is not None and raw["total"] != len(raw["items"]))
        ):
            raise AgentReadError("An incomplete agent catalog cannot be returned without continuation")
        value = PaginatedTableRead.model_validate(raw)
        if value.items is None:
            raise AgentReadError("Agent catalog items are unavailable")
        for item in value.items:
            self._table_scope(item)
        return value

    def _table_scope(self, value: TableRead) -> None:
        self._scope(value)
        if str(value.dataset_id) != self._dataset:
            raise AgentReadError("Agent table does not match the configured dataset")

    async def get_table(self, table_id: str) -> TableRead:
        """Read an exact UUID within the fixed dataset."""
        return await self._operation(self._table_read(_uuid(table_id)))

    async def _table_read(self, table_id: str) -> TableRead:
        value = TableRead.model_validate(await self._get("/tables/" + table_id))
        self._table_scope(value)
        if str(value.id) != table_id:
            raise AgentReadError("Agent table identity does not match")
        return value

    async def get_object(self, table_id: str, object_id: str) -> SchemaObjectRead:
        """Read an exact object bound to the parent's reported current snapshot."""
        return await self._operation(self._object_read(_uuid(table_id), _uuid(object_id)))

    async def _object_read(self, table_id: str, object_id: str) -> SchemaObjectRead:
        parent = await self._table_read(table_id)
        if parent.current_snapshot_id is None:
            raise AgentReadError("The parent snapshot is unavailable")
        value = SchemaObjectRead.model_validate(await self._get("/schema-objects/" + object_id))
        self._scope(value)
        if (
            str(value.id) != object_id
            or str(value.table_id) != table_id
            or value.snapshot_id != parent.current_snapshot_id
        ):
            raise AgentReadError("Agent object does not match the observed parent snapshot")
        return value
