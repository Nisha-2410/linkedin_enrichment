from backend.scoring import calculate_investment_score, calculate_retrieval_score, score_candidate


def test_natasha_high_confidence_fixture():
    result = score_candidate("exact", "exact", "city", "current", False, times_seen=1)
    assert result.retrieval_score == 100
    assert result.investment_score == 100


def test_rachel_former_or_irrelevant_fixture_is_zero():
    result = score_candidate("exact", "absent", "city", "former", False)
    assert result.retrieval_score == 0
    assert result.investment_score is None
    assert result.rejection_reason == "former employee"


def test_wesley_related_fixture_lands_between():
    result = score_candidate("exact", "related", "state", "current", False)
    assert result.retrieval_score == 80
    assert result.investment_score == 80


def test_formula_and_absent_location_penalty():
    retrieval, reason = calculate_retrieval_score("partial", "exact", "absent", "unclear", False)
    assert retrieval == 60
    assert reason is None
    assert calculate_investment_score(retrieval, "absent", 1) == 45


def test_corroboration_bonus_caps_at_fifteen():
    assert calculate_investment_score(80, "state", 2) == 85
    assert calculate_investment_score(80, "state", 20) == 95


def test_collision_hard_override():
    result = score_candidate("exact", "exact", "city", "current", True)
    assert result.retrieval_score == 0
    assert result.rejection_reason == "name/company collision false-positive"

