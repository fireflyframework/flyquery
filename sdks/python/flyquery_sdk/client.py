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

"""Ergonomic high-level Python client for flyquery.

The generated ``flyquery_sdk.api.*`` classes are accurate but verbose
-- every call needs explicit ``x_tenant_id`` + ``x_workspace_id``
arguments, separate API instances, and the bulk + batch endpoints
need hand-built multipart bodies (openapi-generator can't see the
multi-part ``files`` field). This module wraps the generated API
into a single ``FlyqueryClient`` that:

* Carries the tenant + workspace context once per client (no
  repeating headers per call).
* Exposes ergonomic helpers: ``upload(path)``,
  ``upload_directory(path)``, ``upload_bulk(paths)``,
  ``ask(question)``, ``ask_batch(questions)``,
  ``find_or_create_workspace(slug)``, ``find_or_create_dataset(name)``.
* Returns the same generated Pydantic models so callers keep full
  type safety + can drop down to the underlying ``ApiClient`` when
  they need a knob the wrapper doesn't expose.

Threading
---------
The wrapper is async-first (matches the generated client). Sync
mirrors (``upload_sync`` / ``ask_sync``) wrap ``asyncio.run`` for
CLIs and tests without a running event loop. In notebooks, await
the async methods directly.
"""

from __future__ import annotations

import asyncio
import json as _json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from flyquery_sdk.api.audit_events_api import AuditEventsApi
from flyquery_sdk.api.billing_api import BillingApi
from flyquery_sdk.api.cost_events_api import CostEventsApi
from flyquery_sdk.api.datasets_api import DatasetsApi
from flyquery_sdk.api.files_api import FilesApi
from flyquery_sdk.api.queries_api import QueriesApi
from flyquery_sdk.api.query_api import QueryApi
from flyquery_sdk.api.stats_api import StatsApi
from flyquery_sdk.api.tables_api import TablesApi
from flyquery_sdk.api.workspaces_api import WorkspacesApi
from flyquery_sdk.api_client import ApiClient
from flyquery_sdk.configuration import Configuration
from flyquery_sdk.exceptions import ApiException

__all__ = ["FlyqueryClient", "BulkFileResult", "BulkUploadOutcome"]


# Generated model re-exports so callers don't have to chase the deep
# ``flyquery_sdk.models.*`` paths just to access the response shape.
from flyquery_sdk.models.answer_response import AnswerResponse  # noqa: E402
from flyquery_sdk.models.batch_query_response import BatchQueryResponse  # noqa: E402
from flyquery_sdk.models.batch_query_result_item import (  # noqa: E402, F401  -- re-exported
    BatchQueryResultItem,
)
from flyquery_sdk.models.bulk_file_result import BulkFileResult  # noqa: E402
from flyquery_sdk.models.bulk_file_upload_response import BulkFileUploadResponse  # noqa: E402
from flyquery_sdk.models.dataset_read import DatasetRead  # noqa: E402
from flyquery_sdk.models.file_upload_response import FileUploadResponse  # noqa: E402
from flyquery_sdk.models.workspace_read import WorkspaceRead  # noqa: E402

BulkUploadOutcome = BulkFileUploadResponse


