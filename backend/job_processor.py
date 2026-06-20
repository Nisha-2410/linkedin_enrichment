import asyncio
import logging
import re
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .config import GEMINI_BATCH_SIZE, GEMINI_MAX_ATTEMPTS, GEMINI_RPM
from .db import SessionLocal
from .gemini_client import GeminiExtractor
from .models import Job, Observation
from .services import aggregate_candidate, normalize_url, update_company_decision

logger = logging.getLogger(__name__)
processor_lock = asyncio.Lock()
GEMINI_CALL_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# Fixed-interval rate limiter (same strategy as the working project).
# Enforces a minimum gap of (60 / RPM) seconds between every Gemini call,
# which prevents burst-firing and eliminates per-minute 429s entirely.
# ---------------------------------------------------------------------------
class FixedIntervalRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.interval = 60.0 / max(1, requests_per_minute)
        self._lock = asyncio.Lock()
        self._next_allowed_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed_at - now)
            if wait:
                await asyncio.sleep(wait)
            self._next_allowed_at = time.monotonic() + self.interval

    def usage(self) -> float:
        """Return seconds until the next call is allowed (0 = ready now)."""
        return max(0.0, self._next_allowed_at - time.monotonic())


rate_limiter = FixedIntervalRateLimiter(GEMINI_RPM)


# ---------------------------------------------------------------------------
# 429 helpers
# ---------------------------------------------------------------------------
def _is_daily_quota_exhausted(exc) -> bool:
    """True when the daily free-tier cap is hit — no retry will help today."""
    return "GenerateRequestsPerDayPerProjectPerModel" in str(exc)


def _parse_retry_delay(exc, default: float = 60.0) -> float:
    """Read the retryDelay Gemini embeds in the 429 body (e.g. '57s')."""
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(match.group(1)) if match else default


# ---------------------------------------------------------------------------
# Core call / retry logic
# ---------------------------------------------------------------------------
async def _call_with_retries(extractor, observations):
    error = None
    for attempt in range(GEMINI_MAX_ATTEMPTS):
        try:
            await rate_limiter.acquire()
            return await asyncio.wait_for(
                extractor.extract(observations), timeout=GEMINI_CALL_TIMEOUT_SECONDS
            )
        except Exception as exc:
            error = exc
            logger.warning("Gemini attempt %s failed: %s", attempt + 1, exc)

            # Daily cap — retrying is pointless, surface the error immediately.
            if _is_daily_quota_exhausted(exc):
                logger.error(
                    "Gemini daily quota exhausted. "
                    "Enable billing at https://ai.dev or wait until midnight UTC."
                )
                raise

            if attempt + 1 < GEMINI_MAX_ATTEMPTS:
                wait = _parse_retry_delay(exc)
                logger.info(
                    "Waiting %.1fs before retry %s (as requested by Gemini).",
                    wait, attempt + 2,
                )
                await asyncio.sleep(wait)
    raise error


async def _extract_complete(extractor, batch):
    """Return (successes_dict, failures_dict); retry model-omitted items one by one."""
    results = await _call_with_retries(extractor, batch)
    by_url = {normalize_url(r.url): r for r in results}
    complete = {}
    failures = {}
    for observation in batch:
        key = normalize_url(observation.url)
        if key in by_url:
            complete[observation.id] = by_url[key]
            continue
        logger.warning("Gemini omitted %s; retrying individually", observation.url)
        try:
            single = await _call_with_retries(extractor, [observation])
            match = next((r for r in single if normalize_url(r.url) == key), None)
            if not match:
                raise ValueError(f"Gemini repeatedly omitted URL: {observation.url}")
            complete[observation.id] = match
        except Exception as exc:
            failures[observation.id] = exc
    return complete, failures


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _load_batch(job_id):
    with SessionLocal() as db:
        rows = db.scalars(
            select(Observation)
            .options(joinedload(Observation.company))
            .where(Observation.job_id == job_id, Observation.processing_status == "pending")
            .order_by(Observation.id)
            .limit(GEMINI_BATCH_SIZE * 10)
        ).all()
        # URL is the required response-correlation key. Never put the same URL
        # into one mixed-company batch where that key would become ambiguous.
        unique_rows = []
        urls = set()
        for row in rows:
            if row.url in urls:
                continue
            unique_rows.append(row)
            urls.add(row.url)
            if len(unique_rows) == GEMINI_BATCH_SIZE:
                break
        for row in unique_rows:
            db.expunge(row)
        return unique_rows


def _persist_batch(job_id, batch, results=None, failures=None, failure=None):
    with SessionLocal.begin() as db:
        job = db.get(Job, job_id)
        touched_companies = set()
        for detached in batch:
            observation = db.get(Observation, detached.id)
            touched_companies.add(observation.company_id)
            item_failure = failure or (failures or {}).get(observation.id)
            if item_failure:
                observation.processing_status = "failed"
                job.failed_candidates += 1
            else:
                result = results[observation.id]
                observation.company_match = result.company_match
                observation.role_match = result.role_match
                observation.location_match = result.location_match
                observation.employment_status = result.employment_status
                observation.name_collision = result.name_company_collision
                observation.processing_status = "extracted"
            job.processed_candidates += 1
            aggregate_candidate(db, observation.candidate_id)
        for company_id in touched_companies:
            update_company_decision(db, company_id)
        if failure or failures:
            job.message = str(failure or next(iter(failures.values())))


# ---------------------------------------------------------------------------
# Job entry-point
# ---------------------------------------------------------------------------
async def process_job(job_id):
    async with processor_lock:
        try:
            extractor = GeminiExtractor()
            while batch := _load_batch(job_id):
                try:
                    results, failures = await _extract_complete(extractor, batch)
                    _persist_batch(job_id, batch, results=results, failures=failures)
                except Exception as exc:
                    logger.exception("Batch permanently failed")
                    _persist_batch(job_id, batch, failure=exc)
            with SessionLocal.begin() as db:
                job = db.get(Job, job_id)
                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            with SessionLocal.begin() as db:
                job = db.get(Job, job_id)
                job.status = "failed"
                job.message = str(exc)
                job.completed_at = datetime.now(timezone.utc)


def rpm_usage():
    """Seconds until the next Gemini call is allowed (0 = ready now)."""
    return rate_limiter.usage()