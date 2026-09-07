import csv
import io
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Lead


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"


def test_integrated_lead_workflow(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'workflow.db').as_posix()}", SEED_PATH)
    with TestClient(app) as client:
        assert client.get("/health").json()["lead_count"] == 2049

        listed = client.get(
            "/leads",
            params={"q": "y.aina@singhlogistics.io", "status": "new"},
        )
        exported = client.get(
            "/leads/export",
            params={"q": "y.aina@singhlogistics.io", "status": "new"},
        )
        export_rows = list(csv.DictReader(io.StringIO(exported.text)))
        assert [item["id"] for item in listed.json()["items"]] == [100234811]
        assert [int(row["id"]) for row in export_rows] == [100234811]

        original = client.get("/leads/100234811").json()
        patched = client.patch(
            "/leads/100234811",
            json={
                "status": "Qualified",
                "notes": "Referred by Aiko Diop, warm intro.",
            },
        )
        assert patched.status_code == 200
        assert patched.json()["source_channel"] == "Referral"

        submission = {
            "name": original["name"],
            "email": original["email"],
            "phone": original["phone"],
            "company": original["company"],
            "country": original["country"],
            "form_id": "integration-form",
            "form_name": "Book a Demo",
            "page_url": "/book-a-demo",
            "submitted_at": "2026-07-01T05:00:00Z",
            "message": "Please send the implementation guide.",
        }
        ingested = client.post("/leads/ingest", json=submission)
        replayed = client.post("/leads/ingest", json=submission)
        assert ingested.status_code == replayed.status_code == 200
        assert ingested.json()["lead"]["status"] == "Qualified"
        assert ingested.json()["lead"]["source_channel"] == "Referral"
        assert replayed.json()["lead"]["notes"] == ingested.json()["lead"]["notes"]
        assert replayed.json()["lead"]["updated_at"] == ingested.json()["lead"]["updated_at"]

        before_conflict = {
            lead_id: client.get(f"/leads/{lead_id}").json()
            for lead_id in (100234811, 100234812)
        }
        second = before_conflict[100234812]
        conflict_payload = submission | {
            "phone": second["phone"],
            "message": "This request must not change either record.",
        }
        conflict = client.post("/leads/ingest", json=conflict_payload)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "conflicting_identity"
        assert {
            lead_id: client.get(f"/leads/{lead_id}").json()
            for lead_id in (100234811, 100234812)
        } == before_conflict
        assert client.get("/health").json()["lead_count"] == 2049

        dedupe = client.post(
            "/leads/dedupe-candidates", json={"min_score": 0.95, "limit": 5}
        )
        extraction = client.post(
            "/leads/extract-source",
            json={"text": "Found us through organic google search then landed on the homepage."},
        )

    assert dedupe.status_code == 200
    assert dedupe.json()["candidate_pairs_evaluated"] == 5047
    assert dedupe.json()["candidates"]
    assert extraction.json() == {
        "channel": "Organic Search",
        "detail": "Google organic search - homepage",
    }


def test_malformed_fresh_seed_rolls_back_all_rows(tmp_path: Path) -> None:
    with SEED_PATH.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = [next(reader), next(reader)]
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    rows[1]["Lead Status"] = "not-a-real-status"

    malformed_seed = tmp_path / "malformed.csv"
    with malformed_seed.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    app = create_app(
        f"sqlite:///{(tmp_path / 'malformed.db').as_posix()}", malformed_seed
    )
    with pytest.raises(ValueError, match="Unknown lead status"):
        with TestClient(app):
            pass

    with app.state.database.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(Lead))
    assert count == 0


def test_normalized_totals_and_real_edit_survive_restart(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'restart.db').as_posix()}"
    app = create_app(database_url, SEED_PATH)
    with TestClient(app) as client:
        with app.state.database.session_factory() as session:
            status_totals = Counter(session.scalars(select(Lead.status)))
            null_modified = session.scalar(
                select(func.count()).select_from(Lead).where(Lead.updated_at.is_(None))
            )

        edited = client.patch(
            "/leads/100234811",
            json={"status": "Qualified", "owner": "Integration Owner"},
        )
        assert edited.status_code == 200

    assert status_totals == {
        "New": 270,
        "Contacted": 282,
        "Connected": 293,
        "Qualified": 321,
        "Opportunity": 291,
        "Closed Won": 276,
        "Closed Lost": 316,
    }
    assert null_modified == 553

    missing_seed = tmp_path / "seed-is-not-needed-on-restart.csv"
    restarted = create_app(database_url, missing_seed)
    with TestClient(restarted) as client:
        persisted = client.get("/leads/100234811")
        health = client.get("/health")

    assert persisted.status_code == 200
    assert persisted.json()["status"] == "Qualified"
    assert persisted.json()["owner"] == "Integration Owner"
    assert persisted.json()["updated_at"] == edited.json()["updated_at"]
    assert health.json()["lead_count"] == 2049
