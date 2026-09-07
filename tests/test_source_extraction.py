import csv
import io
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import Lead
from app.source_extraction import extract_source


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"


@pytest.mark.parametrize(
    ("text", "channel", "detail"),
    [
        (
            "Met her at the SFF booth, scanned our QR code.",
            "Event",
            "Singapore FinTech Festival - Booth QR Code",
        ),
        (
            "Spoke at our Web Summit 2026 booth, no QR scan logged. No response yet.",
            "Event",
            "Web Summit 2026 - Booth conversation; no QR scan logged",
        ),
        ("Referred by Aiko Diop, warm intro.", "Referral", "Referred by Aiko Diop"),
        (
            "Linkedin dm inbound asking about pricing.",
            "LinkedIn",
            "LinkedIn DM inbound; pricing inquiry",
        ),
        (
            "Found us through organic google search then landed on the pricing page.",
            "Organic Search",
            "Google organic search - pricing page",
        ),
        (
            "Booked a demo via the book-a-demo page after clicking a google ad.",
            "Other",
            "Paid Google advertising - book-a-demo page",
        ),
        (
            "Saw our post about replacing hubspot and commented.",
            "Other",
            "Social post interaction; platform unspecified",
        ),
        (
            "Filled out the form on the product tour page.",
            "Website",
            "Form submission - product tour page",
        ),
        ("Manual - added after inbound phone call.", "Manual/Sales", "Inbound phone call"),
        ("Other - walked into our office.", "Other", "Walk-in contact"),
        ("Other - reached out via our general info@ inbox.", "Other", "General info@ inbox"),
        ("No acquisition evidence here.", "Other", "Source unspecified"),
        (
            "Referred by Aiko Diop. Manual - added after inbound phone call.",
            "Other",
            "Ambiguous source: Referral, Manual/Sales",
        ),
    ],
)
def test_extract_source_rules(text: str, channel: str, detail: str) -> None:
    assert extract_source(text).channel == channel
    assert extract_source(text).detail == detail


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        (
            "Met her at the Web Summit 2026 booth, she has not scanned our QR code.",
            "Web Summit 2026 - Booth conversation; QR scan explicitly negated",
        ),
        (
            "Met her at the Web Summit 2026 booth and did not scan our QR code.",
            "Web Summit 2026 - Booth conversation; QR scan explicitly negated",
        ),
        (
            "Met her at the Web Summit 2026 booth. "
            "Scanned our QR code in the office a week later.",
            "Web Summit 2026 - Booth conversation",
        ),
        (
            "Met her at the Web Summit 2026 booth, but scanned our QR code "
            "in the office a week later.",
            "Web Summit 2026 - Booth conversation",
        ),
    ],
)
def test_event_details_use_only_the_event_sentence(text: str, detail: str) -> None:
    result = extract_source(text)

    assert result.channel == "Event"
    assert result.detail == detail


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("Sent a LinkedIn DM asking about pricing.", "LinkedIn DM; pricing inquiry"),
        (
            "Received an email. Sent a LinkedIn DM asking about pricing.",
            "LinkedIn DM; pricing inquiry",
        ),
        (
            "Received a LinkedIn DM asking about pricing.",
            "LinkedIn DM inbound; pricing inquiry",
        ),
        (
            "Referred by Mary Jane van Doe, warm intro.",
            "Referred by Mary Jane van Doe",
        ),
        (
            "Referred by Aiko Diop\n\nConnected, sending proposal.",
            "Referred by Aiko Diop",
        ),
        (
            "Referred by Aiko Diop before connecting on LinkedIn.",
            "Referred by Aiko Diop",
        ),
    ],
)
def test_person_and_direction_details_require_explicit_evidence(
    text: str, detail: str
) -> None:
    assert extract_source(text).detail == detail


@pytest.mark.parametrize(
    ("text", "channel", "detail"),
    [
        (
            "Referred by Aiko Diop, then connected on LinkedIn.",
            "Referral",
            "Referred by Aiko Diop",
        ),
        (
            "Connected on LinkedIn, then referred by Aiko Diop.",
            "LinkedIn",
            "LinkedIn interaction",
        ),
        (
            "Filled out the form on the homepage before meeting us at the "
            "SaaStr Annual booth.",
            "Website",
            "Form submission - homepage",
        ),
        (
            "Met us at the SaaStr Annual booth before filling out the form on "
            "the homepage.",
            "Event",
            "SaaStr Annual - Booth conversation",
        ),
        (
            "Met us at the SaaStr Annual booth after filling out the form on "
            "the homepage.",
            "Website",
            "Form submission - homepage",
        ),
        (
            "Filled out the form on the homepage after meeting us at the "
            "SaaStr Annual booth.",
            "Event",
            "SaaStr Annual - Booth conversation",
        ),
        (
            "After filling out the form on the homepage, met us at the "
            "SaaStr Annual booth.",
            "Website",
            "Form submission - homepage",
        ),
        (
            "Before filling out the form on the homepage, met us at the "
            "SaaStr Annual booth.",
            "Event",
            "SaaStr Annual - Booth conversation",
        ),
        (
            "Found us through organic Google search then filled out the form on "
            "the pricing page.",
            "Organic Search",
            "Google organic search",
        ),
        (
            "Met us at the SaaStr Annual booth and filled out the form on the "
            "homepage.",
            "Event",
            "SaaStr Annual - Booth conversation",
        ),
    ],
)
def test_explicit_journey_order_selects_original_acquisition(
    text: str, channel: str, detail: str
) -> None:
    result = extract_source(text)

    assert result.channel == channel
    assert result.detail == detail


