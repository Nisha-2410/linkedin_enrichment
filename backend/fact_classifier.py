import re


ROLE_RELATED_TERMS = {
    "operations": {"operations", "operator", "production", "manufacturing", "plant", "site", "general manager", "leader", "lead"},
    "manager": {"manager", "director", "head", "lead", "leader", "supervisor", "vp", "president", "chief", "executive"},
    "director": {"director", "head", "vp", "vice president", "chief", "executive", "manager"},
    "finance": {"finance", "financial", "cfo", "controller", "accounting", "treasury"},
    "sales": {"sales", "business development", "revenue", "commercial", "account executive"},
    "hr": {"human resources", "hr", "people", "talent", "recruiting"},
}

# Tokens that carry seniority/role-level meaning. A role phrase like "Warehouse
# Manager" is really {modifier: "warehouse", seniority: "manager"} -- matching
# only the modifier word ("warehouse" appears because the person is a
# "Warehouse Associate") tells you nothing about whether their actual level
# matches. classify_role() requires a seniority token (or one of its
# ROLE_RELATED_TERMS synonyms) to be present before ever returning "related";
# modifier-word overlap alone is never sufficient.
SENIORITY_TOKENS = {
    "manager", "director", "administrator", "supervisor", "head", "lead",
    "leader", "vp", "president", "chief", "executive", "officer",
}
FORMER_PATTERNS = [
    r"\bformer\b",
    r"\bpreviously\b",
    r"\bex[-\s]",
    r"\bpast\b",
    r"\buntil\s+\d{4}\b",
    r"\b\d{4}\s*[-–—]\s*(?:\d{4}|present)\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\s*[-–—]\s*(?!(?:present|current)\b)",
]
CURRENT_PATTERNS = [r"\bpresent\b", r"\bcurrent\b", r"\bcurrently\b", r"\bnow\b"]
COMPANY_SUFFIXES = {"company", "co", "inc", "llc", "ltd", "corp", "corporation", "group", "the"}


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def tokens(value):
    return [token for token in normalize(value).split() if token]


def compact(value):
    return "".join(tokens(value))


def text_blob(*parts):
    values = []
    for part in parts:
        if isinstance(part, list):
            values.extend(str(item) for item in part if item)
        elif part:
            values.append(str(part))
    return normalize(" ".join(values))


def classify_company(search_company, companies_found, raw_title="", raw_snippet=""):
    target = normalize(search_company)
    target_compact = compact(search_company)
    found = [normalize(company) for company in companies_found or [] if company]
    found_compact = [compact(company) for company in companies_found or [] if company]
    if target and (target in found or target_compact in found_compact):
        return "exact"
    if target_compact and any(target_compact in value or value in target_compact for value in found_compact if value):
        return "exact"
    raw = text_blob(raw_title, raw_snippet)
    if target and target in raw:
        return "partial"
    if target_compact and target_compact in compact(raw):
        return "partial"
    return "absent"


def classify_role(search_role, titles_found, raw_title="", raw_snippet=""):
    target = normalize(search_role)
    target_tokens = set(tokens(search_role))
    blob = text_blob(titles_found, raw_title, raw_snippet)
    blob_tokens = set(tokens(blob))

    if target and target in blob:
        return "exact"
    if target_tokens and target_tokens.issubset(blob_tokens):
        return "exact"

    # Split the target role into seniority tokens ("manager", "director", ...)
    # vs modifier tokens ("warehouse", "area", "regional", ...). A shared
    # modifier word alone (e.g. text says "Warehouse Associate" and the
    # target is "Warehouse Manager") is NOT evidence the seniority level
    # matches, so it must never by itself produce "related". We require
    # seniority evidence -- the literal seniority token, or one of its
    # ROLE_RELATED_TERMS synonyms -- before "related" is ever returned.
    seniority_target_tokens = target_tokens & SENIORITY_TOKENS
    modifier_target_tokens = target_tokens - SENIORITY_TOKENS

    # Literal seniority token match (e.g. target says "manager" and the text
    # also says "manager" somewhere) is strong evidence on its own.
    literal_seniority_match = bool(seniority_target_tokens & blob_tokens)

    seniority_synonyms = set()
    for token in seniority_target_tokens:
        seniority_synonyms.update(ROLE_RELATED_TERMS.get(token, set()))
    synonym_seniority_match = any(term in blob for term in seniority_synonyms)

    if literal_seniority_match:
        return "related"

    if synonym_seniority_match:
        # A generic seniority synonym (e.g. "director" standing in for
        # "manager") is weaker evidence on its own -- "Sales Director" should
        # not be flagged "related" to an unrelated "Area Manager" search just
        # because both are senior titles. Require the modifier word to also
        # match (e.g. target has no modifier, or the modifier appears too)
        # before accepting a cross-title seniority synonym as related.
        if not modifier_target_tokens or (modifier_target_tokens & blob_tokens):
            return "related"
        return "absent"

    return "absent"


