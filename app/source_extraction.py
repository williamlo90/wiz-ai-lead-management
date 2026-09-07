import re
from dataclasses import dataclass

from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Lead
from app.schemas import (
    SourceChannel,
    SourceExtractionRequest,
    SourceExtractionResponse,
)


router = APIRouter(prefix="/leads", tags=["source extraction"])

UNSPECIFIED_DETAIL = "Source unspecified"
OPERATIONAL_SUFFIXES = (
    "No response yet",
    "Great fit, prioritizing",
    "Connected, sending proposal",
    "Qualifying now",
    "Very interested, wants pricing call",
    "Left voicemail, will retry",
    "Not interested for now",
)
EVENT_NAMES = (
    "SaaStr Annual",
    "TechCrunch Disrupt",
    "Mobile World Congress",
    "Dubai FinTech Week",
    "Singapore FinTech Festival",
    "Money20/20 Asia",
    "London Tech Week",
    "Web Summit",
    "Retail Asia Expo",
    "APAC Logistics Summit",
)
EVENT_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(name) for name in EVENT_NAMES)
    + r"|SFF)(?:\s+(?:19|20)\d{2})?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceResult:
    channel: SourceChannel
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", self.detail[:500])


def _clean_for_extraction(text: str | None) -> str:
    cleaned = " ".join((text or "").split()).strip()
    duplicate_pattern = re.compile(
        r"\s*possible duplicate\s*\W+\s*verify before contacting\.?\s*$",
        re.IGNORECASE,
    )
    suffix_pattern = re.compile(
        r"\s*\.\s*(?:"
        + "|".join(re.escape(suffix) for suffix in OPERATIONAL_SUFFIXES)
        + r")\.?\s*$",
        re.IGNORECASE,
    )
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = duplicate_pattern.sub("", cleaned).strip()
        cleaned = suffix_pattern.sub(".", cleaned).strip()
    return cleaned


def _canonical_event(value: str) -> str:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    year = f" {match.group(1)}" if match else ""
    base = re.sub(r"\s+(?:19|20)\d{2}$", "", value, flags=re.IGNORECASE)
    if base.casefold() == "sff":
        base = "Singapore FinTech Festival"
    else:
        base = next(
            name for name in EVENT_NAMES if name.casefold() == base.casefold()
        )
    return f"{base}{year}"


def _event_result(text: str) -> SourceResult | None:
    event = EVENT_PATTERN.search(text)
    if not event or not re.search(r"\bbooth\b", text, re.IGNORECASE):
        return None
    event_name = _canonical_event(event.group(0))
    if re.search(r"\bno\s+qr\s+scan\s+logged\b", text, re.IGNORECASE):
        interaction = "Booth conversation; no QR scan logged"
    elif re.search(
        r"(?:\bscanned\b.{0,30}\bqr code\b|\bqr code\b.{0,30}\bscanned\b)",
        text,
        re.IGNORECASE,
    ):
        interaction = "Booth QR Code"
    else:
        interaction = "Booth conversation"
    return SourceResult("Event", f"{event_name} - {interaction}")


def _referral_result(text: str) -> SourceResult | None:
    match = re.search(r"\breferred\s+by\s+([^,.;\n]+)", text, re.IGNORECASE)
    if not match:
        return None
    return SourceResult("Referral", f"Referred by {match.group(1).strip()}")


def _linkedin_result(text: str) -> SourceResult | None:
    if not re.search(r"\blinked\s*in\b", text, re.IGNORECASE):
        return None
    if re.search(r"\bdm\b", text, re.IGNORECASE):
        detail = "LinkedIn DM inbound"
        if re.search(r"\bpricing\b", text, re.IGNORECASE):
            detail += "; pricing inquiry"
        return SourceResult("LinkedIn", detail)
    if re.search(r"\bpost\b|\bcomment", text, re.IGNORECASE):
        return SourceResult("LinkedIn", "LinkedIn post interaction")
    return SourceResult("LinkedIn", "LinkedIn interaction")


def _paid_google_result(text: str) -> SourceResult | None:
    if not re.search(r"\bgoogle\s+ad\b|\bpaid\s+google\b", text, re.IGNORECASE):
        return None
    page = re.search(r"\b(?:via|on)\s+the\s+([^.]+?page)\b", text, re.IGNORECASE)
    detail = "Paid Google advertising"
    if page:
        detail += f" - {page.group(1).strip()}"
    return SourceResult("Other", detail)


