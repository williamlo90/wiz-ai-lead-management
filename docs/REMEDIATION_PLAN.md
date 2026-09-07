# Remediation Plan

## Review Summary

Reviewed baseline: `c4f11d6` (`feat: add lead dashboard counts`).

The submission is broadly on track for a Mid-Level AI Builder take-home. All required API surfaces and the optional dashboard exist. The storage model, synchronous SQLAlchemy sessions, four-key candidate blocking, shared scoring, and conservative ingest conflicts are appropriate for the assignment. No architecture rewrite is justified.

Counts: **0 BLOCKER, 4 IMPORTANT, 2 NICE-TO-HAVE**. Fix the three demonstrated source-attribution defects and close the specific matching-test gaps before submission. The passing suite is useful evidence for the supplied examples, but does not establish that all free-text source contracts are satisfied.

Review evidence:

- Read the assignment, implementation specification, plan, operating instructions, dataset analysis, README, all application modules, and all seven test modules.
- Ran `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider`: **51 passed**, two third-party deprecation warnings.
- Ran `.venv/Scripts/python.exe -m pip check`: no broken requirements.
- Exercised all 90 supplied submissions through TestClient against a temporary, freshly seeded SQLite database: 40 updates, 41 creations, 9 conflicts. A second pass returned 81 updates and the same 9 conflicts; count remained 2,090 and CSV export bytes were unchanged. These are observed behaviors, not ground-truth identity labels.
- Reproduced the source and PATCH defects below using direct extraction calls and HTTP requests against temporary SQLite. No development database or supplied data was changed.
- Reviewed setup commands and tracked files. Previous Milestone 7 verification established fresh installation and real-server restart behavior; this review did not repeat that installation. Current tests exercised fresh database creation and restart.
- Application code and tests remain unchanged during this review. Only this plan and the small remediation-workflow addition to AGENTS.md are review deliverables.

### Areas That Are Good Enough

| Area | Assessment and disposition |
| --- | --- |
| Assignment coverage | Required endpoints, CSV import/export, fuzzy deduplication, rules extraction, and bonus counts are present. Keep the chosen scope. |
| Storage and normalization | Original IDs, nonunique contacts, display/comparison separation, canonical statuses, explicit seed date formats, UTC API dates, and nullable modification dates fit the data. Keep SQLAlchemy/SQLite and the existing schema. |
| API and errors | Bound queries, shared filtering for export/list, literal wildcard escaping, bounded pagination, request validation, 404/409/422 envelopes, and session rollback are sensible. No new error-handling framework is warranted. |
| Deduplication | 5,047 blocked candidate pairs instead of 2,098,176 full pairs; shared scoring with initials/name guards and explanatory reasons. Scores are correctly described as heuristics. Keep blocks and thresholds. |
| Ingest | Exact-identifier conflicts are checked before mutations, plausible identities prevent arbitrary updates, established contacts/status/owner are preserved, and sample replay is stable. Add targeted tests under R-04. |
| Source extraction | Seven-category taxonomy, paid-versus-organic distinction, source fallback, raw Notes preservation, and reuse across HTTP/import/writes are sensible. Fix the localized evidence and ordering defects under R-01/R-02/R-03. |
| Readability and abstraction | Functions and feature modules are understandable. Some modules contain both business logic and routes, but this is acceptable here. No service/repository hierarchy, generic rule engine, or broad function-splitting exercise. |
| Duplication and side effects | UTC formatting and some test setup repeat, while matching decisions are shared. Import/backfill happen visibly in lifespan. The small amount of repetition does not justify a refactor. |
| Tests | Strong seed reconciliation and normal API workflows; insufficient coverage of certain decision boundaries and text combinations. Fix only the concrete gaps below. |
| Setup and scope | Installable project, environment overrides, startup cleanup, tracked data/docs/tests, and ignored generated files are suitable. No production deployment, worker, authentication, or dependency-migration work. |
| README | Broadly accurate about features, limitations, heuristics, and costs. Source guarantees currently exceed behavior in the reproduced cases; address with the fixes. A small documentation alignment is allowed under R-05. |

