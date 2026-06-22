"""India phone pipeline -- validation, JSON ingestion, CSV export.

Two JSON feeds are supported:
  • IndiaMart  – boss uploads a JSON array scraped from IndiaMart.
                 Key fields: company_name, phone_number.
                 IndiaMart is always India so country check is skipped.
  • Serper     – boss uploads a JSON array from a Google Places/Serper scrape
                 for companies that IndiaMart missed.
                 Key fields: query (= the company name searched), phone,
                 country (used to reject non-India results like US/UK).

Phone acceptance rules (applied by _normalise_phone):
  1. Strip whitespace and common punctuation ( - . ( ) spaces ).
  2. Starts with +91 followed by exactly 10 digits  → ALWAYS accept,
     regardless of the country field AND regardless of the first digit.
     The explicit country code is authoritative -- this covers landlines
     with STD codes (e.g. Hyderabad's 040 in +91 40 2370 4832) as well as
     mobiles, and also covers a Serper result where Google mis-tagged the
     country as "United States" but the number itself is +91 XXXXXXXXXX.
  3. Starts with 91 (no +) followed by exactly 10 digits → same as rule 2,
     always accept regardless of first digit.
  4. Bare 10 digits with NO country-code prefix at all (no +91/91):
     IndiaMart: accepted unconditionally -- the source is authoritative.
     Serper/other: must start with 6-9 (mobile prefix, the only signal
     available with no country code to lean on) AND country must be
     blank / 'India' / 'IN'.
  5. Everything else → None (rejected).

Company matching uses a two-pass strategy:
  Pass 1 — exact: normalize_company() (lowercase + whitespace collapse).
  Pass 2 — suffix-stripped fuzzy: strip legal suffixes (Ltd, Pvt, Limited,
            Industries, …) from both sides then compare cores.  Matches that
            only survive pass 2 are logged as fuzzy_matches so the boss can
            spot-check them.
  The name->id lookup is cached across requests, but the cache stores only
  ids -- every match re-fetches the row via db.get() against the CALLER's
  own session, so results are never a stale/detached ORM object left over
  from an earlier request's session.

CSV output:
  phone_number is written as  +91XXXXXXXXXX  (string, always 13 chars).
  This prevents Excel from treating the 12-digit integer as scientific
  notation (9.18E+11).  The leading '+' makes Excel store it as text.
"""
import csv
import io
import re

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .india_models import IndiaOpportunityCompany, IndiaPhoneNumber
from .services import normalize_company


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[\s\-.()\u00a0]+")


def _clean(raw: str) -> str:
    """Remove common punctuation/spaces to get a digit-only (or +-prefixed) string."""
    return _STRIP_RE.sub("", raw.strip())


def _valid_10(digits: str) -> bool:
    """Indian MOBILE numbers start with 6, 7, 8, or 9. This check only
    applies to BARE 10-digit numbers with no country prefix at all, where
    there's no other signal to confirm it's Indian. It must never be applied
    to a number that already carries an explicit +91/91 prefix -- landline
    numbers (e.g. Hyderabad STD code 040: +91 40 2370 4832) are real,
    legitimate Indian numbers that start with 2-5, and the explicit country
    code is already proof enough that the number is Indian."""
    return len(digits) == 10 and digits.isdigit() and digits[0] in "6789"


def _normalise_phone(raw: str, country: str = "", is_indiamart: bool = False) -> str | None:
    """Return a 10-digit string if the number is a valid Indian number, else None.

    An explicit +91 or 91 prefix is ALWAYS accepted outright, regardless of
    source or first digit -- this covers both mobiles (6-9) and landlines
    with STD codes (0-5), since the country code itself is the proof. The
    6-9 first-digit "_valid_10" check only ever applies to a BARE 10-digit
    number with no country prefix, where it's the only signal available
    that the number might be an Indian mobile.
    IndiaMart rule: a bare 10-digit number is accepted unconditionally too --
    the source itself is authoritative, so no first-digit check is needed.
    For Serper/other sources, a bare 10-digit number additionally requires
    the country field to say India.
    """
    if not raw:
        return None
    cleaned = _clean(raw)

    # Rule 2: explicit +91 prefix → always accept, any 10 digits (mobile or landline)
    if cleaned.startswith("+91") and len(cleaned) == 13:
        digits = cleaned[3:]
        if digits.isdigit():
            return digits

    # Rule 3: 91 without + (12 digits total) → always accept, any 10 digits
    if cleaned.startswith("91") and len(cleaned) == 12:
        digits = cleaned[2:]
        if digits.isdigit():
            return digits

    # Rule 4: bare 10 digits, no country code at all
    if len(cleaned) == 10 and cleaned.isdigit():
        # IndiaMart is always India -- accept any 10-digit number, no first-digit check
        if is_indiamart:
            return cleaned
        # Serper/other: require valid MOBILE prefix AND India country, since
        # there's no explicit country code to lean on for a landline here
        if _valid_10(cleaned):
            country_norm = (country or "").strip().lower()
            if country_norm in ("", "india", "in"):
                return cleaned
            return None  # non-India country with bare number → reject

    return None


