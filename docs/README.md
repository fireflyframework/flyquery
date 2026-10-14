<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark) and (max-width: 600px)" srcset="assets/brand/banner-dark-mobile.svg">
  <source media="(max-width: 600px)" srcset="assets/brand/banner-light-mobile.svg">
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/banner-dark.svg">
  <img src="assets/brand/banner-light.svg" alt="flyquery by Firefly" width="100%">
</picture>

### **Documentation**

</div>

---

The complete reference set for **flyquery**. Start with the top-level
[QUICKSTART.md](../QUICKSTART.md) for your first upload + query, the main
[README.md](../README.md) for the elevator pitch, and
[payload-reference.md](payload-reference.md) for the authoritative wire-payload
guide. Come here when you need a specific corner of the system.

---

## Reading paths

Pick the entry point that matches what you're trying to do.

### "I just want to call the API"

1. [**../QUICKSTART.md**](../QUICKSTART.md) — ten minutes from clone to your
   first upload, ingest, and answered question. HTTP-only, no API keys required
   for format parsing.
2. [**payload-reference.md**](payload-reference.md) — composing the request:
   every wire payload (upload, query, conversation, SSE frames, RFC 7807
   errors).
3. [**api-reference.md**](api-reference.md) — every endpoint, header, query
   parameter, DTO, scope, and status code.
4. [**glossary.md**](glossary.md) — terms the API uses (dataset, table,
   snapshot, schema object, relation, example, conversation turn, ingest job, …).

### "I'm subscribing to the EDA surface"

1. [**eda-events.md**](eda-events.md) — the two topics flyquery publishes
   (`flyquery.ingest` and `flyquery.schema`), the payload on each event, the
   durable Postgres outbox default.
2. [**async-ingest.md**](async-ingest.md) — how `IngestWorker` consumes the
   `flyquery.ingest` topic, job lifecycle, cooperative cancel, retry + dead-letter.
3. [**workers.md**](workers.md) — the worker fleet topology (IngestWorker +
   RetentionWorker), CLI subcommands, scaling, recovery, and deployment forms.
4. [**architecture.md**](architecture.md) — how `pyfly.eda.EventPublisher` is
   injected into the ingestion and query services.

### "I want to understand how it works"

1. [**architecture.md**](architecture.md) — the data model, storage architecture,
   multi-tenancy, hexagonal ports, lock-step modules.
2. [**pipeline.md**](pipeline.md) — upload + 10-stage ingestion and query
   pipeline (Grounding → Generation → Critic → Explainer) end-to-end with ASCII
   diagrams; mode coupling (sync vs async via EDA).
3. [**ingestion.md**](ingestion.md) — stage-by-stage ingestion detail: each
   stage's inputs, outputs, skip policy, and SSE events.
4. [**schema-detection.md**](schema-detection.md) — XLSX/CSV/JSON parsing
   deep dive, type inference, drift detection, PII tagging, and the
   column-name proposer agent.
5. [**prompts.md**](prompts.md) — catalog of the 7 agent prompts: instruction
   text, input shape, output schema.

### "I'm running this in production"

1. [**deployment.md**](deployment.md) — reference topologies, env vars,
   migration step, health checks, observability, backup.
2. [**deployment-topology.md**](deployment-topology.md) — single-node vs
   multi-node vs HA ASCII diagrams; scaling up (more workers, Postgres separate,
   Redis separate, S3 object store).
3. [**cicd.md**](cicd.md) — CI workflows (lint, test-unit, test-integration,
   lockstep-check, publish-sdk), tag-triggered releases, branch protection.
4. [**operations-runbook.md**](operations-runbook.md) — cold start, daily
   checks, common error fixes, GDPR purge runbook, key rotation, incident
   response.
5. [**troubleshooting.md**](troubleshooting.md) — symptom → root cause → fix
   for upload failures, stuck ingest jobs, NULL embeddings, RLS returning zero
   rows, agent timeouts.

### "I'm building / extending"

1. [**architecture.md**](architecture.md) — hexagonal ports and where to plug
   new adapters (ObjectStore, FileReader, VectorStore, PiiScanner,
   SemanticCompiler).
2. [**pipeline.md**](pipeline.md) — the orchestrator and how stages are chained.
3. [**concurrency.md**](concurrency.md) — AsyncSession scoping, RLS GUC binding,
   EDA worker concurrency, DuckDB per-request isolation, ObjectStore async.
4. [**quality.md**](quality.md) — testing strategy: unit, integration,
   conformance (ObjectStore adapters), parser fixtures, pipeline tests,
   LLM-gated tests.
