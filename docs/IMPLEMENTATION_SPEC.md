# Implementation Specification

Technical contract for the take-home work. Implementation milestones 1-8 are completed and accepted. Later remediation status is tracked in `REMEDIATION_PLAN.md`.

Authority: `ASSIGNMENT.md` defines employer requirements; this document resolves implementation choices; `../PLAN.md` defines order and budget. Dataset evidence comes from `DATASET_ANALYSIS.md`, checked against the current code where relevant. Choices below are project assumptions unless explicitly attributed to the assignment.

## 1. Historical Milestone 1 Architecture Snapshot

This section records the foundation as it existed at Milestone 1. Later sections and the current code describe the completed business endpoints and dependencies.

Milestone 1 stack: Python >=3.11, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, Uvicorn, pytest, and HTTPX/TestClient. SQLAlchemy was explicitly requested for Milestone 1 and superseded the earlier PLAN choice of direct `sqlite3`. RapidFuzz was added in Milestone 3. No LLM is required: the assignment permits fuzzy matching and rules.

| Existing file | Responsibility |
| --- | --- |
| `app/main.py` | `create_app(database_url, seed_path)`, lifespan, `/`, `/health`, default paths and environment overrides. |
| `app/database.py` | Declarative Base, engine, session factory/generator, table creation. |
| `app/models.py` | One Lead table and four nonunique comparison indexes. |
| `app/normalization.py` | Shared text, status, country, contact-key, company-key, and seed-date functions. |
| `app/seed.py` | Load CSV into an empty leads table; commit the imported records together. |
| `app/schemas.py` | LeadBase/Create/Update/Read and HealthResponse. These are foundation schemas, not finished API validation. |
| `tests/test_foundation.py` | Health/import, repeat startup/basic normalization, and foundation-only OpenAPI checks. |
| `pyproject.toml`, `.gitignore` | Editable installation, runtime/test dependencies, generated-file exclusions. |

Keep this structure and synchronous SQLAlchemy sessions. Additional route or feature modules are acceptable when directly needed; no repository/service layer is required. File-backed SQLite is the supported local/test configuration. Do not change database technology or introduce migrations infrastructure for this assignment.

Startup creates tables and imports the seed automatically only when `leads` is empty. Default database is repository-root `leads.db`; default seed is `data/leads_seed.csv`. `DATABASE_URL` and `SEED_DATA_PATH`, or explicit factory arguments, override defaults. Existing nonempty databases are left untouched even if the seed file is unavailable. Engine disposal occurs on normal application shutdown.

At this historical milestone, `/` returned the service name, `/health` returned `{"status":"ok","lead_count":2049}` for the unmodified seed, and business endpoints had not yet been added. The completed application now includes the business endpoints specified in later sections.

### Milestone 1 Acceptance and Evidence

- [x] FastAPI starts with SQLAlchemy/SQLite and exposes a database-backed health response.
- [x] All 2,049 seed records load with unique original IDs and without deduplication.
- [x] Full-name fallback, phone keys, canonical status/owner, and mixed-date parsing work on the supplied seed; 553 modification dates remain null.
- [x] Restart does not reimport, increase count, or overwrite an existing edit.
- [x] Model, Pydantic schemas, isolated file-backed tests, and installable package exist.
- [x] Existing suite passes: 3 tests, rerun during this inspection. Two dependency deprecation warnings are non-blocking.

The edit-preservation and missing-seed-on-restart checks were additional temporary-database diagnostics, not existing committed tests. Current tests do not establish exhaustive validation or deduplication quality.

### Material Baseline Findings

No BLOCKER prevents accepting Milestone 1 or proceeding after review. Address these IMPORTANT items only when the owning milestone is authorized:

