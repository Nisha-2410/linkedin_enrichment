from dataclasses import dataclass

from .config import LOCATION_AGNOSTIC_WEIGHTS, RETRIEVAL_WEIGHTS, SIGNAL_VALUES


@dataclass(frozen=True)
class ScoreResult:
    retrieval_score: float
    investment_score: float | None
    rejection_reason: str | None = None


def calculate_retrieval_score(
    company_match, role_match, location_match, employment_status, name_company_collision, location_agnostic=False
):
    if employment_status == "former":
        return 0.0, "former employee"
    if name_company_collision:
        return 0.0, "name/company collision false-positive"
    if location_agnostic:
        # Round 3+ (General Manager, Director of Operations): these are
        # company-wide senior roles, not tied to one office, so location is
        # dropped from the formula entirely -- not just down-weighted -- and
        # its 0.15 weight is redistributed onto company_match/role_match.
        values = {
            "company_match": SIGNAL_VALUES["company_match"][company_match],
            "role_match": SIGNAL_VALUES["role_match"][role_match],
        }
        score = 100 * sum(LOCATION_AGNOSTIC_WEIGHTS[key] * value for key, value in values.items())
        return round(score, 2), None
    values = {
        "company_match": SIGNAL_VALUES["company_match"][company_match],
        "role_match": SIGNAL_VALUES["role_match"][role_match],
        "location_match": SIGNAL_VALUES["location_match"][location_match],
    }
    score = 100 * sum(RETRIEVAL_WEIGHTS[key] * value for key, value in values.items())
    return round(score, 2), None


def calculate_investment_score(retrieval_score, location_match, times_seen, location_agnostic=False):
    if retrieval_score <= 0:
        return None
    # Skip the "absent" location penalty for round 3+ too -- location was
    # already excluded from the positive weight above, so penalizing it here
    # as well would silently undo the whole point of going location-agnostic.
    location_penalty = 0 if location_agnostic else (15 if location_match == "absent" else 0)
    corroboration_bonus = min(5, 2.5 * max(0, times_seen - 1))
    return round(max(0, min(100, retrieval_score - location_penalty + corroboration_bonus)), 2)


def score_candidate(
    company_match,
    role_match,
    location_match,
    employment_status,
    name_company_collision,
    times_seen=1,
    location_agnostic=False,
):
    retrieval, reason = calculate_retrieval_score(
        company_match, role_match, location_match, employment_status, name_company_collision, location_agnostic
    )
    return ScoreResult(
        retrieval, calculate_investment_score(retrieval, location_match, times_seen, location_agnostic), reason
    )