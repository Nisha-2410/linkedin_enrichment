import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .csv_export import audit_csv, final_csv, still_needed_csv, merged_csv
from .config import MAX_ROUNDS
from .db import SessionLocal, get_db, init_db
from .job_processor import process_job, rpm_usage
from .models import Candidate, Company, Job, Observation, OpportunityCompany
from .schemas import DomainRecord, IndustryUpdate, OpportunityRecord, PersonRecord, UploadRecord
from .services import (
    PERSONAS,
    apply_domain_records,
    apply_opportunity_records,
    apply_supplier_types,
    build_merged_rows,
    candidate_display_name,
    delete_candidate,
    delete_company,
    next_persona,
    normalize_company,
    normalize_url,
    update_company_decision,
    wipe_all_data,
)


def _parse_json_array(raw: bytes, model, noun: str):
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"Invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise HTTPException(422, f"The JSON root must be an array of {noun} objects.")
    try:
        return TypeAdapter(list[model]).validate_python(data)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        first = errors[0] if errors else {}
        location = ".".join(str(x) for x in first.get("loc", []))
        raise HTTPException(422, f"Invalid record at {location}: {first.get('msg', 'validation failed')}") from exc


def _parse_csv_rows(raw: bytes, model, noun: str):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, f"Could not read file as UTF-8 text: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(422, f"The {noun} CSV has no header row.")
    rows = list(reader)
    try:
        return TypeAdapter(list[model]).validate_python(rows)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        first = errors[0] if errors else {}
        loc = first.get("loc", [])
        # loc[0] is the row index in the parsed list; +2 accounts for the
        # header row and 0-indexing so this matches the line number a person
        # would actually see if they opened the CSV in a spreadsheet.
        row_number = (loc[0] + 2) if loc and isinstance(loc[0], int) else "?"
        field = loc[1] if len(loc) > 1 else "?"
        raise HTTPException(
            422, f"Invalid {noun} CSV at row {row_number}, column {field!r}: {first.get('msg', 'validation failed')}"
        ) from exc


def parse_upload(raw: bytes):
    return _parse_json_array(raw, UploadRecord, "search-result")


def parse_domain_upload(raw: bytes):
    return _parse_json_array(raw, DomainRecord, "company-domain")


def parse_opportunity_upload(raw: bytes):
    return _parse_csv_rows(raw, OpportunityRecord, "opportunity-scoring")


def parse_supplier_types_upload(raw: bytes):
    # Same CSV shape as the opportunity-scoring upload (Company Name +
    # Supplier Type, plus whatever other columns the boss's export includes
    # -- those extra columns are simply ignored here). Reusing OpportunityRecord
    # means one export from the boss works for both the pipeline tab's
    # supplier-types upload and the merge tab's opportunity upload.
    return _parse_csv_rows(raw, OpportunityRecord, "supplier-types")


def parse_people_upload(raw: bytes):
    return _parse_csv_rows(raw, PersonRecord, "people")


@asynccontextmanager
async def lifespan(_app):
    init_db()
    with SessionLocal.begin() as db:
        running_ids = db.scalars(select(Job.id).where(Job.status == "running")).all()
    for job_id in running_ids:
        asyncio.create_task(process_job(job_id))
    yield


