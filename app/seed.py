import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Lead
from app.normalization import (
    clean_text,
    email_domain,
    normalize_company,
    normalize_country,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_status,
    optional_free_text,
    optional_text,
    parse_seed_datetime,
)
from app.source_extraction import extract_source


def load_seed_data(session: Session, csv_path: Path) -> int:
    """Load the seed once; an existing leads table is left untouched."""
    if session.scalar(select(func.count()).select_from(Lead)):
        return 0

    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    leads = []
    for row in rows:
        name = clean_text(row["Full Name"]) or clean_text(
            f'{row["First Name"]} {row["Last Name"]}'
        )
        email = clean_text(row["Email"])
        phone = clean_text(row["Phone Number"])
        company = clean_text(row["Company Name"])
        created_at = parse_seed_datetime(row["Create Date"])
        if created_at is None:
            raise ValueError(f'Record {row["Record ID"]} has no creation date')
        notes = optional_free_text(row["Notes"])
        source = extract_source(notes)

        leads.append(
            Lead(
                id=int(row["Record ID"]),
                name=name,
                company=company,
                email=email,
                phone=phone,
                country=normalize_country(row["Country/Region"]),
                status=normalize_status(row["Lead Status"]),
                owner=optional_text(row["Contact Owner"]),
                notes=notes,
                created_at=created_at,
                updated_at=parse_seed_datetime(row["Last Modified Date"]),
                original_source=optional_text(row["Original Source"]),
                source_channel=source.channel,
                source_detail=source.detail,
                email_key=normalize_email(email),
                phone_key=normalize_phone(phone),
                email_domain=email_domain(email),
                name_key=normalize_name(name),
                company_key=normalize_company(company),
                form_data=None,
            )
        )

    session.add_all(leads)
    session.commit()
    return len(leads)
