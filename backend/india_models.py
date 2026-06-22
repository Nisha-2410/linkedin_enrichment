"""SQLAlchemy model for the India pipeline's phone-number store.

IndiaOpportunityCompany is parallel to OpportunityCompany (the boss's
opportunity-scoring CSV) but is for the India market. It is keyed by
normalize_company() name just like OpportunityCompany and has NO foreign
key to Company -- it is a standalone enrichment table.

IndiaPhoneNumber stores one verified Indian phone number per company,
sourced from either IndiaMart or Serper JSON. The `source` column records
which feed provided the number ('indiamart' or 'serper') so the audit CSV
can show provenance.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class IndiaOpportunityCompany(Base):
    """One row from the boss's India opportunity CSV.
    Fields mirror OpportunityCompany but are stored in a separate table so
    the two markets never collide.
    """
    __tablename__ = "india_opportunity_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)   # normalize_company() key
    display_name: Mapped[str] = mapped_column(String)
    opportunity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    job_role_posted: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_type: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_insight: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    phone: Mapped["IndiaPhoneNumber | None"] = relationship(
        back_populates="india_company", uselist=False, cascade="all, delete-orphan"
    )


class IndiaPhoneNumber(Base):
    """One verified Indian phone number per India-opportunity company.

    Acceptance rules (enforced in india_phone.py, not here):
      1. If the raw number starts with +91, strip it and keep the remaining
         10 digits -- that IS an Indian number, no country check needed.
      2. If the raw number is exactly 10 digits with no country prefix,
         accept it only when the source record's country field is 'India'
         (case-insensitive) or absent/blank (IndiaMart is always India).
      3. Everything else is rejected and logged.

    `source` is 'indiamart' or 'serper'.
    """
    __tablename__ = "india_phone_numbers"
    __table_args__ = (UniqueConstraint("india_company_id"),)   # one phone per company

    id: Mapped[int] = mapped_column(primary_key=True)
    india_company_id: Mapped[int] = mapped_column(
        ForeignKey("india_opportunity_companies.id"), unique=True, index=True
    )
    phone: Mapped[str] = mapped_column(String)       # always stored as 10-digit string, no prefix
    source: Mapped[str] = mapped_column(String)      # 'indiamart' | 'serper'
    raw_value: Mapped[str] = mapped_column(String)   # original value before normalisation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    india_company: Mapped[IndiaOpportunityCompany] = relationship(back_populates="phone")
