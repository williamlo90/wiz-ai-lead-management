# 1-CSV Analysis before coding

Analysis date: 7 September 2026.

Sources inspected in `C:\Users\William\OneDrive\Dokumen\AI_Builder_Takehome_Candidate_Package`: `docs/ASSIGNMENT.md`, `data/leads_seed.csv`, and `data/website_form_submissions.json`.

This is a pre-implementation analysis. Counts below come from parsing all CSV records and JSON entries, not from a sample. No application code, dependencies, source data, or assignment files were changed. This report is saved outside the assignment repository.

## 1. Actual requirements

Build a small backend within approximately 6-8 focused hours. The required outcome is a working lead API plus duplicate suggestions and structured source extraction. A polished frontend is unnecessary. The assignment explicitly accepts fuzzy matching for deduplication and rules/regex for extraction; a paid LLM, embeddings, and external credentials are not required.

| Deliverable | Required behavior |
| --- | --- |
| Seed import | Load the CSV into a justified storage choice. Normalize enough to make the API and matching useful. |
| `GET /leads` | List leads; filter by status, Contact Owner, and country; search name/company/email with `q`. |
| `GET /leads/:id` | Return one lead. |
| `PATCH /leads/:id` | Update status, owner, or notes. |
| `GET /leads/export` | Export the current filtered result as CSV. |
| `POST /leads/ingest` | Accept one object shaped like a website submission; create a lead or update an existing person. |
| Duplicate detection | Endpoint `POST /leads/dedupe-candidates` or offline script; return ranked candidate pairs/groups with confidence and explanation. Generate candidates before scoring. |
| Source extraction | Function or endpoint accepting text; return `channel` and `detail`. |
| README and tests | Run instructions, design decisions, assumptions, meaningful tests, and what to do next. Disclose provider/model and approximate credits only if a paid LLM is used. |

Allowed source channels: `Website`, `Event`, `LinkedIn`, `Organic Search`, `Referral`, `Manual/Sales`, `Other`.

`GET /dashboard`, with counts by status and source channel, is a bonus. Automatic merging of seed duplicates is not required. Ingest matching is still required even when dedupe only returns suggestions.

Explicit exclusions: authentication/roles, analytics integrations, webhook infrastructure beyond ingest, audit-history UI, HubSpot migration tooling, deployment, scaling, and monitoring. Submit a repository link or ZIP within seven days of receipt.

## 2. Dataset structure and observed messiness

### CSV profile

The seed contains **2,049 records and 22 columns**. Every Record ID is present and unique. There are no identical whole records after excluding Record ID; the problem is identity resolution, not removing repeated CSV lines.

Populated means nonempty after trimming whitespace.

| Field | Populated | Blank | Practical use |
| --- | ---: | ---: | --- |
| Record ID | 2,049 | 0 | Stable identity for the stored record, not proof of a unique person. |
| First Name | 1,942 | 107 | Name display and matching. |
| Last Name | 1,942 | 107 | Name display and matching. |
| Full Name | 107 | 1,942 | Alternative name representation. |
| Job Title | 1,221 | 828 | Optional context; not needed for the required behavior. |
| Company Name | 2,049 | 0 | Search and supporting duplicate evidence. |
| Email | 2,049 | 0 | Strong identity evidence, search, domain blocking. |
| Phone Number | 2,049 | 0 | Strong identity evidence after formatting normalization. |
| Country/Region | 2,049 | 0 | Required filter and supporting context. |
| City | 0 | 2,049 | Ignore in the minimal model. |
| Lead Status | 2,049 | 0 | Required filter and update field. |
| Lifecycle Stage | 1,756 | 293 | Optional context; distinct from Lead Status. |
| Original Source | 1,035 | 1,014 | Preserve as raw context; insufficient as final source attribution. |
| Original Source Drill-Down 1 | 0 | 2,049 | Ignore. |
| Contact Owner | 2,049 | 0 | Required filter and update field. |
| Create Date | 2,049 | 0 | Useful record context; normalize consistently. |
| Last Modified Date | 1,496 | 553 | Optional timestamp; do not invent missing history. |
| Notes | 2,049 | 0 | Main source-extraction input and required update field. |
| Annual Revenue | 0 | 2,049 | Ignore. |
| Marketing contact status | 0 | 2,049 | Ignore. |
| GDPR consent | 0 | 2,049 | Ignore. |
| Lead Score | 153 | 1,896 | Sparse, unexplained score; omit from matching and core behavior. |