| Finding | Evidence and impact | Required disposition |
| --- | --- | --- |
| PATCH schemas are permissive | LeadUpdate accepts arbitrary status strings and explicit null status, and silently ignores unknown fields. Exposing it unchanged would violate PLAN's PATCH contract. | Milestone 2: forbid extra request fields, validate status, distinguish omitted from explicit null, and test rejected writes. |
| SQLite timestamps lose timezone metadata | A seed UTC datetime reloads with `tzinfo=None`; LeadRead currently emits a timestamp without an offset. Later aware/naive comparisons and clients could misinterpret time. | Milestone 2: treat stored naive values as UTC and serialize explicit UTC offsets. Milestone 4: convert submitted timestamps to UTC before persistence/comparison. Keep the existing DateTime columns. |
| Text helper collapses Notes formatting | `optional_text('First line.\n\nSecond  line.')` produces one line. No supplied seed Notes change under this helper, but future multiline messages would lose formatting. | Milestone 2 PATCH and Milestone 4 ingest: preserve internal whitespace/newlines in free text; trim only outer whitespace and map blank text to null. Use that policy in the loader when implementing the shared behavior; do not rewrite existing stored notes. |

Accepted deviations from PLAN: SQLAlchemy instead of direct sqlite3; automatic empty-table startup import instead of a separate import command; country title-casing plus a UAE special case instead of a lookup table. These fit the observed dataset and do not need refactoring. The PLAN's pre-implementation status sentence is historical, not a reason to redo Milestone 1.

Important integration dependency: existing databases have null extraction fields and do not reimport. Milestone 5 must populate missing derived source values without deleting/reseeding data. A small synchronous backfill is sufficient.

## 2. Canonical Lead Model

The existing table `leads` is authoritative. All lengths below are SQLAlchemy declarations; SQLite does not enforce String lengths or nonempty strings. Validate supported HTTP writes with Pydantic, not assumptions about database constraints.

| Persisted field | Storage and nullability |
| --- | --- |
| `id` | Non-null integer primary key, generated for new leads; imported IDs retained. |
| `name`, `company` | Non-null String(255). |
| `email`, `phone`, `country`, `status` | Non-null String(320), String(64), String(100), String(50), respectively. |
| `owner`, `notes` | Nullable String(255), nullable Text. |
| `created_at`, `updated_at` | Non-null / nullable DateTime, respectively; application semantics are UTC. |
| `original_source` | Nullable String(255), raw CRM source label. |
| `source_channel`, `source_detail` | Nullable String(50) / String(500); null until Milestone 5. |
| `email_key`, `phone_key`, `email_domain` | Non-null String(320), String(64), String(255). |
| `name_key`, `company_key` | Non-null String(255). |
| `form_metadata` | Nullable JSON database column, mapped as Python attribute `Lead.form_data`. |

Only the primary key is unique. Indexes exist on email_key, phone_key, email_domain, and company_key. Shared contact identifiers must remain legal. There are no database status/channel enums or check constraints; enforce canonical values at application boundaries.

The public Lead representation is the existing LeadRead field set: id, name, company, email, phone, country, status, owner, notes, created_at, updated_at, original_source, source_channel, source_detail, form_metadata. Keep comparison keys internal. Preserve the ORM `form_data` to public `form_metadata` alias and ensure JSON uses the public name. Source values remain null until extraction is integrated.

Original seed files remain unchanged and preserve omitted first/last components and CRM columns. Do not add operational fields for entirely blank columns, Job Title, Lifecycle Stage, or Lead Score. Lead Score is not duplicate confidence.

## 3. Import and Normalization Contract

