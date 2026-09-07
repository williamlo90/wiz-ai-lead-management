from typing import get_args

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.database import get_session
from app.models import Lead
from app.normalization import STATUSES
from app.schemas import DashboardResponse, SourceChannel


router = APIRouter(tags=["dashboard"])


def _grouped_counts(
    session: Session, field: InstrumentedAttribute[str | None]
) -> dict[str, int]:
    rows = session.execute(select(field, func.count()).group_by(field)).all()
    return {str(value): count for value, count in rows if value is not None}


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    total = session.scalar(select(func.count()).select_from(Lead)) or 0
    stored_statuses = _grouped_counts(session, Lead.status)
    stored_sources = _grouped_counts(session, Lead.source_channel)

    return DashboardResponse(
        total=total,
        by_status={status: stored_statuses.get(status, 0) for status in STATUSES.values()},
        by_source_channel={
            channel: stored_sources.get(channel, 0) for channel in get_args(SourceChannel)
        },
    )
