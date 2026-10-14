<!-- Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0 -->

# MinIO integration-test server

The S3 tests run against the real MinIO server. The community registry images
used by testcontainers are no longer anonymously available, so this build uses
the unchanged [official MinIO source](https://github.com/minio/minio/tree/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a).

| Input | Pinned identity |
| --- | --- |
| MinIO source | `RELEASE.2025-10-15T17-29-55Z`, commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a` |
| Go builder | `golang:1.24.8-alpine@sha256:3d78beb141d98f42337f1252ecf2a5f20374109929a4c3f6817f9e4179cc0ae5` |
| Runtime | `alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412` |

The build verifies the checked-out commit and Go modules against the upstream
`go.sum`. The image retains MinIO's complete AGPL license at
`/usr/share/licenses/minio/LICENSE` and records the source revision in its OCI
labels. This repository's Apache 2.0 license applies to the build recipe;
the MinIO server remains under its upstream AGPL license. The image runs as
user `10001`, with updates disabled and an ephemeral `/data` directory.

CI builds the image before starting pytest, so compilation uses the job's build
budget and each test keeps its normal timeout. It passes the exact local tag
through `FLYQUERY_TEST_MINIO_IMAGE`. Local pytest builds a uniquely tagged image
when that variable is absent, then removes its own tag after container teardown
while retaining shared build layers.

To prepare a local test run explicitly:

```sh
docker build --tag flyquery-integration-minio:local tests/integration/minio
FLYQUERY_TEST_MINIO_IMAGE=flyquery-integration-minio:local \
  uv run pytest tests/integration -m 'not llm'
```

These commands require a working local Docker daemon, outbound access to the
pinned base images and upstream source, and the development, S3 and file-reader
dependencies. They create test containers and do not require model-provider
credentials. Select a dedicated Docker endpoint through the child process's
`DOCKER_HOST` when the desktop default daemon is unavailable.

When updating a pin, inspect the upstream source and license, verify the image
digests, and run the complete integration suite against the rebuilt server.
Keep the RLS, upload and S3 assertions unchanged during prerequisite changes.
