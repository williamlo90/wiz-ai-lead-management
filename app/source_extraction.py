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
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(" ".join(line.split()) for line in normalized.split("\n"))
    cleaned = cleaned.strip()
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


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]


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
    event_sentence = next(
        (
            sentence
            for sentence in _sentences(text)
            if EVENT_PATTERN.search(sentence)
            and re.search(r"\bbooth\b", sentence, re.IGNORECASE)
        ),
        None,
    )
    if event_sentence is None:
        return None
    event = EVENT_PATTERN.search(event_sentence)
    assert event is not None
    event_name = _canonical_event(event.group(0))
    qr_scan = re.search(
        r"(?:\bscanned\b.{0,30}\bqr code\b|\bqr code\b.{0,30}\bscanned\b)",
        event_sentence,
        re.IGNORECASE,
    )
    unrelated_scan = qr_scan and re.search(
        r"\b(?:in|at)\s+(?:our\s+|the\s+)?(?:office|home|hotel|airport)\b",
        event_sentence[qr_scan.start() : qr_scan.end() + 50],
        re.IGNORECASE,
    )
    if re.search(r"\bno\s+qr\s+scan\s+logged\b", event_sentence, re.IGNORECASE):
        interaction = "Booth conversation; no QR scan logged"
    elif re.search(
        r"\b(?:(?:has|have|had|did|does|do)\s+not|"
        r"(?:hasn't|haven't|hadn't|didn't|doesn't))\s+"
        r"scan(?:ned|ning)?\b.{0,40}\bqr\s+code\b",
        event_sentence,
        re.IGNORECASE,
    ):
        interaction = "Booth conversation; QR scan explicitly negated"
    elif qr_scan and not unrelated_scan:
        interaction = "Booth QR Code"
    else:
        interaction = "Booth conversation"
    return SourceResult("Event", f"{event_name} - {interaction}")


def _referral_result(text: str) -> SourceResult | None:
    match = re.search(
        r"\breferred\s+by\s+(.+?)(?=,|[.;\n]|\s+(?:then|before|after)\b|"
        r"\s+and\s+(?:connected|contacted|met|called|emailed)\b|$)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return SourceResult("Referral", f"Referred by {match.group(1).strip()}")


def _linkedin_result(text: str) -> SourceResult | None:
    linkedin_sentences = [
        sentence
        for sentence in _sentences(text)
        if re.search(r"\blinked\s*in\b", sentence, re.IGNORECASE)
    ]
    if not linkedin_sentences:
        return None
    dm_sentence = next(
        (
            sentence
            for sentence in linkedin_sentences
            if re.search(r"\bdm\b", sentence, re.IGNORECASE)
        ),
        None,
    )
    if dm_sentence:
        detail = "LinkedIn DM"
        if re.search(r"\binbound\b|\breceived\b", dm_sentence, re.IGNORECASE):
            detail += " inbound"
        if re.search(r"\bpricing\b", dm_sentence, re.IGNORECASE):
            detail += "; pricing inquiry"
        return SourceResult("LinkedIn", detail)
    if any(
        re.search(r"\bpost\b|\bcomment", sentence, re.IGNORECASE)
        for sentence in linkedin_sentences
    ):
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
    page = re.search(
        r"\bfill(?:ed|ing) out the form on the\s+(.+?)"
        r"(?=\s+(?:before|after|then)\b|[,.;\n]|$)",
        text,
        re.IGNORECASE,
    )
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


def _evidence_span(text: str, result: SourceResult) -> tuple[int, int] | None:
    if result.channel == "Event":
        match = EVENT_PATTERN.search(text)
    elif result.channel == "Referral":
        match = re.search(r"\breferred\s+by\b", text, re.IGNORECASE)
    elif result.channel == "LinkedIn":
        match = re.search(r"\blinked\s*in\b", text, re.IGNORECASE)
    elif result.channel == "Organic Search":
        match = re.search(
            r"\borganic\s+google\s+search\b|\bgoogled\s+us\b",
            text,
            re.IGNORECASE,
        )
    elif result.channel == "Website":
        match = re.search(
            r"\bfill(?:ed|ing) out the form\b", text, re.IGNORECASE
        )
    elif result.channel == "Manual/Sales":
        match = re.search(
            r"\binbound\s+phone\s+call\b|\bcold\s+outreach\b|\bmanual(?:ly)?\b",
            text,
            re.IGNORECASE,
        )
    elif result.detail.startswith("Paid Google advertising"):
        match = re.search(r"\bgoogle\s+ad\b|\bpaid\s+google\b", text, re.IGNORECASE)
    elif result.detail.startswith("Social post interaction"):
        match = re.search(r"\bsaw our post\b|\bpost\b", text, re.IGNORECASE)
    elif result.detail == "Walk-in contact":
        match = re.search(r"\bwalked into\b|\bwalk-in\b", text, re.IGNORECASE)
    elif result.detail == "General info@ inbox":
        match = re.search(r"\bgeneral\s+info@\s+inbox\b", text, re.IGNORECASE)
    else:
        match = None
    return match.span() if match else None


def _ordered_original_source(
    text: str, results: list[SourceResult]
) -> SourceResult | None:
    by_channel = {result.channel: result for result in results}
    if len(by_channel) != 2:
        return None

    positioned = []
    for result in by_channel.values():
        span = _evidence_span(text, result)
        if span is None:
            return None
        positioned.append((span, result))
    positioned.sort(key=lambda item: item[0][0])

    (first_span, first), (second_span, second) = positioned
    leading_connector = re.fullmatch(
        r"\s*(after|before)\s+", text[: first_span[0]], re.IGNORECASE
    )
    if leading_connector:
        if leading_connector.group(1).casefold() == "after":
            return first
        return second

    between = text[first_span[1] : second_span[0]]
    connectors = re.findall(r"\b(then|before|after)\b", between, re.IGNORECASE)
    if len(connectors) != 1:
        return None
    if connectors[0].casefold() == "after":
        return second
    return first


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

    if ordered_result := _ordered_original_source(cleaned, results):
        return ordered_result

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