def test_extract_source_endpoint_validation_and_operational_suffixes(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'source.db').as_posix()}", SEED_PATH)
    with TestClient(app) as client:
        response = client.post(
            "/leads/extract-source",
            json={
                "text": "Referred by Elena Han, warm intro. Connected, sending proposal. "
                "possible duplicate - verify before contacting."
            },
        )
        blank = client.post("/leads/extract-source", json={"text": "  "})
        invalid = client.post("/leads/extract-source", json={"text": None})
        negated_scan = client.post(
            "/leads/extract-source",
            json={
                "text": "Met at the Web Summit 2026 booth; "
                "she has not scanned our QR code."
            },
        )
        ordered_journey = client.post(
            "/leads/extract-source",
            json={"text": "Referred by Elena Han, then connected on LinkedIn."},
        )

    assert response.status_code == 200
    assert response.json() == {
        "channel": "Referral",
        "detail": "Referred by Elena Han",
    }
    assert blank.json() == {"channel": "Other", "detail": "Source unspecified"}
    assert invalid.status_code == 422
    assert negated_scan.json() == {
        "channel": "Event",
        "detail": "Web Summit 2026 - Booth conversation; QR scan explicitly negated",
    }
    assert ordered_journey.json() == {
        "channel": "Referral",
        "detail": "Referred by Elena Han",
    }


def test_fresh_import_extracts_all_seed_sources(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}", SEED_PATH)
    with TestClient(app):
        with app.state.database.session_factory() as session:
            sources = Counter(session.scalars(select(Lead.source_channel)))
            missing_details = session.scalars(
                select(Lead.id).where(Lead.source_detail.is_(None))
            ).all()
            unspecified = session.scalars(
                select(Lead.id).where(Lead.source_detail == "Source unspecified")
            ).all()

    assert sources == {
        "Event": 374,
        "Referral": 241,
        "Website": 388,
        "Other": 363,
        "Organic Search": 311,
        "Manual/Sales": 186,
        "LinkedIn": 186,
    }
    assert missing_details == []
    assert unspecified == []


def test_restart_backfills_only_missing_source_fields(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'backfill.db').as_posix()}"
    app = create_app(database_url, SEED_PATH)
    with TestClient(app):
        with app.state.database.session_factory() as session:
            first = session.get(Lead, 100234811)
            second = session.get(Lead, 100234812)
            assert first is not None and second is not None
            first.status = "Qualified"
            first.source_channel = None
            first.source_detail = None
            second.source_detail = "Keep this populated detail"
            second.source_channel = None
            session.commit()

    restarted = create_app(database_url, SEED_PATH)
    with TestClient(restarted):
        with restarted.state.database.session_factory() as session:
            first = session.get(Lead, 100234811)
            second = session.get(Lead, 100234812)

    assert first is not None and second is not None
    assert first.status == "Qualified"
    assert first.source_channel == "Event"
    assert first.source_detail == "SaaStr Annual - Booth QR Code"
    assert second.source_channel is not None
    assert second.source_detail == "Keep this populated detail"


def test_ingest_refines_website_fallback_with_explicit_evidence(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'ingest-source.db').as_posix()}", SEED_PATH)
    payload = {
        "name": "Nora Example",
        "email": "nora@new-example.test",
        "phone": "+62 812 555 0199",
        "company": "New Example Labs",
        "country": "Indonesia",
        "form_id": "demo-request",
        "form_name": "Demo Request",
        "page_url": "/request-demo",
        "submitted_at": "2026-07-01T05:00:00Z",
        "message": "Please send product information.",
    }
    with TestClient(app) as client:
        created = client.post("/leads/ingest", json=payload)
        payload["submitted_at"] = "2026-07-02T05:00:00Z"
        payload["message"] = "Referred by Aiko Diop, warm intro."
        updated = client.post("/leads/ingest", json=payload)

    assert created.status_code == 201
    assert created.json()["lead"]["source_channel"] == "Website"
    assert updated.status_code == 200
    assert updated.json()["lead"]["source_channel"] == "Referral"
    assert updated.json()["lead"]["source_detail"] == "Referred by Aiko Diop"


def test_patch_recomputes_and_clears_source_immediately(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'patch-source.db').as_posix()}", SEED_PATH)
    with TestClient(app) as client:
        changed = client.patch(
            "/leads/100234811",
            json={"notes": "LinkedIn DM inbound asking about pricing."},
        )
        cleared = client.patch("/leads/100234811", json={"notes": None})

    assert changed.status_code == cleared.status_code == 200
    assert changed.json()["source_channel"] == "LinkedIn"
    assert changed.json()["source_detail"] == "LinkedIn DM inbound; pricing inquiry"
    assert cleared.json()["source_channel"] == "Other"
    assert cleared.json()["source_detail"] == "Source unspecified"