5. [**consumers.md**](consumers.md) — building a service that consumes flyquery:
   SDK patterns, agent-token model, idempotency, EDA subscription recipes.

### "Something broke"

1. [**troubleshooting.md**](troubleshooting.md) — symptom-first index of common
   failure modes.
2. [**operations-runbook.md**](operations-runbook.md) — step-by-step incident
   response template.
3. [**concurrency.md**](concurrency.md) — for multi-worker race conditions and
   RLS mis-configuration symptoms.

### "Designing the future"

1. [**firefly-intelligence-system.md**](firefly-intelligence-system.md) — the
   three-pillar narrative: how flycanon, flyradar, and flyquery cooperate.
2. [**integration-with-firefly-os.md**](integration-with-firefly-os.md) —
   concrete integration recipes: flyradar referencing a flyquery dataset,
   flycanon RAG over metadata about a flyquery dataset.
3. [**auto-learning.md**](auto-learning.md) — the PROPOSED → APPROVED example
   cycle and the v1 online-learning roadmap.
4. [**scale-and-performance.md**](scale-and-performance.md) — throughput
   numbers, bottlenecks, tuning knobs, capacity planning.
5. [**superpowers/specs/2026-05-22-flyquery-design.md**](superpowers/specs/2026-05-22-flyquery-design.md) — the approved design spec.

---

## Document catalogue

| Document | Read it when… |
|----------|--------------|
| [../QUICKSTART.md](../QUICKSTART.md) | You want your first upload + query in ten minutes (HTTP / curl). |
| [architecture.md](architecture.md) | You need the data model, storage design, multi-tenancy, hexagonal ports, lock-step modules. |
| [pipeline.md](pipeline.md) | You're touching the ingestion or query orchestrator, or tracing a slow ingest / wrong SQL. |
| [ingestion.md](ingestion.md) | You need stage-by-stage ingestion detail: each stage's skip policy, SSE events, re-upload semantics. |
| [async-ingest.md](async-ingest.md) | You're operating the IngestWorker: lifecycle, job kinds, cooperative cancel, retry, dead-letter. |
| [file-formats.md](file-formats.md) | You need the per-format reader matrix and edge-case behaviour (BOM, merged cells, ragged JSON). |
| [api-reference.md](api-reference.md) | You're integrating with the HTTP API and need every endpoint, shape, and status code. |
| [payload-reference.md](payload-reference.md) | You're composing the request payload — every field, option, and example. |
| [eda-events.md](eda-events.md) | You're subscribing to `flyquery.ingest` or `flyquery.schema` EDA topics. |
| [conversations.md](conversations.md) | You're building chat-style UX on flyquery — conversation turns, drill-down semantics, snapshot pinning. |
| [prompts.md](prompts.md) | You want the exact instruction text and output schema for any of the 7 agents. |
| [auto-learning.md](auto-learning.md) | You want to understand or tune the PROPOSED → APPROVED example cycle. |
| [semantic-layer.md](semantic-layer.md) | You're authoring MetricFlow YAML metrics or debugging the SEMANTIC_LAYER query path. |
| [security-model.md](security-model.md) | You need RLS details, AST firewall rules, PII policy, agent token verification. |
| [pii.md](pii.md) | You're configuring PII scanners, policies, or debugging a PII-related ingest failure. |
| [deployment.md](deployment.md) | You're deploying flyquery — env vars, topologies, migration, health checks, observability. |
| [deployment-topology.md](deployment-topology.md) | You need the single-node vs multi-node vs HA topology diagrams. |
| [cicd.md](cicd.md) | You're cutting a release or wiring CI/CD — PR gate, SDK publish, secrets. |
| [operations-runbook.md](operations-runbook.md) | You're running flyquery in production — cold start, daily checks, GDPR purge, incident response. |
| [troubleshooting.md](troubleshooting.md) | The service / ingest / query surface is misbehaving — symptom → root cause → fix. |
| [concurrency.md](concurrency.md) | You're running multiple replicas / workers and need the async + transactional boundary picture. |
| [consumers.md](consumers.md) | You're building a service that consumes flyquery — SDK patterns, agent tokens, EDA subscription. |
| [integration-with-firefly-os.md](integration-with-firefly-os.md) | You're wiring flyquery with flycanon or flyradar. |
| [glossary.md](glossary.md) | You need a precise definition for a term the API or docs use. |
| [scale-and-performance.md](scale-and-performance.md) | You're capacity-planning or tuning FLYQUERY_* knobs. |
| [billing.md](billing.md) | You're tracking per-query and per-ingest LLM cost via `flyquery_cost_events` and `GET /api/v1/billing`. |
| [stats.md](stats.md) | You're rendering a workspace dashboard via `GET /api/v1/stats`. |
| [schema-detection.md](schema-detection.md) | You're debugging XLSX/CSV/JSON parsing, type inference, drift detection, or the column-name proposer. |
| [workers.md](workers.md) | You're running, scaling, or recovering the `IngestWorker` + `RetentionWorker` fleet. |
| [quality.md](quality.md) | You're running or extending the test suite — unit, integration, parser fixtures, pipeline tests. |
| [firefly-intelligence-system.md](firefly-intelligence-system.md) | You want the three-pillar narrative (flycanon + flyradar + flyquery). |
| [../sdks/python/README.md](../sdks/python/README.md) | You're integrating from Python (async-first SDK, Pydantic types). |
| [../sdks/java/README.md](../sdks/java/README.md) | You're integrating from Java / Spring Boot. |

