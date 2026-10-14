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

"""Verify the generated SDK can be imported and exposes the expected split API classes.

Each controller tag (workspaces, datasets, files, ...) must produce a
dedicated API class (WorkspacesApi, DatasetsApi, FilesApi, ...) rather
than collapsing everything into DefaultApi.
"""

import os
import sys

# Ensure the SDK package directory is on the path when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_imports():
    from flyquery_sdk import ApiClient, Configuration  # noqa: F401

    assert isinstance(ApiClient, type)
    assert isinstance(Configuration, type)


def test_split_api_classes():
    """All major resource groups must have a dedicated API class.

    Class names track the current OpenAPI tag taxonomy:
        - SchemaApi   -> SchemaChangesApi + SchemaObjectsApi
        - SemanticApi -> SemanticMetricsApi + SemanticDimensionsApi
        - IngestApi   -> IngestJobsApi
        - SqlApi      -> SqlExecuteApi
        - MetaApi     -> VersionApi
        - AgentSqlApi -> AgentSqlExecuteApi
    """
    from flyquery_sdk.api import (  # noqa: F401
        AgentExamplesApi,
        AgentQueryApi,
        AgentSqlExecuteApi,
        AgentTokensApi,
        AgentVersionApi,
        AuditEventsApi,
        BillingApi,
        ConversationsApi,
        CostEventsApi,
        DatasetsApi,
        ExamplesApi,
        FilesApi,
        GlossaryApi,
        IngestJobsApi,
        QueriesApi,
        QueryApi,
        RelationsApi,
        SchemaChangesApi,
        SchemaObjectsApi,
        SemanticDimensionsApi,
        SemanticMetricsApi,
        SqlExecuteApi,
        StatsApi,
        TablesApi,
        TablesDeriveApi,
        VersionApi,
        WorkspacesApi,
    )

    assert WorkspacesApi.__module__.endswith(".workspaces_api")
    assert DatasetsApi.__module__.endswith(".datasets_api")
    assert QueryApi.__module__.endswith(".query_api")
    assert FilesApi.__module__.endswith(".files_api")
    assert AgentQueryApi.__module__.endswith(".agent_query_api")
    assert SchemaChangesApi.__module__.endswith(".schema_changes_api")
    assert SemanticMetricsApi.__module__.endswith(".semantic_metrics_api")


def test_no_stale_split_classes_leaked():
    """Stale class names from prior OpenAPI splits must not still be exported.

    Regression: ``task sdk:python`` used to skip the pruning of stale
    api/*.py files, so importable but useless ``IngestApi`` / ``SqlApi`` /
    ``SchemaApi`` classes from older spec versions stayed around long
    after the tags had been split. New spec runs now ``rm -rf`` the
    api/ + models/ directories before regeneration.
    """
    import importlib

    api_pkg = importlib.import_module("flyquery_sdk.api")
    forbidden = {
        "DefaultApi",
        "IngestApi",
        "MetaApi",
        "SchemaApi",
        "SemanticApi",
        "SqlApi",
        "AgentSqlApi",
    }
    leaked = forbidden & set(dir(api_pkg))
    assert not leaked, (
        f"Stale API classes still exported: {leaked}. "
        "Re-run `task sdk:python` after pulling latest Taskfile.yml."
    )


def test_configuration_can_be_constructed():
    from flyquery_sdk import Configuration

    cfg = Configuration(host="http://localhost:8520")
    assert cfg.host == "http://localhost:8520"


def test_api_client_can_be_constructed():
    from flyquery_sdk import ApiClient, Configuration

    cfg = Configuration(host="http://localhost:8520")
    client = ApiClient(configuration=cfg)
    assert client is not None
    # Don't close the async client in sync context — just verify construction


def test_flyquery_client_exposes_v1_accessors():
    """The hand-written FlyqueryClient must surface every v1.0 (26.5.11) API."""
    from flyquery_sdk.client import FlyqueryClient

    fc = FlyqueryClient(
        base_url="http://localhost:8520",
        tenant_id="acme",
        workspace_id="finance",
    )
    # v1 read surfaces
    assert fc.queries is not None
    assert fc.billing is not None
    assert fc.stats is not None
    assert fc.audit_events is not None
    assert fc.cost_events is not None
    # legacy accessors still present
    assert fc.workspaces is not None
    assert fc.datasets is not None
    assert fc.files is not None
    assert fc.tables is not None
    assert fc.query is not None
    # ergonomic helpers exist (sync mirrors so we don't need an event loop)
    assert callable(fc.recent_queries_sync)
    assert callable(fc.get_query_sync)
    assert callable(fc.fetch_query_result_sync)
    assert callable(fc.billing_rollup_sync)
    assert callable(fc.workspace_stats_sync)
    assert callable(fc.upload_async_sync)