The assignment's prose understates Job Title coverage: it is populated on about 60% of records, not merely a handful. City is entirely empty. These are scope decisions, not defects to fix in the supplied files.

Name fields are mutually exclusive in this file: 1,942 records have first/last names, while 107 have only Full Name. Of the full-name-only records, 53 begin with an initial, such as `J. Diallo`. Multiword given names such as `Wei Ming` make naive splitting unreliable.

### Website submission profile

The JSON is an array of **90 objects**, each with the same 10 keys. All supplied values are nonempty strings.

| JSON key | Mapping or purpose |
| --- | --- |
| `name` | Lead display name and name matching; do not require first/last splitting. |
| `email` | Email identity key. |
| `phone` | Phone display value and normalized identity key. |
| `company` | Company display value and matching input. |
| `country` | Normalized country filter value. |
| `message` | Incoming note and source-extraction evidence. |
| `submitted_at` | Submission time; all 90 parse as UTC ISO timestamps. |
| `form_id` | Form definition, not a unique submission ID. Only four distinct values. |
| `form_name` | Form label; retain without deriving it from form_id. |
| `page_url` | Relative page path: `/blog`, `/book-a-demo`, `/pricing`, or `/contact`. |

There are 90 distinct emails, 90 distinct digit-normalized phones, and 90 distinct names within the JSON. Submission timestamps range from `2025-09-01T15:55:00Z` to `2026-06-19T14:02:00Z`.

Against the seed, 49 submissions have both exact normalized-email and digit-normalized-phone matches; 41 have neither. This is an exact-key overlap measurement, not a verified count of existing versus new people. Fuzzy matching could change the interpretation of the 41.

For nine submissions, the union of matching email/phone records contains more than one seed record. Their 1-based JSON positions are 19, 24, 38, 52, 56, 69, 72, 77, and 84. Ingest cannot assume an exact-key lookup always returns one record.

Form metadata is internally inconsistent. Using the natural mapping of `form_demo_request` to `Book a Demo`, `form_newsletter_signup` to `Newsletter Signup`, `form_contact_general` to `Contact Us`, and `form_pricing` to `Pricing Inquiry`, **66 of 90 labels disagree with their form ID**. This count depends on that stated interpretation. For example, the first entry has `form_demo_request`, `Newsletter Signup`, and `/blog`. Preserve these values and do not fabricate a corrected form identity.

The generic message `Following up after our earlier conversation, please send more info.` appears 49 times. It supplies no clear original acquisition channel.

## 3. Useful fields and minimal model

Use one `leads` table. Retain seed Record IDs as the API IDs and generate fresh IDs for new leads. Do not enforce email or phone uniqueness, because the seed intentionally contains multiple records with those values.

Store display name, company, email, phone, country, status, owner, notes, original source, created date, and nullable modified date. Add normalized email, phone digits, name, and company keys where they simplify candidate queries. Store derived `source_channel` and `source_detail` for consistent detail responses and the optional dashboard.

A small nullable JSON metadata field can retain incoming form ID/name/page/submitted time without adding a submissions service or a separate event-history model. Job Title and Lifecycle Stage can be omitted from the operational model with the original CSV retained as supplied. Lead Score should not become duplicate confidence: it measures an unspecified CRM concept.

Country, owner, status, dates, and similar Notes are not identity keys. In particular, many unrelated leads share templated Notes, so Notes similarity should not materially raise duplicate confidence.

## 4. Normalization issues