## Findings

### BLOCKER

None identified. The service runs and the supplied-data workflows function. The IMPORTANT defects below are localized but should be corrected before submission.

### IMPORTANT

#### R-01: Source details can invent or borrow evidence

- **Area:** Source extraction and persisted attribution.
- **Evidence:** `app/source_extraction.py:57`, `:90`, `:108`, `:115`; specification Section 7.
- **Problem:** Event extraction searches the entire normalized text for QR evidence and only protects the exact phrase "no QR scan logged". LinkedIn DM always becomes inbound, even if direction is not stated. Flattening newlines before referral extraction can absorb a subsequent sales update into a person's name.
- **Reproductions:**
  - `Met her at the Web Summit 2026 booth, she has not scanned our QR code.` returns `Web Summit 2026 - Booth QR Code`.
  - `Met her at the Web Summit 2026 booth. Scanned our QR code in the office a week later.` also assigns the office scan to the event booth.
  - `Sent a LinkedIn DM asking about pricing.` returns `LinkedIn DM inbound; pricing inquiry`.
  - `Referred by Aiko Diop\n\nConnected, sending proposal.` returns `Referred by Aiko Diop Connected`.
- **Why it matters:** This is one of the two core AI-assisted features. Incorrect evidence is subsequently stored and exported; the contract explicitly requires grounded details and no invented scan/person information. Matching seed category counts alone does not verify this.
- **Smallest fix:** Preserve sentence/paragraph boundaries in the extraction copy; match interactions and negation to the relevant event clause; limit referral capture to its clause; emit direction-neutral DM detail unless inbound is explicit. Extend a small set of patterns for the demonstrated cases, keeping the current module and taxonomy.

#### R-02: Channel selection ignores explicit chronology

- **Area:** Acquisition-source selection.
- **Evidence:** `app/source_extraction.py:197`, especially `:218`; specification Section 7 and PLAN's original-discovery assumption.
- **Problem:** The selector discards all Website evidence whenever another channel is found and reduces the remaining results to channel names. It never reads ordering language.
- **Reproductions:**
  - `Referred by Aiko Diop, then connected on LinkedIn.` returns `Other / Ambiguous source: Referral, LinkedIn`, despite explicit referral-first order.
  - Reversing the journey to `Connected on LinkedIn, then referred by Aiko Diop.` returns the same answer.
  - `Filled out the form on the homepage before meeting us at the SaaStr Annual booth.` returns Event, reversing the explicit chronology.
- **Why it matters:** This violates an agreed business rule, and can change dashboard attribution even though the evidence provides a clear order. Existing tests only check an unordered mixed-channel example.
- **Smallest fix:** Retain the matched evidence positions and recognize a bounded set of explicit journey connectors such as "then", "before", and "after". Select the stated original acquisition; preserve the existing search-to-website and event-to-form behavior. For genuinely unresolved competing acquisition evidence, return Other with concise ambiguity detail. Do not treat rule iteration order as temporal order or discard evidence merely because it shares an output enum.

#### R-03: Explicit Notes replacement can leave Website fallback behind

- **Area:** PATCH source recomputation.
- **Evidence:** `app/leads.py:169` through the `if notes_changed` branch at `:179`; specification Section 7 PATCH integration.
- **Problem:** Re-extraction is gated on text inequality, not on whether the user explicitly replaced Notes. A form-created lead can have null/generic Notes but nonempty Website fallback attribution.
- **Reproduction:** Ingest a unique lead with `message: null`, then PATCH that lead with `{"notes": null}`. The response remains Website with form/page detail. Similarly, ingest `message: "Hello"`, then PATCH `{"notes": "Hello"}`; Website fallback remains.
- **Why it matters:** The contract says deliberate Notes replacement derives source from that evidence and clearing yields Other / Source unspecified without restoring form context. This is reachable through ordinary supported HTTP requests.
- **Smallest fix:** Whenever Notes is explicitly supplied, calculate source from the resulting Notes without form fallback. Compare both text and derived fields to stored values. Commit and advance updated_at only if any persisted value actually changes. Status/owner-only PATCH must preserve source.

