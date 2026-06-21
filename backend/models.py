from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    industry: Mapped[str] = mapped_column(String, default="default")
    status: Mapped[str] = mapped_column(String, default="needs_next_round")
    rounds_completed: Mapped[int] = mapped_column(Integer, default=0)
    roles_tried: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    candidates: Mapped[list["Candidate"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("company_id", "url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    raw_url: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String, default="")
    raw_title: Mapped[str] = mapped_column(Text)
    raw_snippet: Mapped[str] = mapped_column(Text)
    search_role: Mapped[str] = mapped_column(String)
    search_location: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    times_seen: Mapped[int] = mapped_column(Integer, default=0)
    gemini_company_match: Mapped[str | None] = mapped_column(String, nullable=True)
    gemini_role_match: Mapped[str | None] = mapped_column(String, nullable=True)
    gemini_location_match: Mapped[str | None] = mapped_column(String, nullable=True)
    gemini_employment_status: Mapped[str | None] = mapped_column(String, nullable=True)
    gemini_name_collision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    investment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    processing_status: Mapped[str] = mapped_column(String, default="pending")
    gemini_extraction_failed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    is_low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    company: Mapped[Company] = relationship(back_populates="candidates")
    observations: Mapped[list["Observation"]] = relationship(back_populates="candidate")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String, default="running")
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    processed_candidates: Mapped[int] = mapped_column(Integer, default=0)
    failed_candidates: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Observation(Base):
    """One candidate appearance; makes corroboration and re-uploads idempotent."""
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("company_id", "url", "search_role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    raw_title: Mapped[str] = mapped_column(Text)
    raw_snippet: Mapped[str] = mapped_column(Text)
    search_role: Mapped[str] = mapped_column(String)
    search_location: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    person_name: Mapped[str | None] = mapped_column(String, nullable=True)
    companies_found: Mapped[list | None] = mapped_column(JSON, nullable=True)
    titles_found: Mapped[list | None] = mapped_column(JSON, nullable=True)
    locations_found: Mapped[list | None] = mapped_column(JSON, nullable=True)
    employment_indicators: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_employment_status: Mapped[str | None] = mapped_column(String, nullable=True)
    company_match: Mapped[str | None] = mapped_column(String, nullable=True)
    role_match: Mapped[str | None] = mapped_column(String, nullable=True)
    location_match: Mapped[str | None] = mapped_column(String, nullable=True)
    employment_status: Mapped[str | None] = mapped_column(String, nullable=True)
    name_collision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    processing_status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    company: Mapped[Company] = relationship()
    candidate: Mapped[Candidate] = relationship(back_populates="observations")