class FlyqueryClient:
    """Tenant + workspace-scoped flyquery client.

    Construct once per ``(tenant_id, workspace_id)`` pair; reuse for
    every call within that scope. ``timeout`` bounds the raw HTTPX helpers;
    generated API calls accept their own ``_request_timeout`` argument.
    ``agent_token`` adds a header but does not switch helpers to agent routes.
    Async-first; ``__aenter__`` /
    ``__aexit__`` close the underlying HTTP pool.

    Examples
    --------
    Single-file upload + a query::

        async with FlyqueryClient(
            base_url="https://flyquery.example.com",
            tenant_id="example-tenant",
            workspace_id="2e5aa824-2f02-4b71-8939-098989024888",
        ) as fly:
            ds = await fly.find_or_create_dataset("orders", description="...")
            await fly.upload(str(ds.id), "examples/csv/sales_orders.csv")
            ans = await fly.ask(str(ds.id), "What's the total revenue?")
            print(ans.sql, ans.preview)

    Bulk upload + batch query::

        async with FlyqueryClient(...) as fly:
            outcome = await fly.upload_directory(str(ds.id), "examples/")
            print(f"uploaded {outcome.succeeded}/{outcome.total_files}")

            batch = await fly.ask_batch(
                str(ds.id),
                ["Top 5 customers?", "Total revenue?", "Refund rate?"],
            )
            for r in batch.results:
                print(r.status, r.sql)
    """

    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        workspace_id: str,
        agent_token: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._agent_token = agent_token

        config = Configuration(host=self._base_url)
        self._api_client = ApiClient(config)
        # Generated methods still require explicit context arguments. Defaults
        # also carry the context when callers use the underlying ApiClient.
        self._api_client.default_headers["X-Tenant-Id"] = self._tenant_id
        self._api_client.default_headers["X-Workspace-Id"] = self._workspace_id
        if self._agent_token:
            self._api_client.default_headers["X-Agent-Token"] = self._agent_token
        self._workspaces = WorkspacesApi(self._api_client)
        self._datasets = DatasetsApi(self._api_client)
        self._files = FilesApi(self._api_client)
        self._tables = TablesApi(self._api_client)
        self._query = QueryApi(self._api_client)
        # v1.0 (26.5.11) -- history + billing + stats + ops ledgers.
        self._queries = QueriesApi(self._api_client)
        self._billing = BillingApi(self._api_client)
        self._stats = StatsApi(self._api_client)
        self._audit_events = AuditEventsApi(self._api_client)
        self._cost_events = CostEventsApi(self._api_client)

        # Separate raw httpx client for the multipart bulk + custom
        # endpoints the generated client can't model.
        headers = {
            "X-Tenant-Id": self._tenant_id,
            "X-Workspace-Id": self._workspace_id,
        }
        if self._agent_token:
            headers["X-Agent-Token"] = self._agent_token
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> FlyqueryClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._api_client.close()

    # ------------------------------------------------------------------
    # Accessors -- drop down to raw generated API when needed
    # ------------------------------------------------------------------

    @property
    def workspaces(self) -> WorkspacesApi:
        return self._workspaces

    @property
    def datasets(self) -> DatasetsApi:
        return self._datasets

    @property
    def files(self) -> FilesApi:
        return self._files

    @property
    def tables(self) -> TablesApi:
        return self._tables

    @property
    def query(self) -> QueryApi:
        return self._query

    # v1.0 (26.5.11) accessors -- raw generated API objects for the
    # new history / billing / stats / ops surfaces.

    @property
    def queries(self) -> QueriesApi:
        return self._queries

    @property
    def billing(self) -> BillingApi:
        return self._billing

    @property
    def stats(self) -> StatsApi:
        return self._stats

    @property
    def audit_events(self) -> AuditEventsApi:
        return self._audit_events

    @property
    def cost_events(self) -> CostEventsApi:
        return self._cost_events

    # ------------------------------------------------------------------
    # Workspace + dataset helpers
    # ------------------------------------------------------------------

    async def find_or_create_workspace(
        self,
        slug: str,
        *,
        name: str | None = None,
    ) -> WorkspaceRead:
        """Look up a workspace by slug; create only after an HTTP 404.

        A concurrent creator can still produce an HTTP 409. Other failures
        propagate without attempting a write.
        """
        try:
            return await self._workspaces.read_by_slug(
                slug=slug,
                x_tenant_id=self._tenant_id,
                x_workspace_id=self._workspace_id,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            from flyquery_sdk.models.workspace_create import WorkspaceCreate

            return await self._workspaces.create(
                workspace_create=WorkspaceCreate(slug=slug, name=name or slug),
                x_tenant_id=self._tenant_id,
                x_workspace_id=self._workspace_id,
            )

    async def find_or_create_dataset(
        self,
        name: str,
        *,
        description: str | None = None,
    ) -> DatasetRead:
        """Look up a dataset by name; create only after an HTTP 404.

        A concurrent creator can still produce an HTTP 409. Other failures
        propagate without attempting a write.
        """
        try:
            return await self._datasets.read_by_name(
                name=name,
                x_tenant_id=self._tenant_id,
                x_workspace_id=self._workspace_id,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            from flyquery_sdk.models.dataset_create import DatasetCreate

            return await self._datasets.create(
                dataset_create=DatasetCreate(name=name, description=description),
                x_tenant_id=self._tenant_id,
                x_workspace_id=self._workspace_id,
            )

    # ------------------------------------------------------------------
    # File ingestion (single + bulk + directory)
    # ------------------------------------------------------------------

    async def upload(
        self,
        dataset_id: str,
        path: str | Path,
    ) -> FileUploadResponse:
        """Upload a single file to ``dataset_id``.

        Uses raw httpx because the generated client's
        ``upload_file`` requires a ``StrictBytes`` object that's
        finicky to construct from a Path.
        """
        p = Path(path)
        content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        files = {"file": (p.name, p.read_bytes(), content_type)}
        r = await self._http.post(
            f"/api/v1/datasets/{quote(dataset_id)}/files",
            files=files,
        )
        r.raise_for_status()
        return FileUploadResponse.model_validate(r.json())

    async def upload_bulk(
        self,
        dataset_id: str,
        paths: list[str | Path],
    ) -> BulkFileUploadResponse:
        """Upload many files in a single bulk multipart request.

        Per-file failures do NOT abort the bulk -- inspect the
        ``results[i].status`` field. Aggregate counts are in
        ``total_files`` / ``succeeded`` / ``failed``.
        """
        files = []
        for raw in paths:
            p = Path(raw)
            content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            files.append(("files", (p.name, p.read_bytes(), content_type)))
        r = await self._http.post(
            f"/api/v1/datasets/{quote(dataset_id)}/files:bulk",
            files=files,
        )
        r.raise_for_status()
        return BulkFileUploadResponse.model_validate(r.json())

    async def upload_directory(
        self,
        dataset_id: str,
        directory: str | Path,
        *,
        recursive: bool = True,
        extensions: tuple[str, ...] = (
            ".csv",
            ".tsv",
            ".json",
            ".jsonl",
            ".xlsx",
            ".xls",
            ".ods",
            ".parquet",
            ".avro",
            ".orc",
            ".arrow",
            ".feather",
        ),
    ) -> BulkFileUploadResponse:
        """Walk ``directory`` and bulk-upload every matching file."""
        root = Path(directory)
        if not root.is_dir():
            raise NotADirectoryError(root)
        glob = "**/*" if recursive else "*"
        paths: list[str | Path] = sorted(
            p for p in root.glob(glob) if p.is_file() and p.suffix.lower() in extensions
        )
        if not paths:
            raise FileNotFoundError(f"no ingestable files under {root} (extensions={extensions})")
        return await self.upload_bulk(dataset_id, paths)

    # ------------------------------------------------------------------
    # NL query (single + batch)
    # ------------------------------------------------------------------

    async def ask(
        self,
        dataset_id: str,
        question: str,
        *,
        conversation_id: str | None = None,
    ) -> AnswerResponse:
        """Run a single NL question through the query pipeline."""
        payload: dict[str, Any] = {"question": question, "dataset_id": dataset_id}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        r = await self._http.post(
            "/api/v1/query",
            content=_json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return AnswerResponse.model_validate(r.json())

    async def ask_batch(
        self,
        dataset_id: str,
        questions: list[str],
    ) -> BatchQueryResponse:
        """Run many NL questions in parallel against ``dataset_id``."""
        payload = {
            "queries": [{"question": q, "dataset_id": dataset_id} for q in questions],
        }
        r = await self._http.post(
            "/api/v1/query:batch",
            content=_json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return BatchQueryResponse.model_validate(r.json())

    # ------------------------------------------------------------------
    # Sync mirrors -- for notebooks, CLIs, tests
    # ------------------------------------------------------------------

    def upload_sync(self, dataset_id: str, path: str | Path) -> FileUploadResponse:
        return asyncio.run(self.upload(dataset_id, path))

    def upload_bulk_sync(
        self,
        dataset_id: str,
        paths: list[str | Path],
    ) -> BulkFileUploadResponse:
        return asyncio.run(self.upload_bulk(dataset_id, paths))

    def ask_sync(self, dataset_id: str, question: str) -> AnswerResponse:
        return asyncio.run(self.ask(dataset_id, question))

    def ask_batch_sync(self, dataset_id: str, questions: list[str]) -> BatchQueryResponse:
        return asyncio.run(self.ask_batch(dataset_id, questions))

    # ------------------------------------------------------------------
    # v1 history + observability helpers (26.5.11)
    # ------------------------------------------------------------------
    #
    # Thin convenience wrappers around the generated history /
    # billing / stats APIs. Each wrapper drops the four-header
    # ceremony (the ApiClient defaults set them once) and returns
    # the typed Pydantic model. Drop down to ``self.queries`` /
    # ``self.billing`` / ``self.stats`` for filters the helper
    # doesn't expose.

    async def recent_queries(
        self,
        *,
        dataset_id: str | None = None,
        execution_status: str | None = None,
        limit: int = 50,
    ) -> Any:
        """List recent queries (newest first), scoped to this client's workspace.

        Optional filters: ``dataset_id``, ``execution_status``
        (``OK`` / ``REJECTED_BY_FIREWALL`` / ``FAILED`` / ...).
        Returns ``Paginated[QueryHistoryItem]``.
        """
        return await self._queries.list_queries(
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
            dataset_id=dataset_id,
            execution_status=execution_status,
            limit=limit,
        )

    async def get_query(self, query_id: str) -> Any:
        """Fetch a single query with every candidate, model id, error envelope."""
        return await self._queries.get_query(
            query_id=query_id,
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
        )

    async def fetch_query_result(self, query_id: str) -> Any:
        """Re-download the preview + presigned Parquet URL for a past query.

        The URL is ``None`` when the result TTL has elapsed (default
        24h) -- in that case the only option is to rerun the query
        via :meth:`ask` to materialise a fresh artifact.
        """
        return await self._queries.get_query_result(
            query_id=query_id,
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
        )

    async def billing_rollup(
        self,
        *,
        period: str = "day",
        date_from: Any | None = None,
        date_to: Any | None = None,
    ) -> Any:
        """Cost rollup over the per-call cost ledger.

        ``period`` is ``day`` / ``week`` / ``month``. Bounds default
        to "all time". Buckets with zero cost are omitted.
        """
        return await self._billing.rollup(
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
            period=period,
            date_from=date_from,
            date_to=date_to,
        )

    async def workspace_stats(self) -> Any:
        """Workspace summary: storage_used_bytes + 5 counts.

        Operator-traffic endpoint -- one COUNT(*) per metric, no
        caching. Cheap enough to poll once per minute for a
        dashboard.
        """
        return await self._stats.workspace_summary(
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
        )

    async def audit_log(
        self,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        resource_kind: str | None = None,
        limit: int = 100,
    ) -> Any:
        """Paginated audit-event reader. Newest first.

        Filters: ``event_type`` (e.g. ``dataset.created``),
        ``actor``, ``resource_kind``. Pass ``date_from`` / ``date_to``
        via the raw ``self.audit_events`` accessor when bounding the
        window matters.
        """
        return await self._audit_events.list_events(
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
            event_type=event_type,
            actor=actor,
            resource_kind=resource_kind,
            limit=limit,
        )

    async def cost_log(
        self,
        *,
        actor: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        limit: int = 100,
    ) -> Any:
        """Paginated per-call cost-event reader. Newest first."""
        return await self._cost_events.list_events(
            x_tenant_id=self._tenant_id,
            x_workspace_id=self._workspace_id,
            actor=actor,
            model=model,
            operation=operation,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Async file upload (26.5.11 :async endpoint)
    # ------------------------------------------------------------------

    async def upload_async(
        self,
        dataset_id: str,
        path: str | Path,
        *,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, str] | None = None,
    ) -> Any:
        """Upload + queue a PARSE_AND_INGEST job. Returns 202 envelope.

        Use this instead of :meth:`upload` for files large enough
        to risk an HTTP timeout (typically anything past a few MB
        with cold-cache describe calls). Poll ``GET /ingest-jobs/{job_id}``
        or stream ``GET /ingest-jobs/{job_id}/stream`` for progress.

        :param callback_url: Optional webhook URL. The server POSTs
            the terminal :class:`IngestJobRead` payload here (event
            ``ingest.succeeded`` or ``ingest.failed``) once stages
            2-10 finish. Setting this overrides any
            ``FLYQUERY_DEFAULT_CALLBACK_URL`` process-wide default.
        :param callback_secret: Optional shared secret. When set,
            every callback request carries an
            ``X-Flyquery-Signature: sha256=<hmac>`` header so the
            receiver can verify authenticity. Min 8 chars.
        :param callback_headers: Optional extra headers to append to
            every callback request. Reserved keys
            (``X-Flyquery-Signature``, ``X-Flyquery-Job-Id``,
            ``X-Flyquery-Event``, ``Content-Type``) are rejected by
            the server.
        """
        import json as _json

        p = Path(path)
        content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        files = {"file": (p.name, p.read_bytes(), content_type)}
        data: dict[str, str] = {}
        if callback_url:
            data["callback_url"] = callback_url
        if callback_secret:
            data["callback_secret"] = callback_secret
        if callback_headers:
            data["callback_headers"] = _json.dumps(callback_headers)
        r = await self._http.post(
            f"/api/v1/datasets/{quote(dataset_id)}/files:async",
            files=files,
            data=data or None,
        )
        r.raise_for_status()
        return r.json()  # {job_id, file_id, dataset_id, status}

    async def list_job_callbacks(
        self,
        job_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        """Webhook delivery audit log for ``job_id``.

        Returns the paginated ``CallbackDeliveryListResponse`` shape
        with one row per delivery attempt: URL, event type
        (``ingest.succeeded`` / ``ingest.failed``), status
        (``PENDING`` / ``DELIVERED`` / ``FAILED`` / ``DEAD``),
        attempt count, last HTTP status code + last error, and the
        next scheduled retry. Use this to confirm a webhook drop has
        cleared after a receiver outage.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        r = await self._http.get(
            f"/api/v1/ingest-jobs/{quote(job_id)}/callbacks",
            params=params,
        )
        r.raise_for_status()
        return r.json()

    # Sync mirrors for the v1 helpers (notebooks / CLIs).

    def recent_queries_sync(self, **kwargs: Any) -> Any:
        return asyncio.run(self.recent_queries(**kwargs))

    def get_query_sync(self, query_id: str) -> Any:
        return asyncio.run(self.get_query(query_id))

    def fetch_query_result_sync(self, query_id: str) -> Any:
        return asyncio.run(self.fetch_query_result(query_id))

    def billing_rollup_sync(self, **kwargs: Any) -> Any:
        return asyncio.run(self.billing_rollup(**kwargs))

    def workspace_stats_sync(self) -> Any:
        return asyncio.run(self.workspace_stats())

    def upload_async_sync(
        self,
        dataset_id: str,
        path: str | Path,
        *,
        callback_url: str | None = None,
        callback_secret: str | None = None,
        callback_headers: dict[str, str] | None = None,
    ) -> Any:
        return asyncio.run(
            self.upload_async(
                dataset_id,
                path,
                callback_url=callback_url,
                callback_secret=callback_secret,
                callback_headers=callback_headers,
            )
        )

    def list_job_callbacks_sync(self, job_id: str, **kwargs: Any) -> Any:
        return asyncio.run(self.list_job_callbacks(job_id, **kwargs))
