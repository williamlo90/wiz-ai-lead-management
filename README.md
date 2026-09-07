# Wiz AI Lead Management

Small FastAPI service for importing and managing the supplied CRM-style lead dataset. It provides persistent SQLite storage, normalized seed import, lead APIs and CSV export, guarded website-form ingestion, explainable duplicate candidates, and rule-based source extraction.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

On macOS or Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

Run the service:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API documentation.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Available API

- `GET /health`
- `GET /dashboard`
- `GET /leads?status=&owner=&country=&q=&limit=&offset=`
- `GET /leads/export` with the same filters and search
- `POST /leads/ingest`
- `POST /leads/dedupe-candidates`
- `POST /leads/extract-source`
- `GET /leads/{id}`
- `PATCH /leads/{id}` with status, owner, and/or notes

Filters combine with AND. Search is a case-insensitive literal substring across name, company, and email. Export returns the complete filtered view rather than one paginated list page.

Configuration can override the defaults with `DATABASE_URL` and `SEED_DATA_PATH`. SQLite and synchronous SQLAlchemy keep the local take-home setup small and persistent.

```powershell
$env:DATABASE_URL = "sqlite:///C:/temp/wiz-leads.db"
$env:SEED_DATA_PATH = "C:/path/to/leads_seed.csv"
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

## Example Requests

List and search leads:

```http
GET /leads?status=Qualified&country=Singapore&q=fintech&limit=25&offset=0
```

Update the supported operational fields:

```http
PATCH /leads/100234811
Content-Type: application/json

{"status":"Qualified","owner":"Marcus Wong","notes":"Referred by Aiko Diop, warm intro."}
```

Extract acquisition source without storing anything:

```http
POST /leads/extract-source
Content-Type: application/json

{"text":"Met her at the Singapore FinTech Festival 2026 booth, scanned our QR code."}
```

```json
{"channel":"Event","detail":"Singapore FinTech Festival 2026 - Booth QR Code"}
```

Ingest accepts one object shaped like an entry in `data/website_form_submissions.json`:

```http
POST /leads/ingest
Content-Type: application/json

{
  "form_id": "form_demo_request",
  "form_name": "Book a Demo",
  "page_url": "/book-a-demo",
  "submitted_at": "2026-07-01T05:00:00Z",
  "name": "Ada Lovelace",
  "email": "ada@example.com",
  "phone": "+1 212 555 0100",
  "company": "Example Inc.",
  "country": "United States",
  "message": "Found us through organic google search then landed on the book-a-demo page."
}
```

## Import and Normalization

On first startup, an empty database imports all 2,049 seed rows in one transaction while retaining their original record IDs. A nonempty database is never reimported or overwritten on restart. Existing databases receive a narrow backfill only when derived source fields are missing.

Display values retain useful source formatting. Separate matching keys casefold email/name, keep complete phone digits including country code, and normalize company punctuation and whitespace. Status is mapped to the seven observed canonical values; owner whitespace and country casing are normalized. Email and phone are deliberately not unique because duplicate seed records must remain representable.

The importer explicitly supports `YYYY-MM-DD`, `M/D/YYYY`, and ISO UTC timestamps. Date-only values are stored as UTC midnight by convention, not as observed event times. Blank modification dates remain null; API timestamps are serialized with `Z`. Raw seed files are never rewritten.

## Duplicate Candidates

The deduplication endpoint first blocks records on normalized email, phone, email domain, or company, then applies explainable RapidFuzz name/company rules. On the supplied seed this evaluates 5,047 candidate pairs instead of all 2,098,176 possible pairs. Results contain a heuristic score, confidence band, and evidence such as matching normalized contact details or conflicting names.

Scores are conservative decision rules, not calibrated probabilities. Similar company/domain values alone cannot produce a match, missing fields do not count as agreement, and incompatible fully spelled given names prevent false positives. The endpoint is read-only and does not merge records.

## Website Form Ingestion

`POST /leads/ingest` validates a website submission and returns `201` with `action: "created"` for a new identity or `200` with `action: "updated"` for one clearly supported existing identity. Updates preserve established contact, owner, status, and creation data; distinct messages are appended without changing line formatting. Exact replays do not add a record, duplicate Notes, or change timestamps.

Ambiguous exact matches, conflicting email/phone identities, incompatible names, and fuzzy-only likely matches return `409` with a machine-readable `ambiguous_match` or `conflicting_identity` code plus ranked candidate evidence. This intentionally requires human resolution instead of choosing or updating a seed duplicate automatically.

## Source Extraction

`POST /leads/extract-source` accepts `{"text": "..."}` and returns one of the seven required channels plus concise evidence-based detail. The extractor uses deterministic, case-insensitive rules for event booths, referrals, LinkedIn, organic Google discovery, website forms, and manual sales entry. It preserves stated event years, distinguishes QR scans from explicit scan negation, maps paid Google advertising and unnamed social posts to `Other`, and returns `Source unspecified` when there is no evidence. Operational sales updates and duplicate warnings are excluded from the derived detail while the original Notes remain unchanged.

Event interactions and referral names are bounded to the relevant sentence or clause, and LinkedIn DM direction is included only when the Notes state it explicitly.

When exactly two distinct sources are connected by one explicit `then`, `before`, or `after`, the extractor selects the stated original acquisition. Without explicit ordering, search/event evidence remains the acquisition rather than a later Website form transport; genuinely competing non-Website sources remain `Other` with ambiguity detail.

Fresh seed imports derive source fields immediately, and startup backfills only missing derived fields in existing databases. PATCH recomputes attribution when Notes are replaced. Ingest prefers explicit message evidence, uses the known form as a Website fallback for new leads, and preserves established acquisition evidence through generic follow-ups. These are transparent heuristics rather than externally verified marketing attribution; no LLM or paid API is used.

## Dashboard

`GET /dashboard` returns the total stored records plus counts by canonical status and extracted source channel. Every supported category is present even when its count is zero, and both count groups reconcile to the total.

## Scope and Limitations

- Matching scores are review heuristics, not calibrated probabilities or measured accuracy. Candidate generation can miss identities when every blocking key changes.
- Ambiguous ingestion requires manual resolution; there is no merge or conflict-resolution endpoint.
- Replay protection prevents duplicate lead/message changes for the demonstrated flow, but it is not an exactly-once delivery system.
- Source extraction recognizes the supplied text families and returns grounded detail; it is not a general natural-language attribution model.
- SQLite and synchronous request handling are intentional for this local take-home. Authentication, queues, deployment, monitoring, and a frontend are out of scope.
- No LLM was used, so there is no provider, model, credential, or API cost.

## Next Steps

With more time, I would validate matching thresholds against a labeled review set, add a human conflict-resolution workflow, introduce migrations and stronger database constraints, and add authentication plus production observability only when deployment requirements justify them.