#### R-04: Matching tests omit consequential decision branches

- **Area:** Deduplication and ingest regression protection.
- **Evidence:** `tests/test_deduplication.py:73`, `:125`, `:173`; `tests/test_ingest.py:79`, `:152`, `:230`; specification Section 5/6 and the checked boundary-test claim at `docs/IMPLEMENTATION_SPEC.md:252`.
- **Problem:** Endpoint min_score validation is tested, but just-below/at-threshold scoring decisions are not. Ingest fixtures cover a single clear match and a fuzzy-only match separately, but not one clear candidate competing with a second likely candidate. Multiple exact hits are tested without the narrowing-identifier case. New-lead replay has only an earlier smoke-test/review diagnostic, not a committed regression test.
- **Why it matters:** These branches decide whether existing records can be changed automatically. A future simplification could silently select the first clear/exact match while every current fixture still passes. This is a focused test-quality issue, not evidence that the present matcher is wrong.
- **Smallest fix:** Add compact parameterized scoring-boundary cases and a few HTTP scenarios for competing plausible candidates, a shared exact identifier despite another identifier narrowing to one record, and replay after creation. Assert unchanged data on conflict. Keep the approved scoring rules and blocking unchanged.

### NICE-TO-HAVE

#### R-05: Small documentation inconsistencies

- **Area:** Technical status and stated limitations.
- **Evidence:** `docs/IMPLEMENTATION_SPEC.md:3` still awaits Milestone 8 review despite commit `c4f11d6`; `:9` says RapidFuzz is not installed and `:26` says business endpoints are absent inside a section labeled current architecture. README does not explain the implemented SFF alias or the accepted ASCII-oriented matching limitation required by specification Section 3.
- **Why it matters:** These statements can confuse a reviewer or the next agent, although README's main feature/setup description is sound.
- **Smallest fix:** Correct current status, explicitly label the Milestone 1 snapshot as historical, and add a concise SFF/year and multilingual limitation note. Keep the original assignment and pre-implementation analysis intact.
- **Disposition:** Include these tiny documentation changes in remediation milestone 3 because they improve clarity without expanding behavior.

#### R-06: Unused foundation schema

- **Area:** `app/schemas.py:40`, `LeadCreate`.
- **Problem/evidence:** Repository search finds a definition but no runtime or test consumers. Ingest uses WebsiteSubmission and Lead directly.
- **Why it matters:** It can suggest a second write contract to someone reading the schemas, but does not affect functionality.
- **Smallest fix:** Remove it only if a future schema change naturally touches this area and all references are still absent.
- **Disposition:** Leave it alone during remediation. No cleanup milestone or abstraction rewrite.

## Remediation Milestones

These numbers are separate from the completed implementation milestones 1-8. Remediation Milestones 1-3 are **ACCEPTED AND COMMITTED**.

### Remediation Milestone 1: Grounded Source Extraction

**Status:** ACCEPTED AND COMMITTED - R-01 and R-02 are complete.

**Final audit follow-up:** ACCEPTED AND COMMITTED. Prefixed `After`/`Before` journeys and referral clauses ending at those connectors are covered by regression tests.

#### Goal

Correct source evidence and original-acquisition selection within the current deterministic extractor.

#### Findings Addressed

R-01, R-02.

#### Scope

- Preserve enough text boundaries and matched spans to prevent evidence from unrelated clauses being combined.
- Handle the demonstrated QR negation, separate-location scan, referral/sales paragraph, and neutral DM cases.
- Resolve clearly ordered two-source journeys using a small documented connector policy; keep unordered ambiguity conservative.
- Preserve the seven channels, ten known event names, SFF alias, explicitly stated years, 500-character detail limit, and stateless endpoint shape.
- Keep raw Notes untouched. Share the corrected function through existing import, PATCH, and ingest integration.
- Explain the bounded ordering behavior briefly in README. Do not automatically rewrite already populated source fields in existing user databases; verify corrected extraction through fresh temporary import and deliberate Notes replacement.

