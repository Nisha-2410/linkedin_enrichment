import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import Candidate, Company
from .services import candidate_display_name, next_persona


def _csv_response(rows, fieldnames):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def still_needed_csv(db):
    companies = db.scalars(
        select(Company).where(Company.status == "needs_next_round").order_by(Company.display_name)
    ).all()
    rows = [
        {
            "company_name": c.display_name,
            "rounds_completed": c.rounds_completed,
            "roles_already_tried": " | ".join(c.roles_tried),
            "suggested_next_role": next_persona(c) or "",
        }
        for c in companies
    ]
    return _csv_response(rows, ["company_name", "rounds_completed", "roles_already_tried", "suggested_next_role"])


def final_csv(db, forced=False):
    companies = db.scalars(
        select(Company).options(selectinload(Company.candidates)).order_by(Company.display_name)
    ).all()
    rows = []
    for company in companies:
        winners = sorted(
            [c for c in company.candidates if c.is_winner],
            key=lambda c: (-(c.investment_score or 0), c.round_number, c.position),
        )[:2]
        forced_low_confidence_ids = set()
        if forced and company.status == "needs_next_round" and not winners:
            ranked = sorted(
                [c for c in company.candidates if (c.investment_score or 0) > 0],
                key=lambda c: (-(c.investment_score or 0), c.round_number, c.position),
            )
            winners = [c for c in ranked if c.investment_score >= 85][:2]
            if not winners and ranked:
                winners = ranked[:1]
                forced_low_confidence_ids.add(ranked[0].id)
        row = {
            "company_name": company.display_name,
            "rounds_taken": company.rounds_completed,
            "final_status": company.status,
        }
        if forced and company.status == "needs_next_round":
            row["final_status"] = "needs_next_round (forced-finalized early)"
        for index in (1, 2):
            candidate = winners[index - 1] if len(winners) >= index else None
            prefix = f"decision_maker_{index}"
            row[f"{prefix}_name"] = _name(candidate.raw_title) if candidate else ""
            row[f"{prefix}_role_title"] = candidate.raw_title if candidate else ""
            row[f"{prefix}_linkedin_url"] = candidate.raw_url if candidate else ""
            row[f"{prefix}_investment_score"] = candidate.investment_score if candidate else ""
            row[f"{prefix}_evidence"] = _excerpt(candidate.raw_snippet) if candidate else ""
            row[f"{prefix}_low_confidence"] = (
                "yes"
                if candidate and (candidate.is_low_confidence or candidate.id in forced_low_confidence_ids)
                else ""
            )
        rows.append(row)
    fields = ["company_name"]
    for index in (1, 2):
        fields.extend(
            [
                f"decision_maker_{index}_name",
                f"decision_maker_{index}_role_title",
                f"decision_maker_{index}_linkedin_url",
                f"decision_maker_{index}_investment_score",
                f"decision_maker_{index}_evidence",
                f"decision_maker_{index}_low_confidence",
            ]
        )
    fields.extend(["rounds_taken", "final_status"])
    return _csv_response(rows, fields)



def audit_csv(db):
    fields = [
        "company_name",
        "company_status",
        "round_number",
        "search_role",
        "search_location",
        "candidate_name",
        "raw_title",
        "raw_snippet",
        "url",
        "gemini_company_match",
        "gemini_role_match",
        "gemini_location_match",
        "gemini_employment_status",
        "gemini_name_collision",
        "retrieval_score",
        "investment_score",
        "times_seen",
        "processing_status",
        "is_winner",
        "rejection_reason",
    ]
    candidates = db.scalars(
        select(Candidate)
        .join(Candidate.company)
        .options(selectinload(Candidate.company))
        .order_by(
            Company.display_name.asc(),
            Candidate.investment_score.desc().nulls_last(),
            Candidate.round_number.asc(),
        )
    ).all()
    rows = []
    for candidate in candidates:
        rows.append(
            {
                "company_name": candidate.company.display_name,
                "company_status": candidate.company.status,
                "round_number": candidate.round_number,
                "search_role": candidate.search_role,
                "search_location": candidate.search_location,
                "candidate_name": candidate.display_name or candidate_display_name(candidate.raw_title),
                "raw_title": candidate.raw_title,
                "raw_snippet": candidate.raw_snippet,
                "url": candidate.raw_url,
                "gemini_company_match": candidate.gemini_company_match or "",
                "gemini_role_match": candidate.gemini_role_match or "",
                "gemini_location_match": candidate.gemini_location_match or "",
                "gemini_employment_status": candidate.gemini_employment_status or "",
                "gemini_name_collision": _bool(candidate.gemini_name_collision),
                "retrieval_score": _number(candidate.retrieval_score),
                "investment_score": _number(candidate.investment_score),
                "times_seen": candidate.times_seen,
                "processing_status": candidate.processing_status,
                "is_winner": _bool(candidate.is_winner),
                "rejection_reason": candidate.rejection_reason or "",
            }
        )
    return _csv_response(rows, fields)
def _name(title):
    return candidate_display_name(title)


def _excerpt(snippet, length=240):
    return snippet if len(snippet) <= length else snippet[: length - 1].rstrip() + "â€¦"


def _bool(value):
    if value is None:
        return ""
    return "true" if value else "false"


def _number(value):
    return "" if value is None else value