| Input | Stored/display value | Comparison or validation |
| --- | --- | --- |
| Name | Prefer nonblank Full Name; otherwise join first/last. Trim/collapse name whitespace. Preserve initials, punctuation, and multiword names. | Existing casefolded, whitespace-collapsed name_key. Never invent an expanded initial or require splitting into first/last. |
| Email | Trim surrounding whitespace, preserve address punctuation/case in display. | Casefold key; domain is the text after the final `@`. Do not erase local-part dots or plus tags. Reject internal whitespace/malformed incoming address shape. No DNS/deliverability checks. |
| Phone | Preserve readable formatting and country prefix. | Digits-only key including country code; no last-N-digit equality. Do not infer a country prefix for an unfamiliar local number. |
| Company | Preserve wording and punctuation, trim/collapse whitespace. | Existing company_key casefolds, expands `&` to `and`, replaces non-ASCII-alphanumeric punctuation with spaces, then collapses spaces. Legal-suffix punctuation becomes comparable; no broad removal of business words. |
| Status | Canonical seven values from `STATUSES`. | Trim/casefold and map; unknown or explicit null status is invalid in writes. |
| Owner | Trim/collapse whitespace; blank becomes null. | Case-insensitive exact filtering. No user directory or owner entity. |
| Country | Existing title-case normalization, except `UAE`. | Case-insensitive exact filtering; 62 seed spellings reduce to 35 countries. |
| Notes/message | Preserve Unicode and internal formatting; outer trim only; blank becomes null. | Extraction may use a normalized copy; never destructively remove source or sales text from storage. |
| Original Source | Preserve source wording after outer/ordinary whitespace cleanup; blank becomes null. | Context only, never a person identifier or authoritative channel. |
| Dates | Parse seed ISO date, ISO UTC timestamp, or US month/day/year. Date-only values mean UTC midnight by convention. | Invalid nonempty dates fail import. Missing creation date fails; missing modification date stays null. API dates use explicit UTC offset; incoming aware timestamps convert to UTC. |

The seed supplies nonblank name/company/email/phone/country/status. Keep the existing non-null operational columns; do not add nullability changes just to support hypothetical incomplete forms. Optional values remain null. Defensive matching helpers must never treat two blank values as agreement, even when testing partial comparison records.

The current ASCII-oriented company key is accepted for this dataset; preserve Unicode display values and document broader multilingual matching as a limitation. Do not use normalized company equality as proof of person identity.

Import is all-or-nothing for a fresh database, retains input IDs, and fails startup on unreadable/malformed required seed data. Invalid rows must not be silently skipped. SQLAlchemy caller/session closure must roll back a failed insert transaction. A nonempty database is not repaired/reconciled against the seed, and a missing seed is irrelevant on that path. No concurrent multi-worker import guarantees are required.

## 4. HTTP Contracts (Milestone 2 Unless Stated)

Use FastAPI's standard `detail` error envelope. Malformed inputs return 422; a valid positive ID with no record returns 404. Request bodies reject unknown fields. Each write commits atomically, returns the persisted LeadRead, and leaves no mutation when validation or matching fails. Do not expose tracebacks as client explanations.

### List, Detail, and Export

`GET /leads`: optional status, owner, country, q; limit defaults to 50, range 1-200; offset defaults to 0 and must be nonnegative. Empty filter strings are absent. Nonempty invalid status is 422; unknown owner/country simply matches zero rows. AND the filters, then apply case-insensitive literal substring q across name OR company OR email. `%` and `_` in q are literal characters, not caller-controlled SQL wildcards. Use bound SQLAlchemy expressions.

Return `{"items":[LeadRead],"total":N,"limit":50,"offset":0}` with ascending ID order. Total is the count before pagination. An empty result returns an empty array and zero total; an offset beyond the result still returns the full filtered total.

`GET /leads/{id}`: positive integer ID; return LeadRead or 404.

`GET /leads/export`: same filters/q, same ordering, every matching record, independent of list pagination. Return UTF-8 `text/csv` with attachment filename `leads.csv`. Header order: id,name,company,email,phone,country,status,owner,notes,created_at,updated_at,original_source,source_channel,source_detail. Exclude internal keys and JSON metadata. Nulls are empty CSV cells; dates use the same UTC representation as JSON. Use the standard CSV writer for commas, quotes, and newlines. Empty results still return the header. Register static paths before the dynamic ID route.

### PATCH