#### Non-goals

No LLM, NLP framework, generic rule-engine architecture, exhaustive natural-language parser, new taxonomy, attribution-history table, bulk reattribution, or matching changes.

#### Expected Files/Areas Affected

`app/source_extraction.py`, `tests/test_source_extraction.py`, a short README source-extraction note. Update this plan's status after acceptance checks.

#### Required Tests

- Retain all existing source fixtures and seed-category reconciliation.
- Add QR affirmative, "has not scanned"/"did not scan", exact existing negation, and unrelated later scan cases.
- Add explicit inbound and neutral DM cases; referral with a separate operational paragraph and a multiword name.
- Test referral then LinkedIn and its reverse, Website before Event and Event before Website, and an "after" phrasing whose text order differs from time order.
- Retain search-to-website attribution and unordered ambiguity; assert detail contains only relevant evidence.
- Exercise representative corrected cases through the endpoint and persisted PATCH/fresh import. Confirm original Notes and years are preserved.
- Run the full suite once final changes are in place because extraction affects every write/import path.

#### Acceptance Criteria

- [x] All R-01/R-02 reproductions return grounded, chronologically defensible results.
- [x] Explicitly negated/unrelated scans never become booth scans for the R-01 cases.
- [x] Inbound direction and referral names are not invented.
- [x] Ordered journeys and unordered ambiguity are distinguished.
- [x] Existing supplied-data cases, taxonomy, API response shape, and raw text remain valid for R-01/R-02.
- [x] R-01/R-02 tests pass; README states bounded evidence and ordering rules without claiming general-language accuracy.

#### Risk

Pattern changes can reduce seed recall or overinterpret connectors inside names/page descriptions. Keep fixtures tied to observed evidence and use Other when ordering cannot be established.

### Remediation Milestone 2: Explicit Notes Replacement

**Status:** ACCEPTED AND COMMITTED - R-03 is complete.

#### Goal

Make PATCH attribution follow explicit Notes replacement even when the text value is unchanged.

#### Findings Addressed

R-03.

#### Scope

- Use request field presence to trigger Notes-only source recomputation.
- Treat a source-field change as a real persisted update, even when Notes already equals the supplied value.
- Preserve updated_at on a true no-op after recomputation.
- Ensure clearing Notes cannot recover Website attribution from form metadata on restart.
- Keep ingest's explicit-attribution preservation and Website fallback behavior intact.

#### Non-goals

No new source-history field, ingest identity changes, contact-write API, mass backfill, database migration, or shared update-service refactor.

#### Expected Files/Areas Affected

`app/leads.py`, `tests/test_source_extraction.py` or `tests/test_leads_api.py`; this plan's status.

#### Required Tests

- Create a lead through ingest with null message and Website fallback; PATCH null/blank Notes yields Other / Source unspecified immediately.
- Create a lead with generic message; PATCH the identical Notes derives Other / Source unspecified.
- Repeating that PATCH preserves the resulting timestamp and source; status/owner-only PATCH does not recalculate attribution.
- An actual source-only change updates updated_at, while contacts, created_at, original_source, and form metadata are preserved.
- Restart the temporary database and check clearing does not restore form fallback; list/detail/export/dashboard agree.
- Run affected API/source/ingest tests and then the complete suite.

#### Acceptance Criteria

- [x] Both R-03 reproductions are corrected.
- [x] A source-only change is committed atomically and timestamped.
- [x] True no-op PATCH does not advance the timestamp.
- [x] Omitted Notes and existing ingest attribution semantics are preserved.
- [x] Cleared source remains cleared after restart; full suite passes.

#### Risk

Treating every explicit Notes field as a write can break no-op timestamps. Determine changes after comparing the resulting source and text with stored values.