def _organic_result(text: str) -> SourceResult | None:
    if not re.search(
        r"\borganic\s+google\s+search\b|\bgoogled\s+us\b", text, re.IGNORECASE
    ):
        return None
    page = re.search(
        r"\b(?:landed|ended up)\s+on\s+the\s+(.+?)(?:\s+before\s+booking|\.|$)",
        text,
        re.IGNORECASE,
    )
    detail = "Google organic search"
    if page:
        detail += f" - {page.group(1).strip()}"
    return SourceResult("Organic Search", detail)


def _website_result(text: str) -> SourceResult | None:
    page = re.search(r"\bfilled out the form on the\s+([^.]+)", text, re.IGNORECASE)
    if not page:
        return None
    return SourceResult("Website", f"Form submission - {page.group(1).strip()}")


def _manual_result(text: str) -> SourceResult | None:
    if re.search(r"\binbound\s+phone\s+call\b", text, re.IGNORECASE):
        return SourceResult("Manual/Sales", "Inbound phone call")
    if re.search(r"\bcold\s+outreach\b", text, re.IGNORECASE):
        return SourceResult("Manual/Sales", "Cold outreach phone call")
    if re.search(r"\bmanual(?:ly)?\b", text, re.IGNORECASE):
        return SourceResult("Manual/Sales", "Manual sales entry")
    return None


def _unspecified_social_result(text: str) -> SourceResult | None:
    if re.search(
        r"\b(?:saw our post\b|post\b.{0,80}\bcomment)", text, re.IGNORECASE
    ) and not re.search(r"\blinked\s*in\b", text, re.IGNORECASE):
        return SourceResult("Other", "Social post interaction; platform unspecified")
    return None


def _other_contact_result(text: str) -> SourceResult | None:
    if re.search(r"\bwalked into\b|\bwalk-in\b", text, re.IGNORECASE):
        return SourceResult("Other", "Walk-in contact")
    if re.search(r"\bgeneral\s+info@\s+inbox\b", text, re.IGNORECASE):
        return SourceResult("Other", "General info@ inbox")
    return None


def _website_fallback(form_name: str | None, page_url: str | None) -> SourceResult:
    context = []
    if form_name:
        context.append(f"form: {form_name}")
    if page_url:
        context.append(f"page: {page_url}")
    detail = "Website form" + (f" - {'; '.join(context)}" if context else "")
    return SourceResult("Website", detail[:500])


def extract_source(
    text: str | None,
    *,
    form_name: str | None = None,
    page_url: str | None = None,
    use_website_fallback: bool = False,
) -> SourceResult:
    cleaned = _clean_for_extraction(text)
    extractors = (
        _event_result,
        _referral_result,
        _linkedin_result,
        _paid_google_result,
        _organic_result,
        _website_result,
        _manual_result,
        _unspecified_social_result,
        _other_contact_result,
    )
    results = [result for extractor in extractors if (result := extractor(cleaned))]

    non_website = [result for result in results if result.channel != "Website"]
    channels = list(dict.fromkeys(result.channel for result in non_website))
    if len(channels) == 1:
        return non_website[0]
    if len(channels) > 1:
        return SourceResult("Other", f"Ambiguous source: {', '.join(channels)}")
    if results:
        return results[0]
    if use_website_fallback:
        return _website_fallback(form_name, page_url)
    return SourceResult("Other", UNSPECIFIED_DETAIL)


def backfill_missing_sources(session: Session) -> int:
    leads = session.scalars(
        select(Lead).where(
            or_(Lead.source_channel.is_(None), Lead.source_detail.is_(None))
        )
    ).all()
    changed = 0
    for lead in leads:
        result = extract_source(lead.notes)
        lead_changed = False
        if lead.source_channel is None:
            lead.source_channel = result.channel
            lead_changed = True
        if lead.source_detail is None:
            lead.source_detail = result.detail
            lead_changed = True
        changed += int(lead_changed)
    if changed:
        session.commit()
    return changed


@router.post("/extract-source", response_model=SourceExtractionResponse)
def extract_source_endpoint(
    request: SourceExtractionRequest,
) -> SourceExtractionResponse:
    result = extract_source(request.text)
    return SourceExtractionResponse(channel=result.channel, detail=result.detail)
