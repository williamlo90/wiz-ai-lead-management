import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Lead
from app.normalization import as_utc, normalize_status
from app.schemas import LeadListResponse, LeadRead, LeadUpdate
from app.source_extraction import extract_source


router = APIRouter(prefix="/leads", tags=["leads"])

EXPORT_FIELDS = (
    "id",
    "name",
    "company",
    "email",
    "phone",
    "country",
    "status",
    "owner",
    "notes",
    "created_at",
    "updated_at",
    "original_source",
    "source_channel",
    "source_detail",
)


def normalize_query(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def lead_query(
    *,
    status: str | None,
    owner: str | None,
    country: str | None,
    q: str | None,
) -> Select[tuple[Lead]]:
    statement = select(Lead)
    if status:
        try:
            canonical_status = normalize_status(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        statement = statement.where(Lead.status == canonical_status)
    if owner:
        statement = statement.where(func.lower(Lead.owner) == owner.casefold())
    if country:
        statement = statement.where(func.lower(Lead.country) == country.casefold())
    if q:
        pattern = f"%{escape_like(q)}%"
        statement = statement.where(
            or_(
                Lead.name.ilike(pattern, escape="\\"),
                Lead.company.ilike(pattern, escape="\\"),
                Lead.email.ilike(pattern, escape="\\"),
            )
        )
    return statement


def utc_string(value: datetime | None) -> str:
    utc_value = as_utc(value)
    return utc_value.isoformat().replace("+00:00", "Z") if utc_value else ""


@router.get("", response_model=LeadListResponse)
def list_leads(
    status: str | None = None,
    owner: str | None = None,
    country: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> LeadListResponse:
    filters = {
        "status": normalize_query(status),
        "owner": normalize_query(owner),
        "country": normalize_query(country),
        "q": normalize_query(q),
    }
    statement = lead_query(**filters)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    leads = session.scalars(statement.order_by(Lead.id).limit(limit).offset(offset)).all()
    return LeadListResponse(items=list(leads), total=total, limit=limit, offset=offset)


@router.get("/export")
def export_leads(
    status: str | None = None,
    owner: str | None = None,
    country: str | None = None,
    q: str | None = None,
    session: Session = Depends(get_session),
) -> Response:
    statement = lead_query(
        status=normalize_query(status),
        owner=normalize_query(owner),
        country=normalize_query(country),
        q=normalize_query(q),
    )
    leads = session.scalars(statement.order_by(Lead.id)).all()

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(EXPORT_FIELDS)
    for lead in leads:
        writer.writerow(
            (
                lead.id,
                lead.name,
                lead.company,
                lead.email,
                lead.phone,
                lead.country,
                lead.status,
                lead.owner or "",
                lead.notes or "",
                utc_string(lead.created_at),
                utc_string(lead.updated_at),
                lead.original_source or "",
                lead.source_channel or "",
                lead.source_detail or "",
            )
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(
    lead_id: int = Path(gt=0),
    session: Session = Depends(get_session),
) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(
    update: LeadUpdate,
    lead_id: int = Path(gt=0),
    session: Session = Depends(get_session),
) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    changed = False
    notes_changed = False
    values = update.model_dump(exclude_unset=True)
    for field in ("status", "owner", "notes"):
        if field in values and getattr(lead, field) != values[field]:
            setattr(lead, field, values[field])
            changed = True
            notes_changed = notes_changed or field == "notes"

    if notes_changed:
        source = extract_source(lead.notes)
        lead.source_channel = source.channel
        lead.source_detail = source.detail
    if changed:
        lead.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(lead)
    return lead
