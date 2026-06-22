import json
import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from .config import BASE_DIR, LOCATION_AGNOSTIC_MIN_ROUND
from .models import Candidate, Company, Job, Observation, OpportunityCompany
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


def apply_opportunity_records(db, records):
    """Ingest the boss's opportunity-scoring CSV into OpportunityCompany --
    a table that belongs entirely to the Merge & Export tab. This NEVER
    creates or modifies a row in Company; the scraping pipeline is
    untouched by this upload. Matching/creation here is keyed on
    normalize_company() against OpportunityCompany.name, completely
    independent of whatever rows exist in companies."""
    created = []
    updated = []
    for record in records:
        normalized = normalize_company(record.company_name)
        opp = db.scalar(select(OpportunityCompany).where(OpportunityCompany.name == normalized))
        is_new = opp is None
        if is_new:
            opp = OpportunityCompany(name=normalized, display_name=record.company_name)
            db.add(opp)

        opp.opportunity_score = record.opportunity_score
        opp.city = record.primary_city()
        opp.state = record.primary_state()
        opp.job_role_posted = record.job_role
        opp.supplier_type = record.supplier_type
        opp.ai_insight = record.ai_insight
        opp.contact_details = record.contact_details

        (created if is_new else updated).append(opp.display_name)

    return {"created": created, "updated": updated}


def apply_supplier_types(db, records):
    """Pipeline-tab counterpart to apply_opportunity_records: same CSV
    format (extra columns like score/insight are simply ignored), but this
    one writes Supplier Type directly onto Company.industry so
    next_persona() picks up the right round sequence natively, with no
    cross-table lookup needed. Only ever touches a company that hasn't
    started scraping yet (rounds_completed == 0) -- once roles_tried is
    non-empty, changing the persona sequence mid-flight would silently
    invalidate rounds already run. Like apply_domain_records, this only
    updates EXISTING companies; it never creates one, since a company with
    no scrape round yet has nothing for a persona sequence to apply to."""
    updated = []
    skipped_locked = []
    unmatched = []
    for record in records:
        normalized = normalize_company(record.company_name)
        company = db.scalar(select(Company).where(Company.name == normalized))
        if not company:
            unmatched.append(record.company_name)
            continue
        supplier_type = record.primary_supplier_type()
        if not supplier_type:
            continue
        if company.rounds_completed > 0:
            skipped_locked.append(company.display_name)
            continue
        company.industry = supplier_type if supplier_type in PERSONAS else "default"
        updated.append(company.display_name)
    return {"updated": updated, "skipped_locked": skipped_locked, "unmatched": unmatched}


def build_merged_rows(db, people_records):
    """Merge the people CSV (first_name, last_name, company_name, ...) with
    two INDEPENDENT sources, joined only by normalized company name at
    read time: OpportunityCompany (score, city, state, insight, job role
    posted, supplier type -- set by apply_opportunity_records) and
    Company.candidates (winner role + LinkedIn URL, the existing scrape
    pipeline's output -- NOT the people CSV's own linkedin_url column).
    Neither source is written to here; this is a pure read-side join.

    Pairing rule for a company with up to 2 people-CSV rows and up to 2
    winners: rank-matched -- the company's FIRST person-CSV row pairs with
    its TOP-scoring winner, the second row with the second winner. If a
    company has more people-CSV rows than winners (or no winners at all,
    or no Company/OpportunityCompany match at all), the unmatched person
    rows still appear with the missing fields left blank rather than being
    dropped -- the person is still a real contact worth having in the
    export even without a confirmed decision-maker match yet."""
    by_company = {}
    order = []
    for record in people_records:
        key = normalize_company(record.company_name)
        if key not in by_company:
            by_company[key] = []
            order.append(key)
        by_company[key].append(record)

    companies = db.scalars(
        select(Company).where(Company.name.in_(order)).options(selectinload(Company.candidates))
    ).all()
    companies_by_key = {c.name: c for c in companies}

    opportunities = db.scalars(
        select(OpportunityCompany).where(OpportunityCompany.name.in_(order))
    ).all()
    opportunities_by_key = {o.name: o for o in opportunities}

    rows = []
    for key in order:
        people = by_company[key]
        company = companies_by_key.get(key)
        opp = opportunities_by_key.get(key)
        winners = []
        if company:
            winners = sorted(
                [c for c in company.candidates if c.is_winner],
                key=lambda c: (-(c.investment_score or 0), c.round_number, c.position),
            )
        display_name = (
            (company.display_name if company else None)
            or (opp.display_name if opp else None)
            or people[0].company_name
        )
        for index, person in enumerate(people):
            winner = winners[index] if index < len(winners) else None
            rows.append({
                "company_name": display_name,
                "opportunity_score": opp.opportunity_score if opp else None,
                "city": opp.city if opp else "",
                "state": opp.state if opp else "",
                "person_name": person.full_name(),
                "email": person.email,
                "role": winner.raw_title if winner else "",
                "linkedin_url": winner.raw_url if winner else "",
                "ai_insight": opp.ai_insight if opp else "",
                "job_role_posted": opp.job_role_posted if opp else "",
                "supplier_type": opp.supplier_type if opp else "",
                "contact_details": opp.contact_details if opp else "",
            })
    return rows


def next_persona(company, supplier_type_hint=None):
    """Round sequence priority: a MANUAL industry override always wins.
    'Manual override' is detected as company.industry != 'default' --
    since the dropdown and apply_supplier_types are the only two things
    that ever set industry to anything else, and 'default' itself is a
    fallback persona set rather than something a person deliberately picks
    to mean 'use the default sequence and ignore Supplier Type'. If no
    override exists, fall back to supplier_type_hint -- normally the
    matching OpportunityCompany.supplier_type, looked up read-only by the
    caller. This is how the merge tab's opportunity data can inform the
    pipeline's round suggestions WITHOUT ever writing to Company."""
    industry = company.industry
    if industry == "default" and supplier_type_hint and supplier_type_hint in PERSONAS:
        industry = supplier_type_hint
    roles = PERSONAS.get(industry, PERSONAS["default"])
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


def apply_domain_records(db, records):
    """Enrich existing companies with a domain from an uploaded {company_name,
    domain} list. Matching uses the same normalize_company() key as the
    LinkedIn upload, so a domain row only attaches to a company that's
    already been created by a scrape round. Companies with no match are
    reported back, not silently dropped or auto-created, since a domain
    file with no corresponding scrape round is more likely a typo than a
    brand-new company the rest of the pipeline has never seen."""
    matched = []
    unmatched = []
    for record in records:
        normalized = normalize_company(record.company_name)
        company = db.scalar(select(Company).where(Company.name == normalized))
        if not company:
            unmatched.append(record.company_name)
            continue
        company.domain = record.domain
        matched.append(company.display_name)
    return {"matched": matched, "unmatched": unmatched}


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