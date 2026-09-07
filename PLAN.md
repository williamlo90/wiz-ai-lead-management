# Implementation Plan

Target: a working local backend in 6-8 focused hours. Planning only; implementation has not started.

## Goals

- Import all 2,049 seed records without silently merging or losing data.
- Deliver the required lead API, explainable duplicate suggestions, and structured source extraction.
- Demonstrate sensible handling of ambiguous inputs through focused tests and a runnable README.

## Scope

CSV import, persistent lead storage, filtering/search, detail/update, filtered CSV export, single-submission ingest, duplicate candidates, and source extraction. Use generated API documentation and example requests as the demo interface. Add dashboard counts only after the core works.

## Explicit Non-Goals

No polished frontend, authentication/roles, HubSpot migration tooling, analytics integrations, webhook infrastructure, audit-history UI, automatic seed merging, deployment, monitoring, queues, vector database, or production scaling work. No paid LLM dependency or generic application framework beyond the selected web framework.

## Proposed Stack

- Python, FastAPI/Pydantic, and Uvicorn for HTTP and validation.
- SQLite through standard-library `sqlite3`; standard-library `csv` and `json` for import/export.
- RapidFuzz for candidate similarity; deterministic rules/regex for source extraction.
- pytest and HTTPX/FastAPI TestClient for focused unit and API tests.

Keep modules focused on API/schemas, storage/import, normalization, deduplication, and source extraction. Use ordinary functions and one database table.

## Data Model

One `leads` table:

| Fields | Purpose |
| --- | --- |
| `id` | Integer primary key; retain seed Record IDs and generate fresh IDs for ingested leads. |
| `name`, `company`, `email`, `phone` | Display/contact values; preserve useful original formatting. |
| `country`, `status`, `owner`, `notes` | Canonical filter/update fields; owner may be null. |
| `created_at`, `updated_at` | Normalized timestamps; unknown seed modification time remains null. |
| `original_source`, `source_channel`, `source_detail` | Raw CRM attribution alongside extracted attribution. |
| `email_key`, `phone_key`, `email_domain`, `name_key`, `company_key` | Comparison values; index email, phone, domain, and company keys. |
| `form_metadata` | Nullable JSON containing the latest accepted form ID/name/page/submission time. |

Email and phone are not unique constraints: duplicate seed records must coexist. Derive display name from Full Name or joined first/last names. Keep the supplied CSV unchanged; omit blank columns, Job Title, Lifecycle Stage, and Lead Score from the operational model. Import explicitly into an empty store in one transaction; restarts must not reimport or overwrite edits.

## Normalization Decisions

- Trim text; map status to `New`, `Contacted`, `Connected`, `Qualified`, `Opportunity`, `Closed Won`, or `Closed Lost`. Trim owners and canonicalize the 35 observed countries, preserving `UAE`.
- Preserve name display text, including initials and multiword given names. Lowercase/collapse whitespace for comparison; never invent expanded initials or force first/last splitting.
- Lowercase/trim email keys. Preserve local-part dots and plus tags. Keep phone display text and a digits-only key including country code; never match empty keys or phone suffixes alone.
- Normalize company case, whitespace, punctuation, and `&`/`and`. Keep descriptive words; limited trailing legal-suffix normalization can supplement matching if needed.
- Parse ISO dates, ISO UTC timestamps, and month/day/year slash dates explicitly. Represent date-only inputs at UTC midnight as a documented storage convention, not observed time-of-day.
- Preserve UTF-8 Notes. Treat blank optional fields as missing. Ignore operational Notes suffixes for extraction, but retain them in stored Notes.

## API Endpoints

| Endpoint | Behavior |
| --- | --- |
| `GET /leads` | AND-combined `status`, `owner`, `country` filters; case-insensitive `q` across name/company/email; stable ID order, bounded limit/offset, total count. |
| `GET /leads/export` | Same filtering/search logic; export every matching row, independent of pagination, using a documented normalized CSV schema. |
| `GET /leads/{id}` | Single lead or `404`. Register static routes before this route. |
| `PATCH /leads/{id}` | Update only status, owner, or notes; reject unsupported fields/invalid status. Allow clearing owner/notes and recompute source when Notes are replaced. |
| `POST /leads/ingest` | Accept one JSON example-shaped object; return `201` for creation, `200` for update, or `409` with candidate IDs for ambiguous identity. |
| `POST /leads/dedupe-candidates` | Return ranked pairs, heuristic scores, reasons, and candidate-comparison count. |
| `POST /leads/extract-source` | Accept raw text and return `{channel, detail}`. |
| `GET /dashboard` (bonus) | Counts of stored records by status and extracted channel, including unresolved duplicates. |

## Deduplication Design