| Issue | Observed evidence | Minimal treatment |
| --- | --- | --- |
| Status casing/spacing | 35 raw values reduce to seven; 277 have surrounding spaces and 894 differ from canonical spelling. | Trim and map case-insensitively to the seven observed statuses. Use the same mapping for import, filters, and PATCH. |
| Owner whitespace | 20 raw owner values reduce to 10 after trimming; 66 records have trailing spaces. | Trim values; compare filters case-insensitively. No users table is needed. |
| Country casing | 62 raw values reduce to 35 after case normalization; 45 records use lowercase. | Use a small explicit canonical display mapping; preserve `UAE` capitalization. |
| Alternative names | 107 records have only Full Name; initials and multiword names occur. | Prefer nonempty Full Name, otherwise join first/last. Preserve display text and use a separate comparison form. Never expand initials as fact. |
| Company variations | 1,307 raw names; punctuation and `&`/`and` normalization reduces this to 1,175. Examples include `Pte Ltd`, `Pte. Ltd.`, `Inc`, and `Inc.`. | Normalize case, punctuation, whitespace, and `&`/`and` for comparisons. Remove only recognized trailing legal suffixes as an optional extra key. |
| Company semantic differences | Ahmed Schulz's matching contact records use `Schmidt AG Analytics` and `Schmidt AG Freight Solutions`. | Company similarity is supporting evidence. Do not strip every descriptive word or require equal company strings. |
| Email | 1,991 distinct values; all supplied emails are lowercase with no surrounding whitespace and pass a basic shape check. | Trim and lowercase as an explicit matching convention. Preserve local-part punctuation; do not globally erase dots or plus tags. Syntax does not prove deliverability. |
| Phone formatting | 1,890 numbers start with `+`; 159 contain digits only. Spaces and hyphens vary. | Keep raw phone and a digits-only comparison key, including country code. Never compare only the last few digits. |
| Mixed dates | ISO dates, slash dates, and ISO UTC midnight timestamps occur. | Parse the three explicit formats. Interpret slash dates as month/day/year, supported by values such as `12/21/2025`. |
| Missing modification date | 553 blanks. | Store null. On an actual update, write the service update time. |
| Notes text | 775 distinct strings; 136 contain a Unicode dash in a possible-duplicate warning. | Read/write UTF-8, preserve Notes, and exclude operational suffixes from source detail. |

Date-format counts:

| Field | `YYYY-MM-DD` | `M/D/YYYY` | ISO UTC timestamp | Blank |
| --- | ---: | ---: | ---: | ---: |
| Create Date | 1,125 | 599 | 325 | 0 |
| Last Modified Date | 776 | 479 | 241 | 553 |

All nonempty dates parse under these conventions. Both fields span 1 September 2025 through 19 June 2026, and no populated modification date precedes its creation date. Date-only inputs have no real time-of-day: retain date precision or document a UTC-midnight representation as a storage convention.

The phone observations support a simple digits key for this dataset. They do not establish that every synthetic number is a valid reachable telephone number. Missing values in future ingest requests should stay missing and must never create a shared empty matching block.

Normalized status totals are New 270, Contacted 282, Connected 293, Qualified 321, Opportunity 291, Closed Won 276, and Closed Lost 316. These sum to 2,049 and provide an import/dashboard reconciliation check before updates.

## 5. Duplicate detection

### Evidence from the seed

| Equality rule | Repeated-value groups | Records in those groups | Candidate pairs |
| --- | ---: | ---: | ---: |
| Exact email after trim/lowercase | 58 | 116 | 58 |
| Raw phone text | 114 | 232 | 122 |
| Phone digits | 232 | 495 | 294 |
| Display name after lowercase/space normalization | 255 | 550 | 339 |

All 58 same-email pairs also have the same normalized phone. Another 236 phone-equal pairs have different email strings. Phone groups contain up to three records. The 263 records in excess of one per phone group are **not a confirmed duplicate count**. Shared identifiers and similar names require interpretation; no ground-truth labels are supplied.

Representative cases, located by Record ID:

| Records | Evidence | Implication |
| --- | --- | --- |
| `100234834`, `100234835` | `Joon Diallo` versus `J. Diallo`; same email and phone, different company wording. | Initial-name compatibility plus strong contact evidence. |
| `100234846`, `100234847` | Isabelle Kapoor; `isabellek@mensahtrading.com.au` versus `isabellekapoor@mensahtrading.com.au`; same phone. | Exact email alone misses an evident candidate. |
| `100234854`, `100234855` | Ahmed Schulz; `+46 70 460 23 83` versus `46704602383`; same email. | Formatting must not split identity keys. |
| `100236413`, `100236414` | Ravi Agyemang versus Rin Agyemang at Zhang Holdings; same email domain but different email, phone, and country. | A useful likely-negative review case. Similar name/company is insufficient to merge. |
| `100236225`, `100236226` | Ama Bianchi versus Farah Bianchi at Kilat Retail Solutions; same domain, different contact identifiers. | Do not turn shared surname/company into person identity. |

The likely-negative examples are reasoned review cases, not supplied labels. Likewise, the 136 Notes containing `possible duplicate` are hints, not a complete or authoritative evaluation set. Do not use those warnings or adjacent Record IDs as a shortcut to identity classification.

### Recommended approach: blocking plus explainable fuzzy scoring

Generate pairs from the union of nonempty equal email, equal phone digits, equal email domain, and normalized company blocks. Deduplicate pairs before scoring. A normalized-name block can be added cheaply to recover candidates that changed company/domain, with the understanding that common names generate unrelated candidates too.

An in-memory profiling calculation using only the first four blocks produced:

| Block | Candidate pairs | Largest block |
| --- | ---: | ---: |
| Exact normalized email | 58 | 2 |
| Phone digits | 294 | 3 |
| Exact email domain | 3,899 | 13 |
| Company after case/space/punctuation and `&` normalization | 1,385 | 7 |
| Union of those four | **5,047** | Not applicable |

There are 2,098,176 possible unordered pairs overall. These blocks reduce pairs by **99.76%** on this file. That is a measured workload reduction, not recall, precision, a runtime benchmark, or a guarantee that every duplicate survives blocking. Legal-suffix removal and additional blocks would change this count.

Score surviving candidates with a proven fuzzy-string library such as RapidFuzz. Combine exact email, exact phone, compatible full/initial names, name similarity, and company similarity. Different nonempty contact details and incompatible given names should lower confidence. Missing evidence is not a mismatch, but it is also not agreement. Country is a weak supporting signal, not a mandatory equality rule.

Return sorted pairs with IDs, a heuristic score, confidence band, and concrete reasons such as `same phone after normalization` or `same domain but conflicting contact details`. Do not present the score as a calibrated probability. Set thresholds using a small reviewed set of strong positives and plausible negatives; do not claim accuracy from the unlabeled file.

The assignment explicitly permits candidate pairs, so two-member groups are sufficient. Avoid transitive automatic grouping that implies A and C are duplicates merely because each resembles B. No seed auto-merge is necessary.

Embeddings, vector databases, and LLM pair scoring add setup and evaluation work with limited benefit for this small, identifier-heavy dataset. They can be mentioned as future alternatives, not baseline dependencies.

### Ingest matching policy

Reuse the same normalization and candidate-generation functions. Update when there is one clearly supported identity, prioritizing exact email with compatible supporting evidence, then exact phone plus compatible name. A fuzzy-only update should require corroborating evidence and an unambiguous best candidate; otherwise return a conflict for review.

When email and phone identify different people, or multiple records remain equally plausible, return `409` with candidate IDs and reasons. Do not update every matching record or silently select the first. This is a proposed resolution of an unspecified edge case; the normal ingest path still creates or updates leads.

For a matched lead, preserve status and owner, retain established contact values unless filling missing fields, and append a new nonempty message only if it has not already been recorded. Do not replace an established acquisition source with a generic follow-up. For a new lead, default to `New` and an unassigned/null owner. Reposting the same submission should not create another lead or append the same message again. `form_id` cannot serve as an idempotency key.

## 6. Notes and source extraction

Every seed record has Notes. Their acquisition sentences fall into the following observed families. These counts describe text patterns, not validated model predictions.

