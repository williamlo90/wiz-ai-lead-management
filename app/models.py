from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_email_key", "email_key"),
        Index("ix_leads_phone_key", "phone_key"),
        Index("ix_leads_email_domain", "email_domain"),
        Index("ix_leads_company_key", "company_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50))
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    original_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_key: Mapped[str] = mapped_column(String(320))
    phone_key: Mapped[str] = mapped_column(String(64))
    email_domain: Mapped[str] = mapped_column(String(255))
    name_key: Mapped[str] = mapped_column(String(255))
    company_key: Mapped[str] = mapped_column(String(255))
    form_data: Mapped[dict[str, Any] | None] = mapped_column(
        "form_metadata", JSON, nullable=True
    )