# ---------------------------------------------------------------------------
# Company name matching -- two-pass (exact → suffix-stripped fuzzy)
# ---------------------------------------------------------------------------

# Legal / descriptive suffixes that routinely differ between a boss's typed
# name and a scraped IndiaMart name.  Sorted longest-first so "private limited"
# is stripped before "limited" when both could match.
_SUFFIXES = [
    "private limited", "pvt limited", "pvt ltd", "private ltd",
    "limited", "ltd", "pvt", "private",
    "llp", "llc", "inc", "incorporated",
    "industries", "industry",
    "enterprises", "enterprise",
    "solutions", "solution",
    "services", "service",
    "trading", "traders", "trader",
    "exports", "export",
    "imports", "import",
    "international", "india",
    "group", "co", "company",
    "& co", "and co",
]

_PUNCT_RE = re.compile(r"[^\w\s]")


def _core(name: str) -> str:
    """Return the 'core' of a company name: lowercase, punctuation removed,
    legal suffixes stripped from the right, whitespace collapsed.

    Examples:
      "Watrana Rentals Limited"  -> "watrana rentals"
      "Watrana Rentals"          -> "watrana rentals"
      "Acme Pvt. Ltd."           -> "acme"
      "Sharma & Sons Co."        -> "sharma sons"
    """
    s = _PUNCT_RE.sub(" ", name.lower())
    s = " ".join(s.split())
    # Strip suffixes greedily from the right, repeating until stable
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            if s == suffix:
                break  # don't strip if it's ALL that's left
            if s.endswith(" " + suffix):
                s = s[:-(len(suffix) + 1)].rstrip()
                changed = True
                break
    return s


# Module-level name cache -- built once per process on first use and kept in
# sync via _cache_add() / _cache_clear().
#
# IMPORTANT: this cache stores only primary-key ints, never ORM row objects.
# Each upload request opens its own short-lived SessionLocal and closes it
# when the request ends. If the cache held the actual IndiaOpportunityCompany
# row from request #1's session, that row becomes "detached" the moment
# request #1 finishes -- any attribute not already loaded into memory (like
# the lazy `phone` relationship) then raises DetachedInstanceError as soon as
# request #2 tries to read it, even though the row still exists in the DB.
# Storing the id and re-fetching with db.get() against the CURRENT request's
# session avoids this entirely, at the cost of one cheap PK lookup per match.
#
# Keys: both the exact normalize_company() key and the _core() key for each
# row. A core key is only stored if it doesn't collide with an existing exact
# key, so exact matches always win.
_NAME_CACHE: dict[str, int] | None = None


def _build_cache(db) -> dict[str, int]:
    rows = db.scalars(select(IndiaOpportunityCompany)).all()
    cache: dict[str, int] = {}
    for row in rows:
        cache[row.name] = row.id                   # exact normalised key
        core = _core(row.display_name)
        if core and core not in cache:             # never shadow an exact key
            cache[core] = row.id
    return cache


def _get_cache(db) -> dict[str, int]:
    global _NAME_CACHE
    if _NAME_CACHE is None:
        _NAME_CACHE = _build_cache(db)
    return _NAME_CACHE


def _cache_add(row: IndiaOpportunityCompany) -> None:
    """Keep the cache in sync when a new IndiaOpportunityCompany is inserted."""
    global _NAME_CACHE
    if _NAME_CACHE is None:
        return
    _NAME_CACHE[row.name] = row.id
    core = _core(row.display_name)
    if core and core not in _NAME_CACHE:
        _NAME_CACHE[core] = row.id


def _cache_clear() -> None:
    """Invalidate the cache -- call after a wipe so the next request rebuilds."""
    global _NAME_CACHE
    _NAME_CACHE = None


def _match_company(db, company_name: str) -> tuple[IndiaOpportunityCompany | None, bool]:
    """Return (row, is_fuzzy).

    Pass 1 -- exact: normalize_company() key (lowercase + whitespace collapse).
    Pass 2 -- suffix-stripped: _core() of both sides must match exactly.

    is_fuzzy=True flags that pass 1 missed and pass 2 rescued it, so the
    caller can collect these in fuzzy_matches for the boss to spot-check.

    The row returned is always freshly loaded via db.get() against the
    CALLER's session (passed in as `db`) -- the cache only ever supplies an
    id, never a live ORM object, so the result is never detached regardless
    of which earlier request originally populated the cache.
    """
    cache = _get_cache(db)

    # Pass 1: exact normalised match
    exact_key = normalize_company(company_name)
    if exact_key in cache:
        row = db.get(IndiaOpportunityCompany, cache[exact_key])
        if row is not None:
            return row, False
        _cache_clear()  # stale id (row deleted since cache was built) -- force rebuild

    # Pass 2: suffix-stripped core match
    core_key = _core(company_name)
    if core_key and core_key in cache:
        row = db.get(IndiaOpportunityCompany, cache[core_key])
        if row is not None:
            return row, True
        _cache_clear()

    return None, False


