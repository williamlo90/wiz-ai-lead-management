from datetime import datetime, timezone
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.deduplication import BLOCK_FIELDS, DuplicateAssessment, score_candidate
from app.models import Lead
from app.normalization import (
    as_utc,
    email_domain,
    normalize_company,
    normalize_country,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from app.schemas import IngestResponse, WebsiteSubmission


router = APIRouter(prefix="/leads", tags=["leads"])


def _utc_string(value: datetime) -> str:
    utc_value = as_utc(value)
    assert utc_value is not None
    return utc_value.isoformat().replace("+00:00", "Z")


def _submission_values(submission: WebsiteSubmission) -> dict[str, object]:
    return {
        "name": submission.name,
        "company": submission.company,
        "email": submission.email,
        "phone": submission.phone,
        "country": normalize_country(submission.country),
        "status": "New",
        "owner": None,
        "notes": submission.message,
        "created_at": submission.submitted_at,
        "updated_at": None,
        "original_source": None,
        "source_channel": None,
        "source_detail": None,
        "email_key": normalize_email(submission.email),
        "phone_key": normalize_phone(submission.phone),
        "email_domain": email_domain(submission.email),
        "name_key": normalize_name(submission.name),
        "company_key": normalize_company(submission.company),
        "form_data": {
            "form_id": submission.form_id,
            "form_name": submission.form_name,
            "page_url": submission.page_url,
            "submitted_at": _utc_string(submission.submitted_at),
        },
    }


def _candidate_leads(session: Session, incoming: Lead) -> list[Lead]:
    conditions = [
        getattr(Lead, field) == getattr(incoming, field)
        for field in BLOCK_FIELDS
        if getattr(incoming, field)
    ]
    if not conditions:
        return []
    return list(session.scalars(select(Lead).where(or_(*conditions)).order_by(Lead.id)))


def _conflict_candidates(
    candidates: list[Lead],
    assessments: dict[int, DuplicateAssessment],
    exact_ids: set[int],
) -> list[dict[str, object]]:
    result = []
    for candidate in candidates:
        assessment = assessments[candidate.id]
        if candidate.id not in exact_ids and assessment.score < 0.75:
            continue
        result.append(
            {
                "lead_id": candidate.id,
                "score": round(assessment.score, 4),
                "confidence": assessment.confidence,
                "reasons": list(assessment.reasons),
            }
        )
    return sorted(result, key=lambda item: (-float(item["score"]), int(item["lead_id"])))


def _raise_conflict(
    code: str,
    message: str,
    candidates: list[Lead],
    assessments: dict[int, DuplicateAssessment],
    exact_ids: set[int],
) -> NoReturn:
    raise HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": message,
            "candidates": _conflict_candidates(candidates, assessments, exact_ids),
        },
    )


def _normalized_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _append_distinct_message(notes: str | None, message: str | None) -> tuple[str | None, bool]:
    if not message:
        return notes, False
    if not notes:
        return message, True

    existing = _normalized_line_endings(notes)
    incoming = _normalized_line_endings(message)
    bounded_existing = f"\n\n{existing}\n\n"
    bounded_incoming = f"\n\n{incoming}\n\n"
    if existing == incoming or bounded_incoming in bounded_existing:
        return notes, False
    return f"{notes.rstrip()}\n\n{message}", True


def _stored_submission_time(form_data: dict[str, object] | None) -> datetime | None:
    if not form_data:
        return None
    submitted_at = form_data.get("submitted_at")
    if not isinstance(submitted_at, str):
        return None
    try:
        return as_utc(datetime.fromisoformat(submitted_at.replace("Z", "+00:00")))
    except ValueError:
        return None


def _update_existing(
    session: Session,
    lead: Lead,
    incoming: Lead,
) -> Lead:
    changed = False
    for field in ("name", "company", "email", "phone", "country"):
        if not getattr(lead, field) and getattr(incoming, field):
            setattr(lead, field, getattr(incoming, field))
            changed = True

    if changed:
        lead.name_key = normalize_name(lead.name)
        lead.company_key = normalize_company(lead.company)
        lead.email_key = normalize_email(lead.email)
        lead.email_domain = email_domain(lead.email)
        lead.phone_key = normalize_phone(lead.phone)

    lead.notes, notes_changed = _append_distinct_message(lead.notes, incoming.notes)
    changed = changed or notes_changed

    current_submission = _stored_submission_time(lead.form_data)
    incoming_submission = _stored_submission_time(incoming.form_data)
    if incoming_submission and (
        current_submission is None or incoming_submission > current_submission
    ):
        lead.form_data = incoming.form_data
        changed = True

    if changed:
        lead.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(lead)
    return lead


@router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={201: {"model": IngestResponse, "description": "Lead created"}},
)
def ingest_lead(
    submission: WebsiteSubmission,
    response: Response,
    session: Session = Depends(get_session),
) -> IngestResponse:
    values = _submission_values(submission)
    incoming = Lead(id=0, **values)
    candidates = _candidate_leads(session, incoming)
    assessments = {
        candidate.id: score_candidate(incoming, candidate) for candidate in candidates
    }

    email_ids = {
        candidate.id
        for candidate in candidates
        if incoming.email_key and candidate.email_key == incoming.email_key
    }
    phone_ids = {
        candidate.id
        for candidate in candidates
        if incoming.phone_key and candidate.phone_key == incoming.phone_key
    }
    exact_ids = email_ids | phone_ids

    if email_ids and phone_ids and email_ids.isdisjoint(phone_ids):
        _raise_conflict(
            "conflicting_identity",
            "Email and phone match different existing leads",
            candidates,
            assessments,
            exact_ids,
        )
    if len(email_ids) > 1 or len(phone_ids) > 1:
        _raise_conflict(
            "ambiguous_match",
            "An exact identifier matches multiple existing leads",
            candidates,
            assessments,
            exact_ids,
        )

    plausible = [
        candidate
        for candidate in candidates
        if assessments[candidate.id].confidence in {"clear", "likely"}
        and assessments[candidate.id].score >= 0.75
    ]
    clear = [
        candidate
        for candidate in plausible
        if assessments[candidate.id].confidence == "clear"
    ]
    if len(clear) == 1 and len(plausible) == 1:
        lead = _update_existing(session, clear[0], incoming)
        return IngestResponse(action="updated", lead=lead)

    if plausible or exact_ids:
        _raise_conflict(
            "ambiguous_match",
            "Submission does not resolve to one clearly supported identity",
            candidates,
            assessments,
            exact_ids,
        )

    lead = Lead(**values)
    session.add(lead)
    session.commit()
    session.refresh(lead)
    response.status_code = status.HTTP_201_CREATED
    return IngestResponse(action="created", lead=lead)
