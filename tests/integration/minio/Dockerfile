# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
# This build recipe is Apache-2.0; the unchanged MinIO server is AGPL-3.0.
FROM golang:1.24.8-alpine@sha256:3d78beb141d98f42337f1252ecf2a5f20374109929a4c3f6817f9e4179cc0ae5 AS build

RUN apk add --no-cache git
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/minio/minio.git \
    && git fetch --depth=1 origin 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
RUN go mod download \
    && go mod verify \
    && go build -trimpath -o /out/minio .

FROM alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412
RUN apk add --no-cache ca-certificates \
    && adduser -D -u 10001 minio \
    && mkdir /data \
    && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/licenses/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
    org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
    org.opencontainers.image.licenses="AGPL-3.0-only"
ENV MINIO_UPDATE=off
USER minio
EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/minio"]