app = FastAPI(title="Decision Maker Discovery Engine", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/uploads/preview")
async def preview_upload(file: UploadFile = File(...)):
    records = parse_upload(await file.read())
    companies = {normalize_company(r.search_company) for r in records}
    roles = sorted({r.search_role for r in records})
    return {"company_count": len(companies), "candidate_count": len(records), "roles": roles}


@app.post("/api/uploads/process")
async def upload_and_process(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    records = parse_upload(await file.read())
    with SessionLocal.begin() as db:
        job = Job(status="running")
        db.add(job)
        db.flush()
        new_count = 0
        company_records = {}
        for record in records:
            company_records.setdefault(normalize_company(record.search_company), []).append(record)

        for normalized_name, grouped in company_records.items():
            company = db.scalar(select(Company).where(Company.name == normalized_name))
            if not company:
                company = Company(name=normalized_name, display_name=grouped[0].search_company, roles_tried=[])
                db.add(company)
                db.flush()

            role_rounds = {}
            roles = list(company.roles_tried)
            for record in grouped:
                existing = next((i + 1 for i, role in enumerate(roles) if role.casefold() == record.search_role.casefold()), None)
                if existing:
                    role_rounds[record.search_role.casefold()] = existing
                elif record.search_role.casefold() not in role_rounds:
                    if len(roles) >= MAX_ROUNDS:
                        raise HTTPException(
                            422,
                            f"{company.display_name} already has {MAX_ROUNDS} distinct rounds; cannot add {record.search_role!r}.",
                        )
                    roles.append(record.search_role)
                    role_rounds[record.search_role.casefold()] = len(roles)
            company.roles_tried = roles
            company.rounds_completed = len(roles)

            for record in grouped:
                url = normalize_url(str(record.url))
                role_key = record.search_role.casefold()
                already = db.scalar(
                    select(Observation.id).where(
                        Observation.company_id == company.id,
                        Observation.url == url,
                        func.lower(Observation.search_role) == role_key,
                    )
                )
                if already:
                    continue
                candidate = db.scalar(
                    select(Candidate).where(Candidate.company_id == company.id, Candidate.url == url)
                )
                if not candidate:
                    candidate = Candidate(
                        company_id=company.id,
                        url=url,
                        raw_url=str(record.url),
                        display_name=candidate_display_name(record.title),
                        raw_title=record.title,
                        raw_snippet=record.snippet,
                        search_role=record.search_role,
                        search_location=record.search_location,
                        position=record.position,
                        round_number=role_rounds[role_key],
                    )
                    db.add(candidate)
                    db.flush()
                observation = Observation(
                    company_id=company.id,
                    candidate_id=candidate.id,
                    job_id=job.id,
                    url=url,
                    raw_title=record.title,
                    raw_snippet=record.snippet,
                    search_role=record.search_role,
                    search_location=record.search_location,
                    position=record.position,
                    round_number=role_rounds[role_key],
                )
                db.add(observation)
                new_count += 1
            update_company_decision(db, company.id)

        job.total_candidates = new_count
        if not new_count:
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.message = "No new candidate observations; duplicate upload skipped."
        job_id = job.id

    if new_count:
        background_tasks.add_task(process_job, job_id)
    return {"job_id": job_id, "new_candidates": new_count}


@app.post("/api/uploads/domains")
async def upload_domains(file: UploadFile = File(...)):
    """Ingest a JSON file of {company_name, domain} pairs and attach the
    domain to the matching existing company (matched the same way the
    LinkedIn scrape upload groups companies, by normalize_company()).
    This is a pure enrichment step -- it never creates new companies, since
    a domain with no matching scrape round has nothing to attach to yet."""
    records = parse_domain_upload(await file.read())
    with SessionLocal.begin() as db:
        result = apply_domain_records(db, records)
    return {
        "matched_count": len(result["matched"]),
        "unmatched_count": len(result["unmatched"]),
        "unmatched_company_names": result["unmatched"],
    }


@app.post("/api/uploads/opportunities")
async def upload_opportunities(file: UploadFile = File(...)):
    """Ingest the boss's opportunity-scoring CSV into OpportunityCompany --
    a table that belongs entirely to the Merge & Export tab. Never creates
    or modifies a Company row; the scraping pipeline is untouched."""
    records = parse_opportunity_upload(await file.read())
    with SessionLocal.begin() as db:
        result = apply_opportunity_records(db, records)
    return {
        "created_count": len(result["created"]),
        "updated_count": len(result["updated"]),
        "created_company_names": result["created"],
    }


@app.post("/api/uploads/supplier-types")
async def upload_supplier_types(file: UploadFile = File(...)):
    """Pipeline-tab upload: same CSV shape as the opportunity-scoring CSV
    (Company Name + Supplier Type; other columns are ignored), but this one
    writes Supplier Type directly onto an EXISTING company's industry field
    so next_persona() picks the right round sequence natively. Only updates
    companies that haven't started scraping yet (rounds_completed == 0) --
    a company already mid-round keeps its locked-in sequence, and a
    company name with no match in companies is reported, not created."""
    records = parse_supplier_types_upload(await file.read())
    with SessionLocal.begin() as db:
        result = apply_supplier_types(db, records)
    return {
        "updated_count": len(result["updated"]),
        "skipped_locked_count": len(result["skipped_locked"]),
        "unmatched_count": len(result["unmatched"]),
        "skipped_locked_company_names": result["skipped_locked"],
        "unmatched_company_names": result["unmatched"],
    }


def retryable_observation_count(db):
    return db.scalar(
        select(func.count()).select_from(Observation).where(Observation.processing_status.in_(["pending", "failed"]))
    ) or 0


def company_payload(company, supplier_type_hint=None):
    winners = sorted(
        [candidate for candidate in company.candidates if candidate.is_winner],
        key=lambda c: (-(c.investment_score or 0), c.round_number, c.position),
    )
    return {
        "id": company.id,
        "display_name": company.display_name,
        "domain": company.domain,
        "industry": company.industry,
        "status": company.status,
        "rounds_completed": company.rounds_completed,
        "roles_tried": company.roles_tried,
        "next_role": next_persona(company, supplier_type_hint=supplier_type_hint),
        "winners": [
            {
                "id": c.id,
                "name": c.display_name or candidate_display_name(c.raw_title),
                "score": c.investment_score,
                "url": c.raw_url,
                "low_confidence": c.is_low_confidence,
            }
            for c in winners
        ],
    }


@app.get("/api/companies")
def list_companies(db: Session = Depends(get_db)):
    companies = db.scalars(select(Company).options(selectinload(Company.candidates)).order_by(Company.display_name)).all()
    hints = dict(db.execute(select(OpportunityCompany.name, OpportunityCompany.supplier_type)).all())
    return {
        "companies": [company_payload(c, supplier_type_hint=hints.get(c.name)) for c in companies],
        "industries": list(PERSONAS),
        "candidate_count": sum(len(c.candidates) for c in companies),
        "retryable_observation_count": retryable_observation_count(db),
    }


@app.patch("/api/companies/{company_id}/industry")
def set_industry(company_id: int, update: IndustryUpdate, db: Session = Depends(get_db)):
    if update.industry not in PERSONAS:
        raise HTTPException(422, f"Industry must be one of: {', '.join(PERSONAS)}")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Company not found")
    company.industry = update.industry
    db.commit()
    db.refresh(company)
    hint = db.scalar(select(OpportunityCompany.supplier_type).where(OpportunityCompany.name == company.name))
    return company_payload(company, supplier_type_hint=hint)


@app.delete("/api/companies/{company_id}")
def delete_company_endpoint(company_id: int, db: Session = Depends(get_db)):
    """Permanently erase one company and all of its candidates/observations. No undo."""
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Company not found")
    delete_company(db, company_id)
    db.commit()
    return {"deleted": True, "company_id": company_id}


@app.delete("/api/candidates/{candidate_id}")
def delete_candidate_endpoint(candidate_id: int, db: Session = Depends(get_db)):
    """Permanently erase one person/candidate and their observations. No undo."""
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    company_id = delete_candidate(db, candidate_id)
    db.commit()
    return {"deleted": True, "candidate_id": candidate_id, "company_id": company_id}


@app.delete("/api/admin/wipe-all")
def wipe_all_endpoint(confirm: str = "", db: Session = Depends(get_db)):
    """Permanently erase every company, candidate, observation, and job.
    Requires ?confirm=DELETE to avoid accidental wipes. No undo."""
    if confirm != "DELETE":
        raise HTTPException(400, "Pass ?confirm=DELETE to confirm this irreversible action.")
    wipe_all_data(db)
    db.commit()
    return {"wiped": True}



@app.post("/api/jobs/rerun-pending")
def rerun_pending_batch(background_tasks: BackgroundTasks):
    with SessionLocal.begin() as db:
        observation_ids = db.scalars(
            select(Observation.id)
            .where(Observation.processing_status.in_(["pending", "failed"]))
            .order_by(Observation.id)
        ).all()
        if not observation_ids:
            raise HTTPException(409, "No pending or failed candidate observations to rerun.")

        job = Job(status="running", total_candidates=len(observation_ids))
        db.add(job)
        db.flush()

        candidate_ids = db.scalars(
            select(Observation.candidate_id).where(Observation.id.in_(observation_ids)).distinct()
        ).all()
        db.execute(
            update(Observation)
            .where(Observation.id.in_(observation_ids))
            .values(job_id=job.id, processing_status="pending")
        )
        db.execute(
            update(Candidate)
            .where(Candidate.id.in_(candidate_ids), Candidate.processing_status.in_(["pending", "failed"]))
            .values(processing_status="pending", gemini_extraction_failed=False)
        )
        job_id = job.id

    background_tasks.add_task(process_job, job_id)
    return {"job_id": job_id, "rerun_candidates": len(observation_ids)}

@app.get("/api/jobs/{job_id}/status")
def job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    counts = dict(db.execute(select(Company.status, func.count()).group_by(Company.status)).all())
    return {
        "id": job.id,
        "status": job.status,
        "total_candidates": job.total_candidates,
        "processed_candidates": job.processed_candidates,
        "failed_candidates": job.failed_candidates,
        "message": job.message,
        "rpm_usage": rpm_usage(),
        "rpm_limit": 15,
        "companies_resolved": counts.get("resolved_90", 0) + counts.get("resolved_85_fallback", 0),
        "companies_pending": counts.get("needs_next_round", 0),
    }


@app.get("/api/exports/still-needed.csv")
def export_still_needed(db: Session = Depends(get_db)):
    return Response(
        still_needed_csv(db),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="still-needed.csv"'},
    )


@app.get("/api/exports/final.csv")
def export_final(forced: bool = False, db: Session = Depends(get_db)):
    return Response(
        final_csv(db, forced=forced),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="decision-makers-final.csv"'},
    )

@app.get("/api/exports/audit.csv")
def export_audit(db: Session = Depends(get_db)):
    return Response(
        audit_csv(db),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="full-candidate-audit.csv"'},
    )


@app.post("/api/exports/merged.csv")
async def export_merged(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Feature B: upload the people CSV (first_name, last_name, company_name,
    company_url, email, linkedin_url) and immediately get back the merged
    operational CSV -- this app's opportunity-scoring data plus winner-
    candidate role/LinkedIn URL, joined in by company name. Read-only:
    nothing in the existing pipeline (scoring, rounds, status) is touched."""
    records = parse_people_upload(await file.read())
    return Response(
        merged_csv(db, records),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="merged-operational.csv"'},
    )