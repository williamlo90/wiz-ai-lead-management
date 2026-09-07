# WIZ.AI Lead Management

A small backend service for organizing sales leads: people or companies that may become customers. It turns a messy CRM export into searchable records, flags possible duplicate contacts, and reads sales notes to identify how each lead discovered the company.

For example, two entries with slightly different names and the same phone number can be flagged for review. A note about meeting someone at an event booth becomes an **Event** source with the event name and interaction details.

Built for the [WIZ.AI Mid-Level AI Builder take-home](docs/ASSIGNMENT.md), using the supplied synthetic dataset of **2,049 lead records**. It runs locally and can be tried through Swagger UI, an interactive API page in your browser.

## What It Does

| Task | Result |
| --- | --- |
| Find and manage leads | Search by name, company, or email; filter by status, owner, and country; update status, owner, or notes. |
| Export a selection | Download all records matching the current filters as CSV. |
| Receive a website form | Create a new lead or update one clearly identified existing contact. Uncertain matches are returned for human review. |
| Spot duplicate contacts | Return likely duplicate pairs, ranked by confidence, with reasons for each suggestion. Records are not automatically merged. |
| Identify lead sources | Turn free-text notes into a source category and a short explanation. |
| View a summary | Return counts by lead status and source category through the bonus dashboard endpoint. |

**Example: turning a note into structured source information**

Input:

> Met her at the Singapore FinTech Festival 2026 booth, scanned our QR code.

Output:

```json
{
  "channel": "Event",
  "detail": "Singapore FinTech Festival 2026 - Booth QR Code"
}
```

The application uses fuzzy matching and text rules. It requires no language model or API key, and its LLM API cost is **$0**.

## Run and Try It

Requires **Python 3.11 or newer**. Clone or download the repository, then run these commands from its root directory.

### Install and Start

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m uvicorn app.main:app --reload
```

Startup creates a local `leads.db` file and imports the supplied seed automatically. No separate database service is required. Changes are saved between restarts.

### Try the Main Features

Open [Swagger UI](http://127.0.0.1:8000/docs). Expand an endpoint, select **Try it out**, enter any parameters or request body, and select **Execute**. Results appear on the same page.

1. **See the summary:** execute `GET /dashboard`. A fresh database has `total: 2049`, with counts by status and source.
2. **Browse leads:** execute `GET /leads` with `limit=10`. Try `country=Singapore` or enter part of a name, company, or email in `q`.
3. **Review duplicate suggestions:** execute `POST /leads/dedupe-candidates` with:
   ```json
   {"min_score": 0.75, "limit": 10}
   ```
   Each pair includes lead IDs, a score, a confidence band, and reasons.
4. **Identify a source:** execute `POST /leads/extract-source` with:
   ```json
   {"text": "Met her at the Singapore FinTech Festival 2026 booth, scanned our QR code."}
   ```
   The result matches the Event example above. This endpoint does not modify stored records.

Swagger UI is the interface for this backend submission; the dashboard returns JSON counts rather than rendered charts.

## API Reference

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Check service health and record count. |
| `GET /leads` | List leads using `status`, `owner`, `country`, `q`, `limit`, and `offset`. |
| `GET /leads/{id}` | Read one lead. |
| `PATCH /leads/{id}` | Update status, owner, and/or notes. |
| `GET /leads/export` | Export all leads matching the same filters and search. |
| `POST /leads/ingest` | Accept one website-form submission. |
| `POST /leads/dedupe-candidates` | Suggest duplicate pairs for review. |
| `POST /leads/extract-source` | Extract a source from text without saving it. |
| `GET /dashboard` | Return total records and counts by status and source. |

Filters combine with AND. Search is a case-insensitive literal substring across name, company, and email. Export includes the complete filtered view, not just the current page.

Example update:

```http
PATCH /leads/100234811
Content-Type: application/json

