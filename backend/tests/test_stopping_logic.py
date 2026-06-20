from types import SimpleNamespace

from backend.stopping_logic import decide_company


def candidate(id, score, round_number=1, position=1):
    return SimpleNamespace(id=id, investment_score=score, round_number=round_number, position=position)


def test_resolves_90_as_soon_as_two_clear_primary():
    result = decide_company([candidate(1, 95), candidate(2, 90), candidate(3, 89)], 2)
    assert result.status == "resolved_90"
    assert result.winner_ids == [1, 2]


def test_does_not_fallback_to_85_early():
    result = decide_company([candidate(1, 89), candidate(2, 87)], 3)
    assert result.status == "needs_next_round"
    assert result.winner_ids == []


def test_resolves_85_fallback_only_at_max_rounds():
    result = decide_company([candidate(1, 89), candidate(2, 85)], 4)
    assert result.status == "resolved_85_fallback"
    assert result.winner_ids == [1, 2]


def test_exhausted_keeps_any_candidate_at_85():
    result = decide_company([candidate(1, 86), candidate(2, 60)], 4)
    assert result.status == "exhausted"
    assert result.winner_ids == [1]
    assert result.low_confidence_ids == []


def test_exhausted_flags_single_best_below_85_as_low_confidence():
    result = decide_company([candidate(1, 40), candidate(2, 70)], 4)
    assert result.status == "exhausted"
    assert result.winner_ids == [2]
    assert result.low_confidence_ids == [2]


def test_tie_breaks_by_round_then_position():
    result = decide_company(
        [candidate(1, 91, 2, 1), candidate(2, 91, 1, 4), candidate(3, 91, 1, 2)], 2
    )
    assert result.winner_ids == [3, 2]

