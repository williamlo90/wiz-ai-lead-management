# Wiz AI Lead Management

Small FastAPI service for importing and managing the supplied CRM-style lead dataset. The current implementation includes persistent SQLite storage, normalized seed import, lead listing/filtering/search, lead detail and updates, filtered CSV export, and explainable duplicate candidates.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Run the service:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API documentation. On first startup, the application creates `leads.db` and imports all 2,049 rows from `data/leads_seed.csv`. A nonempty database is left unchanged on restart.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Available API

- `GET /health`
- `GET /leads?status=&owner=&country=&q=&limit=&offset=`
- `GET /leads/export` with the same filters and search
- `POST /leads/dedupe-candidates`
- `GET /leads/{id}`
- `PATCH /leads/{id}` with status, owner, and/or notes

Filters combine with AND. Search is a case-insensitive literal substring across name, company, and email. Export returns the complete filtered view rather than one paginated list page.

Configuration can override the defaults with `DATABASE_URL` and `SEED_DATA_PATH`. SQLite and synchronous SQLAlchemy keep the local take-home setup small and persistent.

## Duplicate Candidates

The deduplication endpoint first blocks records on normalized email, phone, email domain, or company, then applies explainable RapidFuzz name/company rules. On the supplied seed this evaluates 5,047 candidate pairs instead of all 2,098,176 possible pairs. Results contain a heuristic score, confidence band, and evidence such as matching normalized contact details or conflicting names.

Scores are conservative decision rules, not calibrated probabilities. Similar company/domain values alone cannot produce a match, missing fields do not count as agreement, and incompatible fully spelled given names prevent false positives. The endpoint is read-only and does not merge records.

Website-form ingestion behavior, source extraction, and the optional dashboard are planned milestones and are not currently exposed as endpoints.