{"status":"Qualified","owner":"Marcus Wong","notes":"Referred by Aiko Diop, warm intro."}
```

Example website submission, shaped like an entry in [website_form_submissions.json](data/website_form_submissions.json):

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

## Design Decisions

### Storage and Messy Data

**FastAPI** exposes the API, **Pydantic** validates requests and responses, and **SQLAlchemy with SQLite** provides persistent storage. SQLite keeps setup small without requiring a database server.

The model retains contact details, status, owner, Notes, timestamps, raw Original Source, derived source fields, and form metadata. Revenue, consent, job title, city, and lead score are omitted from storage because the required workflows do not use them. Both original data files remain included and unchanged.

Normalization follows a few explicit rules:

- Use `Full Name` when present; otherwise combine `First Name` and `Last Name`.
- Map status variations such as `new` and ` NEW ` to the seven observed canonical statuses; normalize owner whitespace and country casing.
- Keep display values separate from matching keys. Compare names/emails without case differences, retain all phone digits including any supplied country code, and normalize company punctuation and whitespace.
- Accept `YYYY-MM-DD`, `M/D/YYYY`, and ISO UTC timestamps. Treat date-only values as UTC midnight by convention; leave missing modification dates null and serialize API timestamps with `Z`.
- Preserve original record IDs and allow repeated emails/phones so seed duplicates remain available for review.

An empty leads table imports all seed records in one transaction. A nonempty table is not reimported on restart; only missing derived source fields are backfilled.

### Duplicate Detection

**Blocking + RapidFuzz fuzzy matching** handles spelling differences, initials, and contact formatting with explainable rules.

First, blocking narrows the search to pairs sharing a normalized email, phone, email domain, or company. Then the scorer compares contact evidence, name/company similarity, and email local parts. On the supplied seed, this evaluates **5,047 candidate pairs instead of 2,098,176 possible pairs**.

Shared company/domain alone is insufficient. Missing values do not count as agreement, and incompatible fully spelled given names guard against mistaking different people for one contact.

Results are pairs ranked by descending score, with lead IDs breaking ties. Each includes a confidence band and supporting or conflicting evidence; `total_matches` counts qualifying pairs before the response limit. Scores are review heuristics, not calibrated probabilities. The endpoint never merges records.

### Website Intake and Conflicts

The intake endpoint uses the same matching logic to decide whether a submission belongs to an existing contact:

| Situation | Response |
| --- | --- |
| No supported match, and no unresolved exact-contact conflict | `201`, `action: "created"` |
| One clearly supported existing identity | `200`, `action: "updated"` |
| Multiple plausible identities, conflicting contact details, or a fuzzy-only likely match | `409`, with a conflict code and candidate evidence |

Conflict codes are `ambiguous_match` or `conflicting_identity`. These cases require human resolution.

Updates preserve established contact details, owner, status, and creation data. Distinct messages are appended to Notes while preserving formatting. Replaying the same submission does not add another lead, repeat the message, or change timestamps.

### Source Extraction

**Deterministic rules and regular expressions** recognize recurring patterns in the supplied Notes. This makes results reproducible, inspectable, and inexpensive; unfamiliar wording remains a limitation.

The output contains a `channel` and evidence-based `detail`. Allowed channels are **Website, Event, LinkedIn, Organic Search, Referral, Manual/Sales, and Other**.

Notes provide the evidence because the CRM's Original Source label can be blank or too generic. The original label is retained for context. Rules recognize event encounters, referrals, LinkedIn interactions, organic Google discovery, website forms, and sales contact.

Key decisions:

- Preserve stated event years and distinguish QR scans from explicit scan negation. Expand the observed `SFF` alias to `Singapore FinTech Festival`; do not infer a year.
- Bound event and referral details to the relevant clause or sentence. Include LinkedIn message direction only when explicitly stated.
- Map paid Google advertising and unnamed social posts to `Other`. Without evidence, return `Other` with `Source unspecified`.
- For two distinct sources with a supported explicit `then`, `before`, or `after` ordering, select the original acquisition. Otherwise, acquisition evidence takes priority over website-form transport; competing non-Website channels return an ambiguous `Other` result.
- Exclude operational sales updates and duplicate warnings from extracted detail while preserving the original Notes.

Import derives sources immediately. Replacing or clearing Notes through PATCH recomputes the source. New website submissions use explicit message evidence, falling back to Website when none is available. Generic follow-ups preserve established acquisition evidence.

**LLM usage and cost:** the application calls no LLM and uses no local or mocked language model. No runtime model provider or API key is required; LLM API cost is **$0**. The assignment explicitly permits fuzzy matching and rules/regex.

## Tests

Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

macOS or Linux:

```bash
.venv/bin/python -m pytest -q
```

Tests use temporary SQLite databases and cover:

- Filtering, search, PATCH validation, pagination, and CSV export.
- Duplicate positives, similar-looking different people, missing evidence, and matching thresholds.
- Website intake creation, updates, conflicting identities, and repeated submissions.
- Source ambiguity, chronology, negation, and source changes after Notes updates.
- Import rollback, restart persistence, and dashboard counts after writes.

## Optional Configuration

Defaults are the repository's `leads.db` and `data/leads_seed.csv`. To override them, set `DATABASE_URL` and `SEED_DATA_PATH` before starting the server.

PowerShell example; replace these paths and create the database's parent directory first:

```powershell
$env:DATABASE_URL = "sqlite:///C:/temp/wiz-leads.db"
$env:SEED_DATA_PATH = "C:/path/to/leads_seed.csv"
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

## Limitations and Scope

- Matching can miss duplicates when all blocking keys change. Scores have not been calibrated against a labeled dataset, and comparison rules are ASCII-oriented despite preserving Unicode display values.
- Ambiguous submissions need human review; no merge or conflict-resolution endpoint is included.
- Replay protection handles repeated lead/message submissions, but is not an exactly-once delivery guarantee.
- Source extraction covers the supplied text patterns, not general language understanding or independently verified attribution.
- Dashboard counts represent stored records, including duplicates, rather than unique people. All supported categories are included, even with zero counts.
- Authentication, analytics integrations, webhook infrastructure, audit-history UI, HubSpot migration tooling, and production deployment/scaling/monitoring are excluded to keep the take-home focused. A custom frontend is also omitted; Swagger UI supports local review.

## Next Steps

With more time, I would first validate matching thresholds against a labeled review set and add a human conflict-resolution workflow. Database migrations and stronger constraints would follow. Authentication and production observability would be added when deployment requirements justify them.
