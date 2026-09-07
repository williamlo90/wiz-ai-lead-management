# Wiz AI Lead Management

Small FastAPI service for importing and managing the supplied CRM-style lead dataset. The current implementation includes persistent SQLite storage, normalized seed import, lead listing/filtering/search, lead detail and updates, and filtered CSV export.

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
- `GET /leads/{id}`
- `PATCH /leads/{id}` with status, owner, and/or notes

Filters combine with AND. Search is a case-insensitive literal substring across name, company, and email. Export returns the complete filtered view rather than one paginated list page.

Configuration can override the defaults with `DATABASE_URL` and `SEED_DATA_PATH`. SQLite and synchronous SQLAlchemy keep the local take-home setup small and persistent.

Deduplication, website-form ingestion behavior, source extraction, and the optional dashboard are planned milestones and are not currently exposed as endpoints.
