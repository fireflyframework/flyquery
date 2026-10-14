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

"""Integration-test fixtures: Postgres + Redis + MinIO containers."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from docker.errors import ImageNotFound
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        # Container exposes the default `test` user as SUPERUSER which
        # would silently BYPASSRLS (memory: postgres_test_role_bypasses_rls).
        # We provision flyquery_admin (BYPASSRLS) + flyquery_app (no bypass)
        # via the RLS migration / fixture below.
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer() as r:
        yield r


@pytest.fixture(scope="session")
def minio_container() -> Iterator[MinioContainer]:
    # Community registry images disappeared; retain a real MinIO server built
    # from pinned upstream source instead of substituting an S3 mock.
    prepared = os.environ.get("FLYQUERY_TEST_MINIO_IMAGE")
    if prepared:
        with MinioContainer(image=prepared) as m:
            yield m
        return
    image = DockerImage(
        path=Path(__file__).parent / "minio",
        tag=f"flyquery-integration-minio:{uuid4().hex}",
        clean_up=False,
    )
    try:
        image.build()
        with MinioContainer(image=str(image)) as m:
            yield m
    finally:
        # Delete only this fixture's tag and preserve cached parent layers.
        with suppress(ImageNotFound):
            image.get_docker_client().client.images.remove(str(image), force=False, noprune=True)
        image.remove()


# ---------------------------------------------------------------------------
# fake-gcs-server (GCS conformance)
# ---------------------------------------------------------------------------


class FakeGcsContainer(DockerContainer):
    """Thin wrapper around fsouza/fake-gcs-server for integration tests."""

    GCS_PORT = 4443

    def __init__(self) -> None:
        super().__init__("fsouza/fake-gcs-server:latest")
        self.with_command("-scheme http -port 4443")
        self.with_exposed_ports(self.GCS_PORT)

    def get_url(self) -> str:
        host = self.get_container_host_ip()
        port = self.get_exposed_port(self.GCS_PORT)
        return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def fake_gcs_container() -> Iterator[Any]:
    """Session-scoped fake-gcs-server testcontainer.

    If Docker is unavailable or the image cannot be pulled the fixture
    yields ``None`` and GCS tests are skipped via the ``store`` fixture
    below.
    """
    try:
        with FakeGcsContainer() as c:
            wait_for_logs(c, "server started", timeout=30)
            yield c
    except Exception:  # pragma: no cover
        yield None


# ---------------------------------------------------------------------------
# Azurite (Azure Blob conformance)
# ---------------------------------------------------------------------------


class AzuriteContainer(DockerContainer):
    """Thin wrapper around mcr.microsoft.com/azure-storage/azurite."""

    BLOB_PORT = 10000
    # Well-known Azurite dev account + key
    ACCOUNT_NAME = "devstoreaccount1"
    ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tiqIFBg=="

    def __init__(self) -> None:
        super().__init__("mcr.microsoft.com/azure-storage/azurite:latest")
        self.with_command("azurite-blob --blobHost 0.0.0.0 --blobPort 10000")
        self.with_exposed_ports(self.BLOB_PORT)

    def get_connection_string(self) -> str:
        host = self.get_container_host_ip()
        port = self.get_exposed_port(self.BLOB_PORT)
        return (
            f"DefaultEndpointsProtocol=http;"
            f"AccountName={self.ACCOUNT_NAME};"
            f"AccountKey={self.ACCOUNT_KEY};"
            f"BlobEndpoint=http://{host}:{port}/{self.ACCOUNT_NAME};"
        )


@pytest.fixture(scope="session")
def azurite_container() -> Iterator[Any]:
    """Session-scoped Azurite testcontainer.

    Yields ``None`` when Docker is unavailable so Azure tests can skip.
    """
    try:
        with AzuriteContainer() as c:
            wait_for_logs(c, "Azurite Blob service is successfully listening", timeout=30)
            yield c
    except Exception:  # pragma: no cover
        yield None


def _build_urls(postgres_container: PostgresContainer) -> tuple[str, str, str]:
    """Return (async_url, admin_url, app_url) from the container's sync URL."""
    sync_url = postgres_container.get_connection_url()  # postgresql+psycopg2://...
    async_url = sync_url.replace("+psycopg2", "+asyncpg").replace("+psycopg", "+asyncpg")
    admin_url = sync_url.replace("+psycopg2", "+psycopg")
    app_url = async_url.replace(
        f"//{postgres_container.username}:{postgres_container.password}",
        "//flyquery_app:flyquery_app",
    )
    return async_url, admin_url, app_url