`PATCH /leads/{id}` accepts only status, owner, notes. Omitted fields remain unchanged. Reject `{}`, unknown fields, unknown/blank/null status with 422. Normalize a provided status; owner can be cleared with null/blank. Notes can be cleared with null/blank and otherwise replace the whole note text, preserving internal formatting. Reject overlong owner/status input. No identity/contact updates through this endpoint.

Return updated LeadRead (200). Set updated_at to current UTC on a real change; no-op updates need not advance it. During Milestone 2, extraction is absent: a Notes change clears derived source fields to null rather than leaving stale values. Milestone 5 replaces that invalidation with source recomputation in the same transaction.

### Ingest Schema in Milestone 2; Behavior in Milestone 4

Define a separate WebsiteSubmission schema matching one JSON entry. Required nonblank strings: name, company, email, phone, country, form_id, form_name, page_url. Require submitted_at as a timezone-aware ISO datetime; message is an optional string/null. Use existing lead length limits, 255 characters each for form_id/form_name, and 2,048 for page_url. Reject unknown keys, malformed email shape, and phone text with no digits. Accept relative page paths and absolute HTTP(S) URLs; do not make network calls or force page_url to agree with form metadata. No batch payload, client status/owner/ID, source fields, or arbitrary metadata dictionary is accepted.

Milestone 2 adds and tests the schema only; do not register a placeholder ingest endpoint. Milestone 4 adds `POST /leads/ingest` and returns `{"action":"created"|"updated","lead":LeadRead}` with 201/200 respectively. Conflicts return 409 with `detail: {"code":"ambiguous_match"|"conflicting_identity","message":string,"candidates":[...]}`; candidates contain IDs, score/band, and reasons. An unchanged replay returns action updated, 200.

### Matching, Extraction, and Optional Dashboard

Milestone 3: `POST /leads/dedupe-candidates` accepts no body or an optional object with min_score (default 0.75, range 0.75-1.0) and limit (default 100, range 1-500). Return `{"candidates":[{"lead_ids":[id1,id2],"score":number,"confidence":"clear"|"likely","reasons":[string]}],"candidate_pairs_evaluated":N,"total_matches":M}`. Total matches is after min_score but before result limit. Sort by descending score, then ascending IDs. id1 < id2. This endpoint is read-only; a pair counts as an allowed two-member group.

Milestone 5: `POST /leads/extract-source` accepts `{"text":string}` and returns `{"channel":enum,"detail":string}`. Empty/whitespace text is allowed; omitted/non-string/null text is 422. This endpoint is stateless. Shared extraction logic is also called internally with optional form context.

Milestone 8 only: `GET /dashboard` returns `{"total":N,"by_status":{...},"by_source_channel":{...}}` for all stored records. Include canonical categories with zero counts; sums equal N after Milestone 5 backfill. No filters/charts needed. Count records, not estimated unique people.

## 5. Deduplication Contract (Milestone 3)

### Candidate Generation

Build maps of nonempty email_key, phone_key, email_domain, and company_key to lead IDs. Generate combinations only inside shared-key blocks, union them as `(min_id,max_id)` pairs, and remove self-pairs. Do not compare all records against all others, materialize a full distance matrix, or call an LLM per pair. Ingest looks up blocks for one submission using the same keys and scoring.

Verified on the current seed and normalization: 58 email pairs, 294 phone pairs, 3,899 domain pairs, 1,385 company pairs; union 5,047 versus 2,098,176 possible pairs. Largest blocks are 2, 3, 13, and 7 respectively. Dictionary/index lookup plus scoring the union is tractable here. Pair count is a diagnostic, not accuracy. Do not hardcode the dataset size or these counts in the matcher.

No arbitrary pair truncation before scoring. Broad/common domains are weak evidence, not automatic matches. If future inputs create materially larger blocks, report that limitation; do not solve production scale now. An additional name-based block or changed key normalization affects recall and this contract, so propose evidence and obtain approval before introducing it.

### Scoring and Classification

Use RapidFuzz similarity divided by 100 and explicit evidence tiers instead of a trained model. The following initial thresholds are project decisions, not empirically calibrated probabilities:

- E/P: equality of nonempty email/phone keys. D: equality of nonempty domain. C: `fuzz.ratio` on nonempty company keys; otherwise 0.
- N: maximum of `fuzz.ratio` and `fuzz.token_sort_ratio` on nonempty name keys. For names with the same token count, equal tokens or matching initial/full tokens at each position, allow initial compatibility N=0.90 if at least one non-initial token agrees. Token punctuation can be ignored for this check only. Never expand stored names.
- Guard against a shared surname dominating N: when both first name tokens are fully spelled, differ, and their ratio is below 0.80, treat this as incompatible given-name evidence. A missing name is not compatible evidence. This is a bounded heuristic for this dataset, not a universal name parser.
- L: ratio of the email local parts when both exist; otherwise 0. Country agreement is explanatory context only; it cannot rescue a failed identity test.

Apply the first qualifying rule, with the incompatible-name guard taking precedence:

| Evidence | Score / classification |
| --- | --- |
| Incompatible fully spelled given names | At most 0.69, insufficient evidence; keep exact-key conflicts visible to ingest separately. |
| E and P and N >= 0.80 | 0.99, clear duplicate candidate. |
| P and N >= 0.90 and (D or C >= 0.80) | 0.97, clear; handles changed email local parts. |
| E and N >= 0.90 | 0.95, clear; differing phone is explained, not assumed equivalent. |
| E or P, and N >= 0.80 | 0.85, likely; enough to surface, not enough for automatic update. |
| E and P but missing name | 0.85, likely; insufficient name evidence for automatic update. |
| No exact identifier, but N >= 0.90, C >= 0.80, D, and L >= 0.80 | `0.75 + 0.14 * (0.60*N + 0.25*C + 0.15*L)`, likely, below 0.90. |
| Everything else | 0, insufficient evidence/non-match; do not surface. |

Clear band is >=0.95; likely band is 0.75 to <0.95. Score rounding is for output only; compare unrounded values to thresholds. Missing signals contribute no agreement, and two absent contacts must never qualify E/P/D. Different populated contacts cannot be treated as exact matches merely because they look similar. No exact identifier means no automatic ingest update regardless of score.

These conservative rules can miss real duplicates with changed domain/company/phone or radically different names. Confirm representative positive and negative examples before accepting Milestone 3. If they fail materially, propose the smallest scoring change for review; do not silently tune the contract or claim dataset-wide precision/recall.

### Explanations and False-Positive Protection

Each surfaced pair includes useful reasons: matching normalized phone/email, numeric name/company similarity where used, initial compatibility, and populated conflicting fields. Domain/company alone, shared owner/status, nearby IDs, identical templated Notes, or a `possible duplicate` marker are never proof of identity. Do not use Lead Score as confidence. Preserve conflicting evidence even for high-scoring pairs. No seed updates, auto-merges, or transitive identity groups.

## 6. Ingest Contract (Milestone 4)

Normalize once, generate candidates, and score them using Milestone 3. Also collect every exact email/phone hit independently of the surfaced-score threshold. Matching decides before any mutation:

1. If supplied email and phone each have existing hits but their ID sets are disjoint, return conflicting_identity (409), even when a score would favor one side.
2. If either exact identifier resolves to multiple records, return ambiguous_match (409). A matching seed duplicate group is not permission to pick its first record, even if another identifier would narrow it.
3. With no such conflict, update only when exactly one candidate is clear and no other candidate is likely/clear. Exact-key evidence with incompatible/insufficient names, multiple plausible candidates, or fuzzy-only likely matches returns 409 with reasons.
4. When there are no plausible candidates and no unresolved exact-key hits, create. Weak company/domain matches that score as insufficient do not prevent creation.

No supported match is different from an exact-identifier contradiction; the latter must not accidentally fall through to create. Never fan out a submission update across duplicate records. Conflict handling is in the API response; no conflict-management UI or resolution endpoint is required.