---

## Cross-cutting topics

| Topic | Primary | Secondary |
|-------|---------|-----------|
| Upload + ingest pipeline | [pipeline.md](pipeline.md) | [ingestion.md](ingestion.md), [async-ingest.md](async-ingest.md) |
| Query pipeline (Grounding → Explainer) | [pipeline.md](pipeline.md) | [architecture.md § Query pipeline](architecture.md#7-query-pipeline-4-agents) |
| Agent prompts (instruction text) | [prompts.md](prompts.md) | `src/flyquery/core/agents/*.py` |
| Hybrid retrieval (BM25 + pgvector + RRF) | [architecture.md](architecture.md) | [pipeline.md](pipeline.md) |
| Conversation drill-down | [conversations.md](conversations.md) | [api-reference.md § Conversations](api-reference.md) |
| Auto-learning (PROPOSED → APPROVED) | [auto-learning.md](auto-learning.md) | [pipeline.md](pipeline.md) |
| Semantic layer (MetricFlow) | [semantic-layer.md](semantic-layer.md) | [pipeline.md § SEMANTIC_LAYER path](pipeline.md) |
| PII scanning | [pii.md](pii.md) | [security-model.md § 7](security-model.md) |
| RLS + multi-tenancy | [security-model.md](security-model.md) | [architecture.md § Multi-tenancy](architecture.md) |
| AST firewall | [security-model.md § 6](security-model.md) | [pipeline.md](pipeline.md) |
| Agent-token surface | [security-model.md § 4](security-model.md) | [api-reference.md](api-reference.md) |
| EDA / typed events | [eda-events.md](eda-events.md) | [async-ingest.md](async-ingest.md) |
| Snapshot versioning + pinning | [ingestion.md](ingestion.md) | [conversations.md](conversations.md) |
| Schema drift + rename detection | [schema-detection.md](schema-detection.md) | [ingestion.md § RENAMED_CANDIDATE](ingestion.md) |
| Format detection + parser dispatch | [schema-detection.md](schema-detection.md) | [file-formats.md](file-formats.md) |
| Worker fleet + scaling | [workers.md](workers.md) | [async-ingest.md](async-ingest.md), [deployment-topology.md](deployment-topology.md) |
| Object-store layout | [architecture.md § Storage architecture](architecture.md) | [deployment.md](deployment.md) |
| Billing + cost stream | [billing.md](billing.md) | [api-reference.md](api-reference.md), [cost-tracking.md](cost-tracking.md) |
| Workspace stats | [stats.md](stats.md) | [api-reference.md](api-reference.md) |
| Lock-step modules | [architecture.md § Lock-step](architecture.md) | [cicd.md](cicd.md) |
| GDPR purge | [operations-runbook.md](operations-runbook.md) | [security-model.md § Upload security](security-model.md) |
| RFC 7807 error envelope | [payload-reference.md](payload-reference.md) | [api-reference.md](api-reference.md) |
| Multi-replica concurrency | [concurrency.md](concurrency.md) | [workers.md](workers.md), [async-ingest.md](async-ingest.md) |

---

## Generating the OpenAPI spec

```bash
# Against a running service:
curl -s http://localhost:8520/openapi.json | jq

# Via the task target (writes to ./openapi.json and checks drift):
task openapi-snapshot
```

The Swagger UI at `/docs` and Redoc at `/redoc` both browse the live spec.

## Repository and identity

See [branding.md](branding.md) for the canonical repository, light/dark and
mobile banners, artwork provenance, and package-registry transition.