1. Generate the union of pairs sharing nonempty normalized email, phone digits, email domain, or company key. Deduplicate unordered pairs before scoring. Add exact-name blocking only if reviewed examples expose a useful gap.
2. Score only candidates with RapidFuzz name/company similarity plus exact identifier agreement and initial-name compatibility. Strong conflicting contact/name evidence lowers confidence; company/domain alone is insufficient.
3. Return sorted pairs with a 0-1 heuristic score, confidence band, and concrete reasons. Choose thresholds from a small reviewed positive/negative set; scores are not calibrated probabilities. Do not perform transitive auto-merging.

The inspected four-block union produced 5,047 pairs versus 2,098,176 possible pairs. This is workload reduction, not demonstrated recall. Same-phone matching finds 294 pairs versus 58 same-email pairs; exact email alone is insufficient. Do not use adjacent IDs, templated Notes, or `possible duplicate` warnings as identity labels.

Ingest reuses the same matcher. Update only an unambiguous match supported by an exact identifier and compatible identity evidence; fuzzy-only plausible matches or conflicting/multiple strong matches return `409`. Create when no plausible candidate remains. Preserve existing status/owner and populated contact fields, fill missing values, and append distinct nonempty messages without repeating identical submissions. New leads default to `New` and null owner. `form_id` identifies a form, not a submission, so it is not an idempotency key.

## Source Extraction Design

Use ordered case-insensitive patterns that extract evidence spans for the seven required channels: Website, Event, LinkedIn, Organic Search, Referral, Manual/Sales, Other.

- Capture event name and interaction; distinguish an affirmative QR scan from `no QR scan logged`. Preserve only stated years.
- Capture referral names, website pages, LinkedIn DM/post context, Google organic-search journeys, and inbound/cold-outreach calls.
- Map Google ads to `Other` with paid-search detail because Paid Search is absent from the taxonomy. Never classify advertising as organic.
- Map social posts without a named platform to `Other`; do not assume LinkedIn. Exclude sales-progress and duplicate-warning suffixes from detail.
- Prefer explicit Notes evidence over generic Original Source. Text without source evidence returns `Other` with an unspecified-source detail.
- For new form leads with generic messages, use Website as a contextual fallback and preserve form metadata. For existing leads, generic follow-ups retain established acquisition source; explicit Notes replacement triggers recomputation.

## Testing Strategy

- Import reconciliation: 2,049 records, unique IDs, seven normalized statuses, mixed dates, full-name-only records, null modification dates, and persistence across restart.
- API behavior: combined filters/search, export parity across all pages, CSV quoting round-trip, valid/invalid PATCH, missing IDs, and static-route handling.
- Matching: phone formatting, changed email local parts, initials, similar-name/company negatives, empty keys, unique candidate pairs, and scoring only generated candidates.
- Ingest: create, update, conflicting/multiple matches, unchanged status/owner, repeated submission, and distinct message append.
- Extraction: event/QR negation, referral detail, paid versus organic search, unspecified social platform, unknown text, Notes replacement, and generic follow-up preservation.

Use representative real records plus a few small synthetic edge cases. Report reviewed examples and candidate counts; do not claim dataset-wide accuracy without labels. No coverage-percentage target or large benchmark project.

## Implementation Order and Time

| Order | Work | Hours |
| --- | --- | ---: |
| 1 | Setup, model, import, normalization | 0.75 |
| 2 | List/detail/PATCH/export and ingest schema | 1.50 |
| 3 | Candidate generation and fuzzy scoring | 1.50 |
| 4 | Ingest create/update/conflict behavior | 0.75 |
| 5 | Source extraction and API/import/update integration | 1.00 |
| 6 | Integration tests and fixes | 0.75 |
| 7 | README and fresh-start demo verification | 0.50 |
| 8 | Optional dashboard or contingency | 0.50 |
| | **Total** | **7.25** |

Write focused tests and README decisions alongside implementation. At a six-hour limit, omit the dashboard and extra scoring refinements; prioritize a working end-to-end core.

## Assumptions and Tradeoffs

- Fuzzy matching and rules satisfy the assignment's explicitly permitted approaches. Favor explainability and repeatability over model/API setup.
- Precision takes priority over automatic ingest updates; `409` exposes uncertainty instead of selecting an arbitrary existing record. Seed duplicates remain separate records.
- Acquisition source means original discovery where evidence exists, not simply the website transport of a later submission. No multi-touch attribution model is needed.
- Preserve inconsistent form ID/name/page values; no reliable correction mapping is supplied. Repeated-form protection covers lead/message duplication, not general webhook delivery guarantees.
- SQLite and simple synchronous local operations fit this take-home. Full provenance/history, richer field reconciliation, and broader duplicate-recall evaluation belong in the README's next-steps section.