| Field | New lead | Existing supported lead |
| --- | --- | --- |
| id | Database-generated | Preserve. |
| name/company/email/phone/country | Validated display values and canonical country | Fill only blank/missing values; never replace established data automatically. Recompute affected comparison keys when filling. |
| status/owner | New / null | Preserve. |
| notes | Outer-trimmed message or null | Preserve existing text; append distinct message separated by a blank line. Null/blank message never clears it. |
| created_at | Submitted timestamp normalized to UTC | Preserve. |
| updated_at | Null until a subsequent change | Current UTC when stored content changes; preserve on a no-op replay. |
| original_source | Null (no CRM source supplied) | Preserve. |
| source fields | Null until Milestone 5 | Preserve until Milestone 5 integration. |
| form_metadata | form_id, form_name, page_url, submitted_at | Retain metadata for the latest submission by submitted_at. Older/equal submissions do not overwrite established metadata. |

For duplicate-message checks, compare outer-trimmed text after normalizing line endings, preserving stored internal formatting. Do not append if the message equals all Notes or an existing complete blank-line-delimited block; check multiline blocks with complete boundaries, not arbitrary substring membership. Exact replays must not create a second lead, append the same message, or change timestamps. Different messages can be retained even for older submissions; metadata chronology is handled separately.

This is best-effort lead/message replay handling, not an exactly-once delivery guarantee. No submission ledger, cache, queue, or idempotency service. Do not repair mismatched form_id/form_name/page_url or infer a unique submission from form_id.

## 7. Source Extraction Contract (Milestone 5)

Allowed channel enum, exactly as assigned: Website, Event, LinkedIn, Organic Search, Referral, Manual/Sales, Other. Output detail is a concise evidence-based string, at most 500 characters. Unknown input returns `{"channel":"Other","detail":"Source unspecified"}`. Never fabricate a platform, event year, person, or QR scan.

Implement rules only, with ordered case-insensitive patterns and extracted text spans. No LLM calls, model credentials, embeddings, or mock-model claims. Preserve raw Notes; normalization and operational-suffix removal apply only to the extraction copy.

| Evidence | Channel/detail behavior |
| --- | --- |
| Event booth encounter | Event; capture event name and stated interaction. Affirmative scanned QR -> Booth QR Code; no QR scan logged -> Booth conversation; no QR scan logged. Generic booth contact alone does not imply QR. |
| Explicit referral | Referral; capture referrer's name from the referral clause, excluding sales updates. |
| Explicit LinkedIn or Linkedin DM/post | LinkedIn; retain DM or post interaction detail. |
| Organic Google search / Googled us | Organic Search; retain search provider and stated landing page. |
| Google ad followed by demo booking | Other; detail preserves paid Google advertising and demo destination. Evaluate paid-ad evidence before generic Google/website rules. |
| Website form only | Website; preserve named page/form context. |
| Manual entry / sales phone call | Manual/Sales; distinguish inbound phone call from cold outreach. |
| Social post with unspecified platform | Other; Social post interaction; platform unspecified. |
| Walk-in / general email inbox | Other; retain the contact method. |

Recognize event names from the text, including the ten observed names. SFF may expand to Singapore FinTech Festival as a documented alias; add a year only if explicitly present. Ignore sales-status suffixes and possible-duplicate warnings for detail. For a search-to-website or event-to-form journey, retain the acquisition evidence rather than the final form transport. If two genuinely different acquisition channels remain and the text specifies no ordering, return Other with a concise ambiguous-source detail. Do not choose a fixed precedence that silently rewrites chronology.

Integration rules:

