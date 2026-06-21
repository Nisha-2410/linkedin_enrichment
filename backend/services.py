import json
import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, select

from .config import BASE_DIR, LOCATION_AGNOSTIC_MIN_ROUND
from .models import Candidate, Company, Job, Observation
from .scoring import score_candidate
from .stopping_logic import decide_company

PERSONAS = json.loads((BASE_DIR / "personas.json").read_text())


def candidate_display_name(raw_title):
    value = (raw_title or "").strip()
    for separator in (" - ", " · "):
        if separator in value:
            name = value.split(separator, 1)[0].strip()
            return name or value
    return value


def normalize_company(value):
    return " ".join(value.lower().split())


def normalize_url(value):
    parts = urlsplit(str(value).strip().lower())
    path = re.sub(r"/+$", "", parts.path)
    return urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))


def next_persona(company):
    roles = PERSONAS.get(company.industry, PERSONAS["default"])
    tried = {role.casefold() for role in company.roles_tried}
    return next((role for role in roles if role.casefold() not in tried), None)


def aggregate_candidate(db, candidate_id):
    candidate = db.get(Candidate, candidate_id)
    observations = db.scalars(
        select(Observation).where(
            Observation.candidate_id == candidate_id,
            Observation.processing_status == "extracted",
        )
    ).all()
    if not observations:
        candidate.processing_status = "failed"
        candidate.gemini_extraction_failed = True
        return candidate

    strength = {
        "company": {"absent": 0, "partial": 1, "exact": 2},
        "role": {"absent": 0, "related": 1, "exact": 2},
        "location": {"absent": 0, "country_only": 1, "state": 2, "metro": 3, "city": 4},
        "employment": {"former": 0, "unclear": 1, "current": 2},
    }
    best = lambda attr, key: max(observations, key=lambda o: strength[key][getattr(o, attr)])
    candidate.gemini_company_match = best("company_match", "company").company_match
    candidate.gemini_role_match = best("role_match", "role").role_match
    candidate.gemini_location_match = best("location_match", "location").location_match
    candidate.gemini_employment_status = best("employment_status", "employment").employment_status
    # all() over a list of Nones returns True, which would incorrectly zero
    # a valid candidate's score. Only flag a collision when every observation
    # has an *explicit* True -- None/False observations are not collisions.
    candidate.gemini_name_collision = bool(observations) and all(
        o.name_collision is True for o in observations
    )
    candidate.times_seen = len(observations)

    # candidate.round_number is the round this person was FIRST found in --
    # not which round(s) actually produced their evidence. A person first
    # found in round 1 (Operations Manager search, location relevant) can
    # reappear in round 3 (Director of Operations, location-agnostic), so the
    # location-agnostic decision must look at every contributing observation,
    # not just the candidate row. Location only drops out of the formula once
    # NONE of the evidence came from a location-relevant round (1-2) -- if a
    # location-relevant search ever ran for this person and still came back
    # "absent", that's real signal and should still count.
    location_agnostic = all(o.round_number >= LOCATION_AGNOSTIC_MIN_ROUND for o in observations)

    result = score_candidate(
        candidate.gemini_company_match,
        candidate.gemini_role_match,
        candidate.gemini_location_match,
        candidate.gemini_employment_status,
        candidate.gemini_name_collision,
        candidate.times_seen,
        location_agnostic=location_agnostic,
    )
    candidate.retrieval_score = result.retrieval_score
    candidate.investment_score = result.investment_score
    candidate.rejection_reason = result.rejection_reason
    candidate.processing_status = "scored"
    candidate.gemini_extraction_failed = False
    return candidate


def update_company_decision(db, company_id):
    company = db.get(Company, company_id)
    candidates = db.scalars(select(Candidate).where(Candidate.company_id == company_id)).all()
    decision = decide_company(candidates, company.rounds_completed)
    company.status = decision.status
    for candidate in candidates:
        candidate.is_winner = candidate.id in decision.winner_ids
        candidate.is_low_confidence = candidate.id in decision.low_confidence_ids
    return decision


def delete_company(db, company_id):
    """Permanently remove a company and every candidate/observation tied to it.
    Irreversible. Job rows are left alone since a Job can span other companies."""
    db.execute(delete(Observation).where(Observation.company_id == company_id))
    db.execute(delete(Candidate).where(Candidate.company_id == company_id))
    company = db.get(Company, company_id)
    if company:
        db.delete(company)


def delete_candidate(db, candidate_id):
    """Permanently remove a single person and their observations, then
    re-evaluate the parent company's status since a winner may have been removed."""
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        return None
    company_id = candidate.company_id
    db.execute(delete(Observation).where(Observation.candidate_id == candidate_id))
    db.delete(candidate)
    db.flush()
    update_company_decision(db, company_id)
    return company_id


def wipe_all_data(db):
    """Permanently remove every company, candidate, observation, and job.
    Irreversible full reset, intended for clearing out test data."""
    db.execute(delete(Observation))
    db.execute(delete(Candidate))
    db.execute(delete(Company))
    db.execute(delete(Job))