def test_patch_persists_grounded_source_without_changing_notes(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'grounded.db').as_posix()}", SEED_PATH)
    notes = "Met her at the Web Summit 2026 booth, she has not scanned our QR code."

    with TestClient(app) as client:
        response = client.patch("/leads/100234811", json={"notes": notes})
        with app.state.database.session_factory() as session:
            stored = session.get(Lead, 100234811)

    assert response.status_code == 200
    assert response.json()["source_channel"] == "Event"
    assert response.json()["source_detail"] == (
        "Web Summit 2026 - Booth conversation; QR scan explicitly negated"
    )
    assert stored is not None
    assert stored.notes == notes


@pytest.mark.parametrize(
    ("notes", "channel", "detail"),
    [
        (
            "Connected on LinkedIn, then referred by Aiko Diop.",
            "LinkedIn",
            "LinkedIn interaction",
        ),
        (
            "After filling out the form on the homepage, met us at the "
            "SaaStr Annual booth.",
            "Website",
            "Form submission - homepage",
        ),
        (
            "Referred by Aiko Diop before connecting on LinkedIn.",
            "Referral",
            "Referred by Aiko Diop",
        ),
    ],
)
def test_patch_persists_original_source_from_ordered_journey(
    tmp_path: Path, notes: str, channel: str, detail: str
) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'ordered.db').as_posix()}", SEED_PATH)

    with TestClient(app) as client:
        response = client.patch("/leads/100234811", json={"notes": notes})
        with app.state.database.session_factory() as session:
            stored = session.get(Lead, 100234811)

    assert response.status_code == 200
    assert response.json()["source_channel"] == channel
    assert response.json()["source_detail"] == detail
    assert stored is not None
    assert stored.notes == notes
    assert stored.source_channel == channel


@pytest.mark.parametrize(
    ("message", "patched_notes", "expected_notes"),
    [
        (None, None, None),
        (None, " \n ", None),
        ("Hello", "Hello", "Hello"),
    ],
)
def test_explicit_notes_patch_replaces_website_fallback_and_survives_restart(
    tmp_path: Path,
    message: str | None,
    patched_notes: str | None,
    expected_notes: str | None,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'notes-replacement.db').as_posix()}"
    app = create_app(database_url, SEED_PATH)
    payload = {
        "name": "Patch Source Example",
        "email": "patch-source@example-new.test",
        "phone": "+62 812 555 0200",
        "company": "Patch Source Labs",
        "country": "Indonesia",
        "form_id": "demo-request",
        "form_name": "Demo Request",
        "page_url": "/request-demo",
        "submitted_at": "2026-07-01T05:00:00Z",
        "message": message,
    }

    with TestClient(app) as client:
        created = client.post("/leads/ingest", json=payload)
        assert created.status_code == 201
        created_lead = created.json()["lead"]
        lead_id = created_lead["id"]
        assert created_lead["source_channel"] == "Website"
        assert created_lead["updated_at"] is None

        patched = client.patch(
            f"/leads/{lead_id}", json={"notes": patched_notes}
        )
        replay = client.patch(
            f"/leads/{lead_id}", json={"notes": patched_notes}
        )
        status_only = client.patch(
            f"/leads/{lead_id}", json={"status": "Contacted"}
        )

    assert patched.status_code == replay.status_code == status_only.status_code == 200
    patched_lead = patched.json()
    assert patched_lead["notes"] == expected_notes
    assert patched_lead["source_channel"] == "Other"
    assert patched_lead["source_detail"] == "Source unspecified"
    assert patched_lead["updated_at"] is not None
    assert replay.json()["updated_at"] == patched_lead["updated_at"]
    assert status_only.json()["source_channel"] == "Other"
    assert status_only.json()["source_detail"] == "Source unspecified"
    for field in (
        "name",
        "company",
        "email",
        "phone",
        "country",
        "created_at",
        "original_source",
        "form_metadata",
    ):
        assert patched_lead[field] == created_lead[field]

    restarted = create_app(database_url, SEED_PATH)
    with TestClient(restarted) as client:
        persisted = client.get(f"/leads/{lead_id}")
        listed = client.get("/leads", params={"q": payload["email"]})
        exported = client.get("/leads/export", params={"q": payload["email"]})
        dashboard = client.get("/dashboard")

    assert persisted.status_code == 200
    assert persisted.json()["source_channel"] == "Other"
    assert persisted.json()["source_detail"] == "Source unspecified"
    assert listed.status_code == exported.status_code == dashboard.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["source_channel"] == "Other"
    export_rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(export_rows) == 1
    assert export_rows[0]["source_channel"] == "Other"
    assert export_rows[0]["source_detail"] == "Source unspecified"
    dashboard_body = dashboard.json()
    assert sum(dashboard_body["by_source_channel"].values()) == dashboard_body["total"]
    assert dashboard_body["by_source_channel"]["Other"] >= 1