| Notes family | Records | Proposed channel/detail policy |
| --- | ---: | --- |
| Event booth interactions | 374 | `Event`; capture the named event and actual interaction. |
| Explicit referrals | 241 | `Referral`; extract the referrer's name. |
| Website form completion | 388 | `Website`; extract the page description. |
| Google ad followed by demo booking | 119 | `Other`; retain paid Google search and demo-page information in detail. |
| Explicit Other, e.g. walk-in or general inbox | 153 | `Other`; retain the stated contact method. |
| Organic Google search / Googled us | 311 | `Organic Search`; retain Google and the landing-page description. |
| Manual entry / phone outreach | 186 | `Manual/Sales`; distinguish inbound call and cold outreach. |
| Explicit LinkedIn mention | 186 | `LinkedIn`; distinguish DM and post interaction. |
| Post/comment without named platform | 91 | `Other`; detail `Social post interaction; platform unspecified`. |
| Total | **2,049** | |

The 119 Google-ad records lack a matching channel in the required taxonomy. Mapping them to `Other` preserves acquisition meaning without incorrectly calling paid traffic organic. `Website` with a paid-ad detail is another defensible choice, but the README should state which definition is used.

The 91 unspecified-platform records say `Saw our post about replacing hubspot and commented.` Forty have Original Source `Social Media`; 51 have it blank. Neither proves LinkedIn. Do not infer a specific platform from the neighboring templates.

Other important patterns:

1. Ten event names occur: SaaStr Annual, TechCrunch Disrupt, Mobile World Congress, Dubai FinTech Week, Singapore FinTech Festival 2026, Money20/20 Asia, London Tech Week, Web Summit 2026, Retail Asia Expo, and APAC Logistics Summit. Preserve years only where the text states them.
2. Fifty-four event Notes say `no QR scan logged`. They must not become `Booth QR Code`. Use a booth-conversation detail that preserves the lack of a recorded scan. Other booth encounters also do not necessarily state that a QR scan occurred.
3. The abbreviation `SFF` occurs in the assignment example but zero times in the seed Notes. Supporting a documented SFF alias is reasonable, but it is not an observed seed pattern, and an abbreviation alone does not establish the year.
4. Status-like suffixes such as `No response yet`, `Great fit, prioritizing`, and `Connected, sending proposal` describe sales progress rather than acquisition. They should not appear in source detail or override Lead Status.
5. The `possible duplicate` warning is also operational text. Preserve it in Notes but exclude it from source detail.
6. Original Source is blank on 1,014 records. For event records specifically, 214 are blank, 129 say `Offline Sources`, and 31 say `Other Campaigns`. Notes supply much more useful information.
7. In the JSON, the message may describe an event, referral, or search journey despite arriving through a website form. The ingestion transport does not automatically establish original acquisition source.

Use ordered, case-insensitive patterns for specific acquisition evidence, followed by a narrow fallback. Extract detail from the matched span rather than hardcoding every full sentence. Explicit paid advertising must not hit a generic Google/organic rule; negated QR statements must not hit an affirmative QR rule.

For a text-only request with no source evidence, return `Other` and a concise unspecified-source detail. For a new lead arriving through a known form with an uninformative message, use `Website` as a documented fallback based on form context, retaining the actual page/form metadata. For an existing lead's generic follow-up, keep its established source. Recompute source when Notes are explicitly replaced through PATCH so the stored fields remain consistent.

## 7. Ambiguities and proposed defaults

These choices can be documented and implemented without waiting for clarification.

| Unspecified point | Proposed decision |
| --- | --- |
| Does AI-assisted mean an actual LLM call? | No. Use the explicitly permitted fuzzy matching and extraction rules, and describe them truthfully. |
| Person versus stored record | Preserve every seed record. Duplicate suggestions identify potential shared identity without deleting records. |
| What constitutes duplicate confidence? | Explainable heuristic score and reviewed thresholds, not probability or claimed accuracy. |
| Multiple matching records on ingest | Update only an unambiguous match; return `409` otherwise. |
| Field precedence on repeat submission | Preserve existing status/owner and populated contact details; fill blanks and append distinct message text. |
| First-touch versus latest-touch source | Prefer the original acquisition evidence. A generic follow-up does not overwrite it. |
| Paid advertising missing from taxonomy | Use `Other` with explicit paid-search detail. |
| Social post without platform | Use `Other`, not an assumed LinkedIn label. |
| Conflicting form ID/name/page | Preserve all three raw values; do not repair one from another. |
| New-lead status/owner | `New`, with null/unassigned owner. |
| PATCH nulls and invalid fields | Allow explicit clearing of owner/notes; reject null or unknown status and fields outside the supported patch surface. |
| Date-only input timezone | Preserve date meaning; document any UTC-midnight storage convention. |
| Filtering semantics | AND supplied filters; case-insensitive exact status/owner/country and substring `q` across name/company/email. |
| Pagination/export | Simple stable ID ordering with limit/offset for listing. Export all matching records, not just the displayed page. |
| Export schema | Document a stable normalized lead schema; reproducing all 22 raw CRM columns is not requested. |
| JSON array versus ingest request | Treat the file as examples and accept a single entry per request. Batch ingest is unnecessary. |
| Seed reload | Explicit import once into an empty store; do not recreate leads or overwrite edits on restart. |
| Optional dashboard meaning | Count stored records, including unresolved duplicates, and label the result accordingly. |