# ---------------------------------------------------------------------------
# IndiaMart JSON ingestion
# ---------------------------------------------------------------------------

def apply_indiamart_phones(db, records: list[dict]) -> dict:
    """Ingest IndiaMart JSON array.

    Expected record shape:
      {
        "company_name": "Acme Supplies",
        "phone_number": "8018396219",   # bare 10-digit or +91-prefixed
        ...
      }

    Company-name field fallback order: company_name -> name -> business_name
    -> Company Name. Real-world scrapes don't always use the same key, so
    every plausible field is tried before giving up and counting the record
    as skipped_empty (rather than silently dropping it with no visibility).

    IndiaMart is always India -- no country field needed.
    Companies already having a phone are skipped.
    fuzzy_matches lists companies that matched only after suffix stripping
    so the boss can verify the pairing is correct.
    """
    matched = []
    fuzzy_matches = []
    already_filled = []
    rejected_phone = []
    unmatched = []
    skipped_empty = 0

    for record in records:
        company_name = (
            record.get("company_name")
            or record.get("name")
            or record.get("business_name")
            or record.get("Company Name")
            or ""
        ).strip()
        if not company_name:
            skipped_empty += 1
            continue

        india_co, is_fuzzy = _match_company(db, company_name)
        if not india_co:
            unmatched.append(company_name)
            continue

        if india_co.phone is not None:
            already_filled.append(company_name)
            continue

        raw_phone = str(
            record.get("phone_number")
            or record.get("phone")
            or record.get("mobile")
            or record.get("contact")
            or ""
        )
        normalised = _normalise_phone(raw_phone, country="india", is_indiamart=True)
        if not normalised:
            rejected_phone.append({"company": company_name, "raw": raw_phone})
            continue

        db.add(IndiaPhoneNumber(
            india_company_id=india_co.id,
            phone=normalised,
            source="indiamart",
            raw_value=raw_phone,
        ))
        matched.append(company_name)
        if is_fuzzy:
            fuzzy_matches.append({
                "scraped_name": company_name,
                "matched_to": india_co.display_name,
            })

    return {
        "total_records": len(records),
        "skipped_empty": skipped_empty,
        "matched": matched,
        "fuzzy_matches": fuzzy_matches,
        "already_filled": already_filled,
        "rejected_phone": rejected_phone,
        "unmatched": unmatched,
    }


# ---------------------------------------------------------------------------
# Serper JSON ingestion
# ---------------------------------------------------------------------------

def apply_serper_phones(db, records: list[dict]) -> dict:
    """Ingest Serper JSON array for companies IndiaMart missed.

    Expected record shape:
      {
        "query": "Express Global Logistics",   <- USE THIS for company matching
        "business_name": "...",
        "country": "India",                    <- used only for bare 10-digit numbers
        "phone": "+91 22 6633 9898",
        ...
      }

    Company-name field fallback order: query -> business_name -> company_name
    -> name. "query" is what the boss's Serper scraper searches for, so it's
    tried first, but some batches only carry business_name -- falling back
    to it (instead of dropping the record) catches records that would
    otherwise be silently skipped because the exact field name varied.

    CRITICAL RULE: if the phone has an explicit +91 prefix, it is accepted
    regardless of the country field.  Only bare 10-digit numbers need the
    country == India check.  This handles the real-world case where Serper/
    Google returns country="United States" (a mis-tagged result) but the
    actual phone number on the listing is +91 XXXXXXXXXX.
    fuzzy_matches lists companies matched only via suffix stripping.
    """
    matched = []
    fuzzy_matches = []
    already_filled = []
    rejected_phone = []
    rejected_country = []
    unmatched = []
    skipped_empty = 0

    for record in records:
        company_name = (
            record.get("query")
            or record.get("business_name")
            or record.get("company_name")
            or record.get("name")
            or ""
        ).strip()
        if not company_name:
            skipped_empty += 1
            continue

        india_co, is_fuzzy = _match_company(db, company_name)
        if not india_co:
            unmatched.append(company_name)
            continue

        if india_co.phone is not None:
            already_filled.append(company_name)
            continue

        raw_phone = str(record.get("phone") or record.get("phone_number") or "")
        country = str(record.get("country") or "")
        country_norm = country.strip().lower()

        cleaned = _STRIP_RE.sub("", raw_phone.strip())
        has_explicit_india_prefix = (
            (cleaned.startswith("+91") and len(cleaned) == 13) or
            (cleaned.startswith("91") and len(cleaned) == 12)
        )

        if not has_explicit_india_prefix and country_norm and country_norm not in ("india", "in", ""):
            rejected_country.append({
                "company": company_name,
                "business_name": record.get("business_name", ""),
                "country": country,
                "raw_phone": raw_phone,
            })
            continue

        normalised = _normalise_phone(raw_phone, country=country, is_indiamart=False)
        if not normalised:
            rejected_phone.append({"company": company_name, "raw": raw_phone})
            continue

        db.add(IndiaPhoneNumber(
            india_company_id=india_co.id,
            phone=normalised,
            source="serper",
            raw_value=raw_phone,
        ))
        matched.append(company_name)
        if is_fuzzy:
            fuzzy_matches.append({
                "scraped_name": company_name,
                "matched_to": india_co.display_name,
            })

    return {
        "total_records": len(records),
        "skipped_empty": skipped_empty,
        "matched": matched,
        "fuzzy_matches": fuzzy_matches,
        "already_filled": already_filled,
        "rejected_phone": rejected_phone,
        "rejected_country": rejected_country,
        "unmatched": unmatched,
    }


