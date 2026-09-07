from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Lead


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"


def build_test_app(tmp_path: Path):
    database_path = tmp_path / "test.db"
    return create_app(f"sqlite:///{database_path.as_posix()}", SEED_PATH)


def test_app_loads_seed_and_reports_health(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "lead_count": 2049}


def test_seed_is_idempotent_and_normalized(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)

    with TestClient(app):
        pass
    with TestClient(app):
        pass

    database = app.state.database
    with database.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(Lead))
        first = session.get(Lead, 100234811)
        full_name_only = session.get(Lead, 100234835)
        statuses = set(session.scalars(select(Lead.status)))

    assert count == 2049
    assert first is not None
    assert first.owner == "Marcus Wong"
    assert first.phone_key == "8613824247912"
    assert first.created_at.isoformat() == "2025-12-21T00:00:00"
    assert full_name_only is not None
    assert full_name_only.name == "J. Diallo"
    assert statuses == {
        "New",
        "Contacted",
        "Connected",
        "Qualified",
        "Opportunity",
        "Closed Won",
        "Closed Lost",
    }


def test_openapi_contains_milestone_two_endpoints(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert set(schema["paths"]) == {
        "/dashboard",
        "/health",
        "/leads",
        "/leads/dedupe-candidates",
        "/leads/extract-source",
        "/leads/export",
        "/leads/ingest",
        "/leads/{lead_id}",
    }
    assert "201" in schema["paths"]["/leads/ingest"]["post"]["responses"]


def test_swagger_ui_uses_local_favicon(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        favicon_response = client.get("/static/favicon.svg")
        stylesheet_response = client.get("/static/swagger-ui.css")

    assert docs_response.status_code == 200
    assert 'href="/static/favicon.svg"' in docs_response.text
    assert "fastapi.tiangolo.com/img/favicon.png" not in docs_response.text
    assert favicon_response.status_code == 200
    assert favicon_response.headers["content-type"].startswith("image/svg+xml")
    assert stylesheet_response.status_code == 200
    assert ".view-line-link.copy-to-clipboard" in stylesheet_response.text
    assert "display: none" in stylesheet_response.text