- Fresh import derives source from each record's Notes. Existing databases receive a one-time-on-demand startup pass over only rows with null source fields, in a transaction. Reuse the extractor; preserve IDs, Notes, owner/status, timestamps, and any populated attribution. Subsequent startups skip complete source fields. Do not reseed or reset the database.
- New ingest: explicit message evidence wins; with no acquisition evidence, Website is a documented fallback from the known form transport, with page/form context retained. Unspecified social/paid/conflicting evidence is still evidence and stays Other, not Website.
- Existing ingest: preserve established explicit attribution. Fill missing or `Source unspecified` attribution from new evidence; a generic follow-up never overwrites it. A known Website fallback may be refined by later explicit acquisition evidence if the earlier Notes provided none. Use existing Notes/form metadata to distinguish that case; no new attribution-history layer.
- PATCH replacing Notes deliberately replaces the evidence: recompute immediately in the same transaction from the new Notes. Clearing Notes yields Other / Source unspecified; do not resurrect the old source through form context.

Source results are heuristic extraction from the supplied text, not externally verified marketing attribution. Preserve raw Original Source for context but do not use its generic labels to invent details absent from Notes.

## 8. Testing and Milestone Acceptance

Add meaningful tests with each behavior, using temporary file-backed SQLite databases and the existing application factory. No tests mutate the developer's `leads.db` or supplied data. Update the foundation-only OpenAPI assertion as routes are intentionally introduced; retaining a health-only assertion is not a future acceptance criterion.

Representative matching review fixtures: 100234834/100234835 (Joon/J. Diallo); 100234846/100234847 (Isabelle Kapoor local-part change); 100234854/100234855 (Ahmed Schulz phone formatting). Plausible negatives: 100236413/100236414 (Ravi/Rin Agyemang) and 100236225/100236226 (Ama/Farah Bianchi). These are reasoned fixtures, not provided ground truth. Add a small synthetic typo pair and conflicting-identifier case rather than a full annotation exercise.

Use the 90 form examples to validate schema compatibility. Forty-nine have exact seed email/phone overlap and nine submissions hit multiple records; do not assume all must update successfully. Exact overlap is not a labeled evaluation of the remaining 41.

### Milestone 2: List/Detail/PATCH/Export and Ingest Schema (1.50h) - COMPLETED

Done when:

- [x] List/detail/PATCH/export match Section 4, including UTC serialization, stable pagination, and unpaginated export.
- [x] PATCH rejects unsupported fields, null/invalid status, and empty payload; validation failures do not change the row. Notes formatting, clearing, and source invalidation work.
- [x] WebsiteSubmission validates all supplied examples and rejects representative malformed inputs; no ingest route yet.
- [x] Tests cover combined filters/search, literal wildcard characters, no results/missing ID, pagination/export parity, CSV comma/quote/newline round-trip, and timestamp round-trip policy. Existing foundation checks still pass.
- [x] README begins with working setup/run/test commands and the currently available routes.

### Milestone 3: Candidate Generation and Fuzzy Scoring (1.50h) - COMPLETED

Done when:

- [x] RapidFuzz and shared candidate/scoring functions implement Section 5; endpoint output is ranked and explained, with comparison count.
- [x] Tests confirm 5,047 candidate pairs for the unchanged seed/current keys; no self/repeated pairs; empty identifiers create no shared block; every scored pair belongs to generated candidates.
- [x] Reviewed formatting/typo/initial positives and similar-looking negatives exercise threshold guards. Score is never represented as calibrated accuracy.
- [x] Threshold boundaries, missing evidence, deterministic ordering/limit, and absence of database mutation are checked. Document matching decisions and known recall limits.

### Milestone 4: Ingest Create/Update/Conflict Behavior (0.75h) - COMPLETED

Done when:

- [x] Section 6 decision order and field policy are implemented in a single transaction per successful write.
- [x] Tests cover new lead, unambiguous existing identity, fuzzy-only likely match, multiple exact hits, cross-record email/phone conflict, and incompatible names with an exact identifier.
- [x] Replay preserves count/notes/timestamps; a distinct multiline message appends intact; status/owner/contact preservation and submission-time metadata ordering are verified.
- [x] Responses and status codes are documented; extraction remains pending until Milestone 5.

### Milestone 5: Source Extraction and API/Import/Update Integration (1.00h) - COMPLETED

Done when:

