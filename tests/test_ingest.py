from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Lead
from app.normalization import (
    email_domain,
    normalize_company,
    normalize_email,
    normalize_name,
    normalize_phone,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"


def build_test_app(tmp_path: Path):
    database_path = tmp_path / "ingest.db"
    return create_app(f"sqlite:///{database_path.as_posix()}", SEED_PATH)


def submission(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Nora Example",
        "email": "nora@example-new.test",
        "phone": "+62 812 555 0199",
        "company": "Example New Labs",
        "country": "indonesia",
        "form_id": "demo-request",
        "form_name": "Demo Request",
        "page_url": "/request-demo",
        "submitted_at": "2026-07-01T12:00:00+07:00",
        "message": "Interested in analytics.\n\nPlease call next week.",
    }
    payload.update(overrides)
    return payload


def lead_count(app) -> int:
    with app.state.database.session_factory() as session:
        return session.scalar(select(func.count()).select_from(Lead)) or 0


def test_ingest_creates_a_normalized_new_lead(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/leads/ingest", json=submission())

    assert response.status_code == 201
    body = response.json()
    assert body["action"] == "created"
    assert body["lead"]["id"] > 100236859
    assert body["lead"]["country"] == "Indonesia"
    assert body["lead"]["status"] == "New"
    assert body["lead"]["owner"] is None
    assert body["lead"]["original_source"] is None
    assert body["lead"]["source_channel"] is None
    assert body["lead"]["created_at"] == "2026-07-01T05:00:00Z"
    assert body["lead"]["updated_at"] is None
    assert body["lead"]["notes"] == "Interested in analytics.\n\nPlease call next week."
    assert body["lead"]["form_metadata"] == {
        "form_id": "demo-request",
        "form_name": "Demo Request",
        "page_url": "/request-demo",
        "submitted_at": "2026-07-01T05:00:00Z",
    }
    assert lead_count(app) == 2050


def test_ingest_updates_clear_identity_and_replay_is_a_no_op(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        original = client.get("/leads/100234811").json()
        payload = submission(
            name=original["name"],
            email=original["email"],
            phone=original["phone"],
            company=original["company"],
            country=original["country"],
            message="First line.\n\nSecond line.",
        )

        first = client.post("/leads/ingest", json=payload)
        replay = client.post("/leads/ingest", json=payload)

    assert first.status_code == replay.status_code == 200
    first_lead = first.json()["lead"]
    replay_lead = replay.json()["lead"]
    assert first.json()["action"] == "updated"
    assert first_lead["id"] == 100234811
    assert first_lead["status"] == original["status"]
    assert first_lead["owner"] == original["owner"]
    assert first_lead["email"] == original["email"]
    assert first_lead["phone"] == original["phone"]
    assert first_lead["notes"] == (
        f'{original["notes"].rstrip()}\n\nFirst line.\n\nSecond line.'
    )
    assert first_lead["updated_at"] is not None
    assert replay_lead["notes"] == first_lead["notes"]
    assert replay_lead["updated_at"] == first_lead["updated_at"]
    assert replay_lead["form_metadata"] == first_lead["form_metadata"]
    assert lead_count(app) == 2049


def test_older_submission_keeps_newer_metadata_and_appends_message(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        original = client.get("/leads/100234811").json()
        identity = {
            "name": original["name"],
            "email": original["email"],
            "phone": original["phone"],
            "company": original["company"],
            "country": original["country"],
        }
        newer = client.post(
            "/leads/ingest",
            json=submission(
                **identity,
                message="Newer message",
                submitted_at="2026-07-02T00:00:00Z",
            ),
        )
        older = client.post(
            "/leads/ingest",
            json=submission(
                **identity,
                message="Older message\n\nwith details",
                form_name="Older Form",
                submitted_at="2026-06-01T00:00:00Z",
            ),
        )

    assert newer.status_code == older.status_code == 200
    lead = older.json()["lead"]
    assert lead["notes"].endswith("Newer message\n\nOlder message\n\nwith details")
    assert lead["form_metadata"] == newer.json()["lead"]["form_metadata"]
    assert lead["form_metadata"]["form_name"] == "Demo Request"


def test_ingest_rejects_multiple_exact_matches_without_mutation(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        duplicate = client.get("/leads/100234834").json()
        before = client.get("/leads/100234834").json()
        response = client.post(
            "/leads/ingest",
            json=submission(
                name=duplicate["name"],
                email=duplicate["email"],
                phone=duplicate["phone"],
                company=duplicate["company"],
                country=duplicate["country"],
            ),
        )
        after = client.get("/leads/100234834").json()

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "ambiguous_match"
    assert {candidate["lead_id"] for candidate in detail["candidates"]} >= {
        100234834,
        100234835,
    }
    assert before == after
    assert lead_count(app) == 2049


def test_ingest_rejects_cross_record_identifiers(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        email_lead = client.get("/leads/100234811").json()
        phone_lead = client.get("/leads/100234812").json()
        response = client.post(
            "/leads/ingest",
            json=submission(
                name=email_lead["name"],
                email=email_lead["email"],
                phone=phone_lead["phone"],
                company=email_lead["company"],
                country=email_lead["country"],
            ),
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "conflicting_identity"
    assert {candidate["lead_id"] for candidate in detail["candidates"]} >= {
        100234811,
        100234812,
    }
    assert lead_count(app) == 2049


def test_ingest_rejects_incompatible_name_with_exact_identifiers(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        existing = client.get("/leads/100234811").json()
        response = client.post(
            "/leads/ingest",
            json=submission(
                name="Completely Different",
                email=existing["email"],
                phone=existing["phone"],
                company=existing["company"],
                country=existing["country"],
            ),
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "ambiguous_match"
    assert detail["candidates"][0]["lead_id"] == 100234811
    assert detail["candidates"][0]["score"] == 0.69
    assert "incompatible given names" in detail["candidates"][0]["reasons"]
    assert lead_count(app) == 2049


def test_ingest_rejects_fuzzy_only_likely_match(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    with TestClient(app) as client:
        with app.state.database.session_factory() as session:
            lead = Lead(
                name="Maya Chen",
                email="maya.chen@example.com",
                phone="+1 212 555 0101",
                company="Example Labs",
                country="United States",
                status="New",
                owner=None,
                notes=None,
                created_at=datetime(2026, 1, 1),
                updated_at=None,
                original_source=None,
                source_channel=None,
                source_detail=None,
                name_key=normalize_name("Maya Chen"),
                email_key=normalize_email("maya.chen@example.com"),
                phone_key=normalize_phone("+1 212 555 0101"),
                email_domain=email_domain("maya.chen@example.com"),
                company_key=normalize_company("Example Labs"),
                form_data=None,
            )
            session.add(lead)
            session.commit()

        response = client.post(
            "/leads/ingest",
            json=submission(
                name="Mya Chen",
                email="mya.chen@example.com",
                phone="+1 212 555 0102",
                company="Example Labs",
                country="United States",
            ),
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "ambiguous_match"
    assert detail["candidates"][0]["confidence"] == "likely"
    assert 0.75 <= detail["candidates"][0]["score"] < 0.90
    assert lead_count(app) == 2050