# ---------------------------------------------------------------------------
# "Still needed" list: companies without a phone yet
# ---------------------------------------------------------------------------

def india_companies_without_phone(db) -> list[dict]:
    """Return companies that still have no phone number after IndiaMart."""
    rows = db.scalars(
        select(IndiaOpportunityCompany)
        .outerjoin(IndiaOpportunityCompany.phone)
        .where(IndiaPhoneNumber.id.is_(None))
        .order_by(IndiaOpportunityCompany.display_name)
    ).all()
    return [{"company_name": r.display_name} for r in rows]


# ---------------------------------------------------------------------------
# India opportunity CSV ingestion
# ---------------------------------------------------------------------------

def apply_india_opportunity_records(db, records) -> dict:
    """Ingest the India opportunity-scoring CSV into IndiaOpportunityCompany."""
    _cache_clear()  # force rebuild so new rows are visible to _match_company
    created = []
    updated = []
    for record in records:
        key = normalize_company(record.company_name)
        india_co = db.scalar(select(IndiaOpportunityCompany).where(IndiaOpportunityCompany.name == key))
        is_new = india_co is None
        if is_new:
            india_co = IndiaOpportunityCompany(name=key, display_name=record.company_name)
            db.add(india_co)
            db.flush()          # get the PK so _cache_add works immediately
            _cache_add(india_co)

        india_co.opportunity_score = record.opportunity_score
        india_co.city = record.primary_city()
        india_co.state = record.primary_state()
        india_co.job_role_posted = record.job_role
        india_co.supplier_type = record.supplier_type
        india_co.ai_insight = record.ai_insight
        india_co.contact_details = record.contact_details

        (created if is_new else updated).append(india_co.display_name)

    return {"created": created, "updated": updated}


# ---------------------------------------------------------------------------
# India pipeline CSV export
# ---------------------------------------------------------------------------

def india_phone_csv(db) -> str:
    """Export the full India pipeline CSV.

    Columns:
      company_name, company_score, job_title, supplier_type, city, state,
      phone_number (+91 prefixed), contact_details, ai_insight, urgency.

    phone_number is ALWAYS written as  +91XXXXXXXXXX  (13-char string).
    This prevents Excel scientific-notation display (9.18E+11) because
    the leading '+' forces Excel to treat the cell as text.

    urgency = 'High' when score >= 80, else 'Normal'.
    """
    rows_orm = db.scalars(
        select(IndiaOpportunityCompany)
        .options(selectinload(IndiaOpportunityCompany.phone))
        .order_by(IndiaOpportunityCompany.display_name)
    ).all()

    fieldnames = [
        "company_name",
        "company_score",
        "job_title",
        "supplier_type",
        "city",
        "state",
        "phone_number",
        "contact_details",
        "ai_insight",
        "urgency",
    ]

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()

    for co in rows_orm:
        score = co.opportunity_score
        phone_display = f"+91{co.phone.phone}" if co.phone else ""
        urgency = "High" if (score is not None and score >= 80) else "Normal"
        writer.writerow({
            "company_name": co.display_name,
            "company_score": "" if score is None else score,
            "job_title": co.job_role_posted or "",
            "supplier_type": co.supplier_type or "",
            "city": co.city or "",
            "state": co.state or "",
            "phone_number": phone_display,
            "contact_details": co.contact_details or "",
            "ai_insight": co.ai_insight or "",
            "urgency": urgency,
        })

    return stream.getvalue()