### Remediation Milestone 3: Decision Tests and Documentation Alignment

**Status:** ACCEPTED AND COMMITTED - R-04 and R-05 are complete.

#### Goal

Protect automatic-update decisions with targeted regression tests and finish small factual documentation corrections.

#### Findings Addressed

R-04; R-05 as the explicit small NICE-TO-HAVE exception.

#### Scope

- Add boundary fixtures around the name-compatibility and evidence thresholds used for clear/likely/rejected classification.
- Verify one clear plus another likely candidate returns 409; verify multiple exact email hits still conflict when phone narrows to one of them.
- Verify an immediately replayed newly created lead keeps its ID, count, Notes, source, timestamps, and form metadata.
- Correct the current implementation status, label historical architecture text, and add the short SFF/year and multilingual limitation note.
- Treat demonstrated scores and seed counts as regression fixtures, never accuracy estimates.

#### Non-goals

No threshold tuning, new blocking key, dedupe algorithm rewrite, broad fixture consolidation, coverage quota, unused-schema deletion, production hardening, or new endpoint.

#### Expected Files/Areas Affected

`tests/test_deduplication.py`, `tests/test_ingest.py`, `README.md`, `docs/IMPLEMENTATION_SPEC.md`; this plan's status. No application changes expected.

#### Required Tests

- A small parameterized set just below and at relevant 0.80/0.90 evidence boundaries, including the incompatible-given-name guard. Prefer deterministic synthetic names; narrowly isolate a similarity primitive only if needed, without mocking the decision under test.
- HTTP conflict tests with stable IDs and both exact and fuzzy candidate evidence; snapshot records, including metadata, before and after.
- Creation followed by exact replay, checking full persisted public fields and no additional row.
- Existing seed positives/negatives, ranked deterministic pairs, and API validation continue to pass.
- Run the complete suite and `git diff --check`. Review documentation against the final code and verified Git history.

#### Acceptance Criteria

- [x] Tests would catch removal of the competing-likely guard and improper narrowing of shared exact identifiers.
- [x] Threshold comparison direction is protected by boundary assertions.
- [x] New-lead replay has a committed regression test.
- [x] Documentation states the current validated implementation and limitations.
- [x] No scoring rule, block, schema, or endpoint behavior changes; full suite passes.

#### Risk

Fixtures that merely restate current implementation can create false confidence. Assert the specification's decision and persisted state, and do not adjust expected outcomes simply to make tests green. If a new test exposes a separate behavioral defect, report the smallest necessary correction before expanding this milestone.

## Execution Workflow

`Implement remediation milestone 1.` authorizes only that numbered remediation milestone.

1. Read this plan and the relevant specification sections; inspect current Git state.
2. Implement only the selected milestone with the smallest necessary changes.
3. Add/update required tests, run relevant checks, and verify acceptance criteria.
4. Update this plan to distinguish implemented, awaiting review, accepted, and committed work.
5. Report findings addressed, files/behavior changed, tests/results, and any deviation.
6. Stop for review. Do not commit newly implemented work.

On `Approved. Commit and continue to the next remediation milestone.`:

1. Verify passing evidence still applies; rerun relevant tests if code/state changed.
2. Commit only the approved milestone with a concise conventional commit message.
3. Select the next NOT STARTED remediation milestone from this document.
4. Implement, test, report, and stop for review again; do not commit that new milestone without approval.

A commit-only instruction does not authorize further implementation. Review artifacts are not committed by this review. Later commit commands must not silently bundle unrelated changes.

## Decisions Before Starting

No additional employer clarification or architecture decision is required for this plan. Original-acquisition ordering and deliberate Notes replacement are already specified; remediation restores those behaviors. An instruction to implement a numbered remediation milestone is sufficient to begin that work. Keep the current rules-based approach, blocking thresholds, storage, and public API.

If desired behavior changes beyond these requirements emerge, document the concrete tradeoff and follow AGENTS.md rather than silently altering business rules.
