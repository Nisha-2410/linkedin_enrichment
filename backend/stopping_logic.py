from dataclasses import dataclass

from .config import FALLBACK_THRESHOLD, MAX_ROUNDS, PRIMARY_THRESHOLD


@dataclass(frozen=True)
class CompanyDecision:
    status: str
    winner_ids: list[int]
    low_confidence_ids: list[int]


def _rank(candidates):
    return sorted(
        [c for c in candidates if c.investment_score is not None and c.investment_score > 0],
        key=lambda c: (-c.investment_score, c.round_number, c.position),
    )


def decide_company(candidates, rounds_completed):
    ranked = _rank(candidates)
    primary = [c for c in ranked if c.investment_score >= PRIMARY_THRESHOLD]
    if len(primary) >= 2:
        return CompanyDecision("resolved_90", [c.id for c in primary[:2]], [])

    fallback = [c for c in ranked if c.investment_score >= FALLBACK_THRESHOLD]
    if len(fallback) >= 2 and rounds_completed >= MAX_ROUNDS:
        return CompanyDecision("resolved_85_fallback", [c.id for c in fallback[:2]], [])

    if rounds_completed >= MAX_ROUNDS:
        if fallback:
            return CompanyDecision("exhausted", [c.id for c in fallback[:2]], [])
        if ranked:
            return CompanyDecision("exhausted", [ranked[0].id], [ranked[0].id])
        return CompanyDecision("exhausted", [], [])
    return CompanyDecision("needs_next_round", [], [])
