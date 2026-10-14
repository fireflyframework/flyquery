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

# syntax=docker/dockerfile:1.7
#
# Multi-stage Docker build for flyquery.
#
# Dependencies come from public first-party sources pinned by uv.lock.
# Build: docker build --tag flyquery:local .

ARG PYTHON_VERSION=3.13

# ---- Stage 1: builder -----------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy

# Stage the project manifests for layer caching. README.md is required
# by hatchling because pyproject.toml declares ``readme = "README.md"``.
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY README.md      /app/README.md
COPY LICENSE        /app/LICENSE
COPY uv.lock        /app/uv.lock

RUN --mount=type=cache,target=/root/.cache/uv \
    uv lock --check \
    && uv sync --frozen --no-install-project --no-dev --no-editable

# Copy the application source + migrations and finalise the install.
COPY src/         /app/src/
COPY migrations/  /app/migrations/
COPY alembic.ini  /app/alembic.ini
COPY pyfly.yaml   /app/pyfly.yaml
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


# ---- Stage 2: runtime -----------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

# System deps for file format handling:
# * ``curl``                                           -- container healthchecks
# * ``libheif1``                                       -- pillow-heif (HEIC / HEIF / AVIF)
# * ``libcairo2`` + ``libpango*`` + ``libgdk-pixbuf*`` -- cairosvg (SVG)
#
# Note: flyquery does not perform OCR; tesseract is not needed.
# LibreOffice (`soffice`) is intentionally NOT installed by default;
# operators that want the in-container subprocess path set
# ``FLYQUERY_OFFICE_CONVERTER=libreoffice`` and extend this Dockerfile
# with ``libreoffice-core``. The canonical Office path is the
# Gotenberg sidecar (see docker-compose.yml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libheif1 \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --shell /usr/sbin/nologin --no-create-home flyquery

WORKDIR /app
# Copy artefacts as the unprivileged ``flyquery`` user so the runtime always
# has read access to bundled resources (e.g. resources/prompts/*.yaml)
# regardless of whatever host umask produced the source tree.
COPY --from=builder --chown=flyquery:flyquery /app/.venv         /app/.venv
COPY --from=builder --chown=flyquery:flyquery /app/src           /app/src
COPY --from=builder --chown=flyquery:flyquery /app/migrations    /app/migrations
COPY --from=builder --chown=flyquery:flyquery /app/alembic.ini   /app/alembic.ini
COPY --from=builder --chown=flyquery:flyquery /app/pyfly.yaml    /app/pyfly.yaml
COPY --from=builder --chown=flyquery:flyquery /app/docker-entrypoint.sh /app/docker-entrypoint.sh
# Ensure files are world-readable inside the image -- mktemp/host umask
# sometimes ships 0600 files which then fail at boot under the flyquery user.
RUN find /app -type f -exec chmod a+r {} + \
    && find /app -type d -exec chmod a+rx {} + \
    && chmod a+x /app/docker-entrypoint.sh

# Stateful directory that the runtime writes to (BM25 SQLite corpus +
# any other on-disk projection). Pre-created with flyquery ownership so
# the named volume mount inherits the right permissions on first
# use; FLYQUERY_CORPUS_PATH defaults to /app/flyquery-data/corpus.db in
# the compose stack.
RUN mkdir -p /app/flyquery-data && chown -R flyquery:flyquery /app/flyquery-data

ENV PYTHONPATH=/app/src

USER flyquery
EXPOSE 8520

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["serve"]