- [x] Extractor and stateless endpoint return only the seven channels with grounded detail and explicit unknown handling.
- [x] Tests cover QR affirmation/negation, referral, LinkedIn, paid/organic Google, unnamed social platform, unknown/conflicting text, and year preservation.
- [x] Fresh import and existing-database null-source backfill work without reseeding or overwriting edits; repeated startup is stable.
- [x] Ingest defaults, generic-follow-up preservation, PATCH replacement/clearing, and immediate persisted source consistency are verified. README explains rules and taxonomy choices.

### Milestone 6: Integration Tests and Fixes (0.75h) - COMPLETED

Done when:

- [x] Run the complete suite; fix relevant failures rather than marking them as expected merely to pass.
- [x] Verify the integrated sequence: import -> filter/export -> PATCH -> ingest/replay/conflict -> dedupe -> extraction, including unchanged state after conflicts.
- [x] Test fresh-start failure/rollback with a small malformed seed and persistence across restart after a real edit. Check normalized status totals and null-date behavior against the analysis.
- [x] Keep fixes within observed correctness/integration issues; no unrelated restructuring or test-count target.

### Milestone 7: README and Fresh-Start Demo Verification (0.50h) - COMPLETED

Done when:

- [x] Verify a fresh virtual environment installation from repository metadata and a fresh temporary database; do not delete the user's local database or edits.
- [x] Run documented commands, the complete suite, and a real local server smoke test for implemented endpoints; check restart preservation and import count.
- [x] README covers setup, environment overrides, example requests, import/date policy, matching/extraction reasoning, conflict behavior, limitations, and next steps.
- [x] Describe fuzzy/rules implementation truthfully; no LLM is used or billed. If an approved later change uses an LLM, document provider/model/cost.
- [x] Run/dependency commands are repeatable, submission contains source/tests/data/docs but excludes environments/databases/caches, and future-production ideas are clearly separate from current behavior.

### Milestone 8: Optional Dashboard or Contingency (0.50h) - COMPLETED

Done when:

- [x] User authorized this optional milestone after all core work was stable.
- [x] Dashboard JSON counts satisfy Section 4 and reconcile after PATCH and ingest writes; a focused test passes. No frontend was added.
- [x] Dashboard implementation was selected rather than contingency-only work.

Milestone 1 allocation was 0.75h; the PLAN total remains 7.25h. Allocations are estimates, not a claim of elapsed time. Keep a handful of parameterized tests where useful; no comprehensive production test program.

## 9. Non-Goals and Review Decisions

Exclude authentication, RBAC, Redis, Celery, queues/workers, event buses, production deployment/scaling/monitoring infrastructure, website analytics, extra webhook infrastructure, complex audit/history systems, HubSpot migration tooling, unnecessary repository/service abstractions, unrelated refactors, seed auto-merge, external identity enrichment, and speculative UI. Frontend work requires explicit authorization and demonstrable spare time after stable core work.

Assumptions deserving review before their milestones:

- Conservative matching scores/thresholds and the policy of conflicting on multiple exact-key records are not employer-specified. They protect existing data but can require human review for legitimate duplicate seed identities. No conflict-resolution feature is included.
- Paid advertising maps to Other, unspecified social platforms stay Other, and original discovery is preferred to later form transport. These resolve gaps in the employer taxonomy; different business attribution semantics would require approval.
- All eight non-message form strings are required, reflecting the examples and existing non-null model. Supporting forms missing contact/name/company/country would require an explicitly approved schema policy.
- Empty-table automatic import and file-backed SQLite are accepted baseline choices. Source backfill in Milestone 5 enriches only derived fields; it does not reopen import/reconciliation scope.
- Existing naive database datetimes mean UTC. Do not guess local timezones for historical records.

No unresolved employer-scope blocker was found. If implementation evidence requires changing a behavioral rule, threshold, or architecture above, stop, explain the impact, and propose the smallest change for approval. Minor implementation details remain the implementer's choice.
