# flyquery — PII

## Table of Contents

1. [Overview](#1-overview)
2. [Three scanners](#2-three-scanners)
3. [Three policies](#3-three-policies)
4. [Ordering guarantee](#4-ordering-guarantee)
5. [Re-redact on late tag flip](#5-re-redact-on-late-tag-flip)
6. [PII in query results](#6-pii-in-query-results)
7. [Custom regex extension](#7-custom-regex-extension)
8. [PII tags on schema objects](#8-pii-tags-on-schema-objects)
9. [Configuration reference](#9-configuration-reference)

---

## 1. Overview

flyquery classifies columns for personally identifiable information (PII)
and applies a configurable policy that controls whether PII-containing
columns are queryable and whether sample values are retained.

PII scanning runs in two places:

1. **Stage 4 (sample)** — the configured scanner checks the original value
   batch before filtering it. Redact/reject applies to the column immediately;
   the stored empty list prevents later profiles from supplying its values.
   Warn mode keeps only clean samples. A disabled scanner is an explicit opt-out.
2. **Stage 8 (PII tag)** — the configured scanner classifies each column
   using its name, description, samples, and up to 100 stored profile values.
   It sets `pii_tag` and `pii_source` before embedding and retrieval. A value
   after the sampled prefix can therefore still trigger redact/reject.

The scanner and policy are both configurable — globally via environment
variables or per-dataset via `ingest_policy_json`.

---

## 2. Three scanners

`FLYQUERY_PII_SCANNER` selects the scanner.

### regex (default)

Rule-based scanner using pattern matching on column names and sample values.
Built-in patterns cover:
- Email addresses (`.*email.*`, `[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}`)
- Phone numbers (E.164 patterns, national-format variants)
- Social security numbers / national IDs (US SSN, UK NI, EU formats)
- Credit card numbers (Luhn-valid 13–19 digit sequences)
- IP addresses (IPv4 and IPv6)
- Dates of birth (when combined with `dob`, `birth_date` column name signals)
- Passport and driver's licence patterns (configurable; disabled by default)

Extend via `FLYQUERY_PII_REGEX_PATTERNS_PATH` (see §7).

**Pros:** Fast; no external dependency; works offline; easily auditable.
**Cons:** Higher false-positive rate on numeric columns with Luhn-like
sequences; misses semantic PII (e.g., "manager_name" → free-text names).

### presidio

Uses [Microsoft Presidio](https://github.com/microsoft/presidio) for NER-
based PII detection. Detects names, locations, organisations, dates,
credit-card numbers, and many more entity types via spaCy models.

Enable by setting `FLYQUERY_PII_SCANNER=presidio`. Requires the
`presidio-analyzer` and `presidio-anonymizer` packages and a spaCy model
(`FLYQUERY_PRESIDIO_SPACY_MODEL`, default `en_core_web_sm`).

**Pros:** Lower false-positive rate; catches semantic PII (names in free-text
columns).
**Cons:** Slower; requires `presidio` extra (`pip install 'flyquery[presidio]'`);
spaCy model download on first run.

### disabled

`FLYQUERY_PII_SCANNER=disabled` — PII scanning is skipped entirely. Samples
are written without any PII gate. Stage 8 still runs but all columns are
tagged `pii_tag=NONE, pii_source=null`.

Use only in air-gapped environments where data is pre-classified, or in
development with synthetic data.

---

## 3. Three policies

`FLYQUERY_PII_POLICY_SAMPLES` applies at stage 4 (sample gate) and stage 8
(tag gate) for sample values:

| Policy | What happens on PII match |
|--------|--------------------------|
| `warn` | Tag the column and continue. Sampling still drops individual PII values. Profiles may expose values when clean samples remain; this policy does not promise redaction. |
| `redact` (recommended) | Tag the column and store `sample_values_json=[]`. Embedding inputs, schema retrieval metadata, and value catalogs cannot recover values from its profile. The column remains queryable. |
| `reject` | Tag the column, store the empty sample list, and set `is_active=false`. Embedding and retrieval exclude the column until it is reviewed. |

`FLYQUERY_PII_POLICY_RESULTS` controls what happens when PII is detected in
query result rows (post-execution scan by the Explainer):

| Policy | What happens |
|--------|-------------|
| `warn` (default) | `pii_findings_json` populated on `flyquery_queries` row. Result is returned unchanged. |
| `redact` | PII-matching cells in the result preview are replaced with `[REDACTED]`. Full result in object storage is not modified. |
| `reject` | Query returns `422` with `error_code=PII_IN_RESULTS`. |

Policies can be overridden per-dataset via `ingest_policy_json`:
```json
{
  "pii_policy_samples": "redact",
  "pii_policy_results": "warn",
  "pii_disabled": false
}
```

---

## 4. Ordering guarantee

The PII gate runs BEFORE sample persistence on first ingest:

```
Stage 4 (sample):
  For each column value batch:
    1. Classify the original values, name, and description
    2. IF match AND policy=redact → tag; persist []
    3. IF match AND policy=reject → tag; deactivate column; persist []
    4. IF match AND policy=warn → tag; persist only individually clean values
    5. IF no match → persist clean values
    6. IF all values were filtered or the column was already tagged → persist []
```

Filtering a batch must not erase its classification. Otherwise, a generic
column name could pass the later tag stage while raw profile values reached
the agents. The empty list is an explicit denial; a missing sample list may
still use ordinary profile values. Original Parquet files remain unchanged,
and this sampling policy does not remove source data or stored profiles.
Detection is limited to the values sampled or retained by the profiler and
the selected scanner's patterns. Values outside that coverage can be missed;
this is not a guarantee that arbitrary source data contains no PII.

---

## 5. Re-redact on late tag flip

An operator can manually set `pii_tag` on a schema object via:

```
PUT /api/v1/schema-objects/{id}
{
  "pii_tag": "EMAIL",
  "pii_source": "HUMAN"
}
```

If the column already has `sample_values_json` persisted (because the
original scan missed it or the scanner was set to `warn`), flyquery
scrubs the samples in-place in the same transaction:

```python
if update.pii_tag and update.pii_tag != "NONE":
    schema_object.sample_values_json = None   # atomic with the tag update
```

This ensures that a retroactive PII classification immediately removes
the sample data without a separate step.

To trigger a full re-ingestion with the new policy (to update profile_json
as well), use:

```
POST /api/v1/ingest-jobs  {"job_kind": "REPARSE", "file_id": "<id>"}
```

---

## 6. PII in query results

The ExplainerAgent receives up to 50 rows of result preview. flyquery applies
`FLYQUERY_PII_POLICY_RESULTS` to the preview before returning it to the caller.

**Note:** The full result in object storage (Parquet at
`results/{query_id}.parquet`) is NOT post-processed for PII. If you need
PII-free results at rest, set `policy=redact` and rely on the preview only,
or apply your own column-level filtering before downloading the presigned
Parquet.

`pii_findings_json` on `flyquery_queries` records which columns in the result
triggered PII findings (scanner and entity type). This field is populated
regardless of policy (even `warn`).

---

## 7. Custom regex extension

Additional regex patterns can be supplied via a YAML file pointed to by
`FLYQUERY_PII_REGEX_PATTERNS_PATH`:

```yaml
# custom_pii_patterns.yaml
patterns:
  - name: EMPLOYEE_ID
    pattern: "EMP[0-9]{6}"
    column_name_hints: ["employee_id", "emp_id"]
  - name: INTERNAL_ACCOUNT
    pattern: "ACC[0-9]{10}"
    column_name_hints: ["account_number", "acct_no"]
```

Each pattern entry has:
- `name` — the `pii_tag` value set when matched.
- `pattern` — a Python `re`-compatible regex applied to sample values.
- `column_name_hints` (optional) — if the column name contains any of these
  strings, the pattern match threshold is lowered (flag on name alone, even
  without a sample match).

Custom patterns are merged with the built-in set. Duplicate `name` values
override the built-in.

---

## 8. PII tags on schema objects

`flyquery_schema_objects.pii_tag` holds the detected category:

| Value | Meaning |
|-------|---------|
| `NONE` | No PII detected |
| `EMAIL` | Email address |
| `PHONE` | Phone number |
| `SSN` | Social security / national ID number |
| `CREDIT_CARD` | Credit card number |
| `IP_ADDRESS` | IP address |
| `DOB` | Date of birth |
| `NAME` | Personal name (Presidio only) |
| `LOCATION` | Address / location (Presidio only) |
| `CUSTOM:<name>` | Matched a custom pattern (name from YAML) |

`flyquery_schema_objects.pii_source` records how the tag was set:
`REGEX`, `PRESIDIO`, `AGENT` (v1+ GovernanceClassifierAgent), or `HUMAN`.

HUMAN-set tags take precedence and are preserved across re-uploads
(annotation transplant in stage 3).

---

## 9. Configuration reference

| Variable | Default | Effect |
|----------|---------|--------|
| `FLYQUERY_PII_SCANNER` | `regex` | Scanner: `regex` \| `presidio` \| `disabled` |
| `FLYQUERY_PII_POLICY_SAMPLES` | `redact` | Policy for sample values: `warn` \| `redact` \| `reject` |
| `FLYQUERY_PII_POLICY_RESULTS` | `warn` | Policy for query result rows |
| `FLYQUERY_PII_REGEX_PATTERNS_PATH` | (unset) | Path to custom regex YAML |
| `FLYQUERY_PRESIDIO_SPACY_MODEL` | `en_core_web_sm` | spaCy model for Presidio |
| `FLYQUERY_SAMPLE_N` | `8` | Number of sample values read per column |

See also [security-model.md § 7](security-model.md#7-pii-scanning-and-sample-protection)
for the security angle.