No full precision/recall estimate or confirmed number of unique people can be derived from the supplied files alone. A small manually reviewed test set is suitable; a full annotation project is not.

## 8. Minimal implementation for 6-8 hours

Assuming Python familiarity, use **FastAPI, SQLite, RapidFuzz, and pytest**. Use standard-library CSV/JSON parsing and SQLite access. API documentation plus a few example requests can be the demo interface. Framework choice should follow the candidate's familiarity rather than force a new stack.

Keep a few focused modules: API/schema definitions, storage/import, normalization, duplicate matching, and source extraction. Use one leads table, a handful of matching-key indexes, and ordinary functions. No generic repository framework, dependency-injection framework, background queue, vector service, or frontend application is needed.

| Work block | Hours | Completion criterion |
| --- | ---: | --- |
| Setup, model, import, normalization | 0.75 | 2,049 records import with unique IDs; restart preserves stored edits. |
| Core API and filtered CSV export | 1.50 | List/detail/patch/export work consistently; ingestion schema is defined. |
| Candidate generation and fuzzy scoring | 1.50 | Ranked, explained pairs; candidate count reported; reviewed positive/negative cases. |
| Ingest create/update/conflict behavior | 0.75 | New person, existing person, ambiguous match, and repeated request paths work. |
| Source extraction and integration | 1.00 | Required channels, useful detail, unknown-text behavior, and Notes update handling. |
| Focused tests and fixes | 0.75 | Ambiguous behavior and core API paths verified. |
| README and runnable demo | 0.50 | Fresh setup, requests, decisions, limitations, and next steps documented. |
| Optional dashboard or contingency | 0.50 | Add counts only if core behavior is complete; otherwise spend on fixes. |
| Total | **7.25** | Core work remains the priority. |

Write tests alongside each feature; the testing block is for integration and fixes. At a six-hour limit, omit the dashboard and elaborate scoring refinements while keeping all three required pieces.

High-value verification cases:

1. Import count and normalized status totals; full-name-only records; three date formats; optional missing modified date.
2. A combined filter plus search produces the same lead IDs in listing and unpaginated export. CSV fields with commas/quotes/newlines round-trip through a standard parser.
3. PATCH rejects invalid status/unsupported fields, handles missing IDs, and refreshes extracted source when Notes change. Register static paths such as `/leads/export` before the dynamic detail route.
4. Duplicate suggestions include the observed phone-format, email-local-part, and initial-name examples. Likely-negative similar-name/company cases do not get automatic-update confidence.
5. Missing identifiers do not form a common block. Pair output has no self-pairs or repeated unordered pairs, and scoring is restricted to generated candidates.
6. Ingest creates, updates, preserves status/owner, handles multiple exact matches, and does not duplicate a repeated submission's note.
7. Extraction handles affirmative versus negated QR scan, paid versus organic Google traffic, unnamed social platforms, referral names, operational suffixes, and unknown text. A generic follow-up preserves an established source.

The baseline deliberately stops at a local, demonstrable backend. Leave deployment, authentication, migrations frameworks, background processing, full audit history, automatic merging, LLM orchestration, and polished UI out of this submission. The strongest use of remaining time is clearer decisions and a reliable end-to-end demo.
