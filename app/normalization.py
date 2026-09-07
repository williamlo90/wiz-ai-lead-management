import re
from datetime import datetime, timezone


STATUSES = {
    "new": "New",
    "contacted": "Contacted",
    "connected": "Connected",
    "qualified": "Qualified",
    "opportunity": "Opportunity",
    "closed won": "Closed Won",
    "closed lost": "Closed Lost",
}


def clean_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def optional_text(value: str | None) -> str | None:
    cleaned = clean_text(value)
    return cleaned or None


def optional_free_text(value: str | None) -> str | None:
    """Trim free text without changing its internal spacing or line breaks."""
    cleaned = (value or "").strip()
    return cleaned or None


def normalize_status(value: str) -> str:
    key = clean_text(value).casefold()
    try:
        return STATUSES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown lead status: {value!r}") from exc


def normalize_country(value: str) -> str:
    cleaned = clean_text(value)
    if cleaned.casefold() == "uae":
        return "UAE"
    return cleaned.title()


def normalize_email(value: str) -> str:
    return clean_text(value).casefold()


def email_domain(value: str) -> str:
    normalized = normalize_email(value)
    return normalized.rsplit("@", 1)[-1] if "@" in normalized else ""


def normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_name(value: str) -> str:
    return clean_text(value).casefold()


def normalize_company(value: str) -> str:
    text = clean_text(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return clean_text(text)


def parse_seed_datetime(value: str | None) -> datetime | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None

    formats = (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%m/%d/%Y",
    )
    for date_format in formats:
        try:
            parsed = datetime.strptime(cleaned, date_format)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value!r}")


def as_utc(value: datetime | None) -> datetime | None:
    """Attach the project's UTC convention to naive SQLite datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
