from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"


def test_dashboard_reconciles_before_and_after_writes(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'dashboard.db').as_posix()}", SEED_PATH)
    with TestClient(app) as client:
        initial = client.get("/dashboard")
        patched = client.patch(
            "/leads/100234811",
            json={
                "status": "Qualified",
                "notes": "LinkedIn DM inbound asking about pricing.",
            },
        )
        payload = {
            "name": "Dashboard Verification",
            "email": "dashboard@new-example.test",
            "phone": "+1 212 555 0197",
            "company": "Dashboard Example",
            "country": "United States",
            "form_id": "dashboard-form",
            "form_name": "Book a Demo",
            "page_url": "/book-a-demo",
            "submitted_at": "2026-09-07T05:00:00Z",
            "message": "Filled out the form on the book-a-demo page.",
        }
        ingested = client.post("/leads/ingest", json=payload)
        changed = client.get("/dashboard")

    assert initial.status_code == 200
    assert initial.json() == {
        "total": 2049,
        "by_status": {
            "New": 270,
            "Contacted": 282,
            "Connected": 293,
            "Qualified": 321,
            "Opportunity": 291,
            "Closed Won": 276,
            "Closed Lost": 316,
        },
        "by_source_channel": {
            "Website": 388,
            "Event": 374,
            "LinkedIn": 186,
            "Organic Search": 311,
            "Referral": 241,
            "Manual/Sales": 186,
            "Other": 363,
        },
    }
    assert patched.status_code == 200
    assert ingested.status_code == 201

    result = changed.json()
    assert result["total"] == 2050
    assert result["by_status"]["New"] == 270
    assert result["by_status"]["Qualified"] == 322
    assert result["by_source_channel"]["Event"] == 373
    assert result["by_source_channel"]["LinkedIn"] == 187
    assert result["by_source_channel"]["Website"] == 389
    assert sum(result["by_status"].values()) == result["total"]
    assert sum(result["by_source_channel"].values()) == result["total"]