def classify_location(search_location, locations_found, raw_title="", raw_snippet=""):
    target = normalize(search_location)
    locations = [normalize(location) for location in locations_found or [] if location]
    raw = text_blob(raw_title, raw_snippet)
    if not target:
        return "absent"
    for original, normalized in zip(locations_found or [], locations):
        original_text = str(original)
        if target in normalized:
            if "," in original_text or len(tokens(original_text)) > len(tokens(search_location)):
                return "city"
            return "state"
    if target in raw:
        # Apply the same city heuristic used for locations_found: if the raw
        # text contains a comma after the target (e.g. "Chicago, IL") or the
        # surrounding context has more tokens than the bare search term, it's
        # specific enough to be a city-level match, not just state/region.
        target_token_count = len(tokens(search_location))
        raw_tokens = tokens(raw)
        try:
            idx = next(
                i for i in range(len(raw_tokens))
                if " ".join(raw_tokens[i: i + target_token_count]) == target
            )
            context = " ".join(raw_tokens[idx: idx + target_token_count + 2])
            if "," in context or len(raw_tokens[idx: idx + target_token_count + 1]) > target_token_count:
                return "city"
        except StopIteration:
            pass
        return "state"
    if "united states" in raw or any("united states" in location for location in locations):
        return "country_only"
    return "absent"


def classify_employment_status(employment_indicators, raw_title="", raw_snippet=""):
    raw_blob = " ".join(str(part) for part in [*(employment_indicators or []), raw_title, raw_snippet] if part).lower()
    blob = text_blob(employment_indicators, raw_title, raw_snippet)
    if any(re.search(pattern, raw_blob, flags=re.IGNORECASE) for pattern in FORMER_PATTERNS):
        if "present" not in blob and "current" not in blob:
            return "former"
        # Date ranges with non-present endings are stronger than generic current wording elsewhere.
        if re.search(r"\b\d{4}\s*[-–—]\s*\d{4}\b", raw_blob):
            return "former"
    if any(re.search(pattern, blob, flags=re.IGNORECASE) for pattern in CURRENT_PATTERNS):
        return "current"
    return "unclear"


def classify_name_collision(person_name, search_company, company_match):
    if company_match != "absent":
        return False
    name_tokens = {token for token in tokens(person_name) if len(token) > 2}
    company_tokens = {token for token in tokens(search_company) if len(token) > 2 and token not in COMPANY_SUFFIXES}
    return bool(name_tokens and company_tokens and name_tokens.intersection(company_tokens))


def classify_observation(observation, facts):
    person_name = getattr(facts, "person_name", "") or ""
    companies_found = getattr(facts, "companies_found", []) or []
    titles_found = getattr(facts, "titles_found", []) or []
    locations_found = getattr(facts, "locations_found", []) or []
    employment_indicators = getattr(facts, "employment_indicators", []) or []
    raw_employment_status = getattr(facts, "raw_employment_status", "unclear") or "unclear"

    company_match = classify_company(observation.company.display_name, companies_found, observation.raw_title, observation.raw_snippet)
    role_match = classify_role(observation.search_role, titles_found, observation.raw_title, observation.raw_snippet)
    location_match = classify_location(observation.search_location, locations_found, observation.raw_title, observation.raw_snippet)
    employment_status = classify_employment_status(employment_indicators, observation.raw_title, observation.raw_snippet)
    name_collision = classify_name_collision(person_name, observation.company.display_name, company_match)

    return {
        "person_name": person_name,
        "companies_found": companies_found,
        "titles_found": titles_found,
        "locations_found": locations_found,
        "employment_indicators": employment_indicators,
        "raw_employment_status": raw_employment_status,
        "company_match": company_match,
        "role_match": role_match,
        "location_match": location_match,
        "employment_status": employment_status,
        "name_collision": name_collision,
    }