@pytest.fixture(scope="session")
def run_migrations(
    postgres_container: PostgresContainer,
) -> None:
    """Run ``alembic upgrade head`` once per session against the test DB.

    This fixture is session-scoped so migrations run exactly once regardless
    of the order tests are collected. CRUD tests depend on it implicitly via
    the ``autouse`` ``configure_env`` fixture which pulls it in as a dependency.
    """
    _, admin_url, _ = _build_urls(postgres_container)
    env = {**os.environ, "FLYQUERY_DATABASE_URL_ADMIN": admin_url}
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)


@pytest.fixture(scope="session")
def session_env(
    run_migrations: None,
    postgres_container: PostgresContainer,
    redis_container: RedisContainer,
    minio_container: MinioContainer,
) -> None:
    """Set session-wide env vars so pyfly picks them up at startup."""
    async_url, admin_url, app_url = _build_urls(postgres_container)
    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(redis_container.port)
    redis_url = f"redis://{redis_host}:{redis_port}/0"

    # Use admin URL so pyfly's EDA / DDL infra startup has DDL rights.
    # Per-test RLS isolation uses the app-role URL (set in configure_env).
    os.environ["FLYQUERY_DATABASE_URL"] = admin_url.replace("+psycopg", "+asyncpg")
    os.environ["FLYQUERY_DATABASE_URL_ADMIN"] = admin_url
    os.environ["FLYQUERY_REDIS_URL"] = redis_url
    os.environ["FLYQUERY_OBJECT_STORE"] = "local"
    os.environ["FLYQUERY_OBJECT_STORE_BASE"] = "/tmp/flyquery-test"
    os.environ["FLYQUERY_RUN_MIGRATIONS"] = "false"
    os.environ["AWS_ACCESS_KEY_ID"] = minio_container.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = minio_container.secret_key


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def started_app(session_env: None) -> AsyncIterator[None]:
    """Start the pyfly application (run lifespan startup) once per session.

    ``httpx.ASGITransport`` does not trigger ASGI lifespan events, so the
    pyfly application context (including ``RelationalAutoConfiguration`` and
    all ``@auto_configuration`` beans) never gets started. This fixture
    drives the startup / shutdown lifecycle manually so every integration
    test sees a fully-initialised DI container.

    Must be async and share the session event loop so asyncpg connection
    pools are bound to the same loop that runs the tests.
    """
    from flyquery.main import _pyfly

    if not getattr(_pyfly.context, "_started", False):
        await _pyfly.startup()
    yield


@pytest.fixture(autouse=True)
def configure_env(
    monkeypatch: pytest.MonkeyPatch,
    postgres_container: PostgresContainer,
    redis_container: RedisContainer,
    minio_container: MinioContainer,
    started_app: None,
) -> None:
    async_url, admin_url, app_url = _build_urls(postgres_container)
    monkeypatch.setenv("FLYQUERY_DATABASE_URL", async_url)
    monkeypatch.setenv("FLYQUERY_DATABASE_URL_ADMIN", admin_url)
    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(redis_container.port)
    monkeypatch.setenv("FLYQUERY_REDIS_URL", f"redis://{redis_host}:{redis_port}/0")
    monkeypatch.setenv("FLYQUERY_OBJECT_STORE", "s3")
    monkeypatch.setenv(
        "FLYQUERY_OBJECT_STORE_BASE", f"s3://{minio_container.get_config()['endpoint']}/flyquery-test"
    )
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", minio_container.access_key)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", minio_container.secret_key)
    monkeypatch.setenv("FLYQUERY_RUN_MIGRATIONS", "false")
    # After migration 0007 provisions flyquery_app (NOSUPERUSER), the runtime
    # URL must authenticate as that role so RLS policies actually fire.
    # The admin URL (BYPASSRLS) is kept in FLYQUERY_DATABASE_URL_ADMIN for
    # migrations and seeding (memory: postgres_test_role_bypasses_rls).
    monkeypatch.setenv("FLYQUERY_DATABASE_URL", app_url)
