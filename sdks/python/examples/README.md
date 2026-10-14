# Python examples

These scripts use the convenience client from `flyquery_sdk.client` and the
repository's synthetic files. They write datasets and uploads to the selected
workspace. Use a development tenant and configure ingestion and query model
providers before running them.

First follow the service [quick start](../../../QUICKSTART.md). Install the SDK
into your own Python environment, then supply the URL and existing workspace:

```bash
uv pip install -e ./sdks/python
export FLYQUERY_URL=http://127.0.0.1:8520
export FLYQUERY_TENANT_ID=example-tenant
# Replace with the UUID returned when your workspace was created.
export FLYQUERY_WORKSPACE_ID=2e5aa824-2f02-4b71-8939-098989024888
python sdks/python/examples/01_quickstart.py
```

| Script | What it does |
|---|---|
| `01_quickstart.py` | Finds or creates a dataset, uploads synthetic files and asks a batch of questions. |
| `02_bulk_ingest.py` | Uploads valid fixtures alongside a malformed file, prints each outcome and removes its temporary fixture. |

Inspect per-file and per-question statuses. Model and embedding calls may incur
provider charges; these examples are not part of the SDK's provider-free test
suite. For setup, authentication, explicit generated API calls and errors, read
the [Python SDK guide](../README.md).
