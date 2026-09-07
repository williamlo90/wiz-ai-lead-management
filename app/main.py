import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.database import Database
from app.dashboard import router as dashboard_router
from app.deduplication import router as deduplication_router
from app.ingest import router as ingest_router
from app.leads import router as leads_router
from app.models import Lead
from app.schemas import HealthResponse
from app.seed import load_seed_data
from app.source_extraction import backfill_missing_sources
from app.source_extraction import router as source_extraction_router


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'leads.db').as_posix()}"
DEFAULT_SEED_PATH = PROJECT_ROOT / "data" / "leads_seed.csv"
STATIC_DIRECTORY = PROJECT_ROOT / "app" / "static"


def create_app(
    database_url: str | None = None,
    seed_path: Path | None = None,
) -> FastAPI:
    database = Database(database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))
    selected_seed_path = seed_path or Path(
        os.getenv("SEED_DATA_PATH", str(DEFAULT_SEED_PATH))
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            database.create_tables()
            with database.session_factory() as session:
                load_seed_data(session, selected_seed_path)
                backfill_missing_sources(session)
            yield
        finally:
            database.engine.dispose()

    app = FastAPI(
        title="Wiz AI Lead Management",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
    )
    app.state.database = database
    app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
    app.include_router(dashboard_router)
    app.include_router(ingest_router)
    app.include_router(deduplication_router)
    app.include_router(source_extraction_router)
    app.include_router(leads_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": "wiz-ai-lead-management"}

    @app.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} - Swagger UI",
            swagger_css_url="/static/swagger-ui.css",
            swagger_favicon_url="/static/favicon.svg",
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        with database.session_factory() as session:
            count = session.scalar(select(func.count()).select_from(Lead)) or 0
        return HealthResponse(status="ok", lead_count=count)

    return app


app = create_app()
