import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.models import Lead
from app.schemas import WebsiteSubmission


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"
SUBMISSIONS_PATH = PROJECT_ROOT / "data" / "website_form_submissions.json"


@pytest.fixture
def app_client(tmp_path: Path):
    database_path = tmp_path / "api.db"
    app = create_app(f"sqlite:///{database_path.as_posix()}", SEED_PATH)
    with TestClient(app) as client:
        yield app, client


def test_list_combines_filters_search_and_pagination(app_client) -> None:
    _, client = app_client

    response = client.get(
        "/leads",
        params={
            "status": " new ",
            "owner": "marcus wong",
            "country": "CHINA",
            "q": "Singh Logistics",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["items"][0]["id"] == 100234811
    assert body["items"][0]["created_at"] == "2025-12-21T00:00:00Z"

    beyond_result = client.get("/leads", params={"q": "Acme", "limit": 1, "offset": 999})
    assert beyond_result.status_code == 200
    assert beyond_result.json()["total"] > 1
    assert beyond_result.json()["items"] == []


@pytest.mark.parametrize("query", ["%", "_"])
def test_search_treats_sql_wildcards_as_literals(app_client, query: str) -> None:
    _, client = app_client

    response = client.get("/leads", params={"q": query})

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_detail_and_patch_validation_preserve_state_on_failure(app_client) -> None:
    app, client = app_client
    lead_id = 100234811
    with app.state.database.session_factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        lead.source_channel = "Event"
        lead.source_detail = "Existing source"
        session.commit()

    response = client.patch(
        f"/leads/{lead_id}",
        json={
            "status": " qualified ",
            "owner": "  ",
            "notes": "  First line.\n\nSecond  line.  ",
        },
    )

    assert response.status_code == 200
    changed = response.json()
    assert changed["status"] == "Qualified"
    assert changed["owner"] is None
    assert changed["notes"] == "First line.\n\nSecond  line."
    assert changed["source_channel"] == "Other"
    assert changed["source_detail"] == "Source unspecified"
    assert changed["updated_at"].endswith("Z")

    for payload in ({}, {"status": None}, {"status": "invalid"}, {"email": "new@example.com"}):
        invalid = client.patch(f"/leads/{lead_id}", json=payload)
        assert invalid.status_code == 422

    after_failures = client.get(f"/leads/{lead_id}")
    assert after_failures.status_code == 200
    assert after_failures.json() == changed
    assert client.get("/leads/999999999").status_code == 404
    assert client.get("/leads/0").status_code == 422


def test_export_matches_unpaginated_filtered_view_and_quotes_fields(app_client) -> None:
    _, client = app_client
    email = "y.aina@singhlogistics.io"
    notes = 'Asked for "pricing", then wrote:\ncall tomorrow'
    patch = client.patch("/leads/100234811", json={"notes": notes})
    assert patch.status_code == 200

    listed = client.get("/leads", params={"q": email, "limit": 1})
    exported = client.get("/leads/export", params={"q": email})

    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.headers["content-disposition"] == 'attachment; filename="leads.csv"'
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == listed.json()["total"] == 1
    assert int(rows[0]["id"]) == listed.json()["items"][0]["id"]
    assert rows[0]["notes"] == notes
    assert rows[0]["created_at"] == "2025-12-21T00:00:00Z"
    assert "email_key" not in rows[0]
    assert "form_metadata" not in rows[0]

    paginated = client.get("/leads", params={"q": "Acme", "limit": 1}).json()
    complete_export = client.get("/leads/export", params={"q": "Acme"})
    complete_rows = list(csv.DictReader(io.StringIO(complete_export.text)))
    assert len(complete_rows) == paginated["total"] > len(paginated["items"])
    assert [int(row["id"]) for row in complete_rows] == sorted(
        int(row["id"]) for row in complete_rows
    )


def test_export_returns_header_for_no_matches(app_client) -> None:
    _, client = app_client

    response = client.get("/leads/export", params={"q": "value-not-in-the-seed"})

    assert response.status_code == 200
    assert len(list(csv.reader(io.StringIO(response.text)))) == 1


def test_website_submission_schema_accepts_all_examples() -> None:
    submissions = json.loads(SUBMISSIONS_PATH.read_text(encoding="utf-8"))

    parsed = [WebsiteSubmission.model_validate(item) for item in submissions]

    assert len(parsed) == 90
    assert all(item.submitted_at.utcoffset().total_seconds() == 0 for item in parsed)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "invalid-email"),
        ("email", "first@second@example.com"),
        ("phone", "no digits"),
        ("page_url", "ftp://example.com/page"),
        ("page_url", "//example.com/page"),
        ("submitted_at", "2026-01-01T12:00:00"),
        ("name", "   "),
    ],
)
def test_website_submission_schema_rejects_invalid_values(field: str, value: str) -> None:
    valid = {
        "form_id": "form_demo_request",
        "form_name": "Book a Demo",
        "page_url": "/book-a-demo",
        "submitted_at": "2026-01-01T12:00:00Z",
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 212 555 0100",
        "company": "Example Inc.",
        "country": "United States",
        "message": None,
    }
    valid[field] = value

    with pytest.raises(ValidationError):
        WebsiteSubmission.model_validate(valid)


def test_website_submission_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        WebsiteSubmission.model_validate(
            {
                "form_id": "form_demo_request",
                "form_name": "Book a Demo",
                "page_url": "https://example.com/book-a-demo",
                "submitted_at": "2026-01-01T12:00:00+07:00",
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "phone": "+1 212 555 0100",
                "company": "Example Inc.",
                "country": "United States",
                "message": "Hello",
                "status": "New",
            }
        )
