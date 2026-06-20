from types import SimpleNamespace

from backend.csv_export import audit_csv


class ScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _statement):
        return ScalarResult(self.rows)


def test_audit_csv_includes_all_requested_columns_and_raw_signals():
    company = SimpleNamespace(display_name="Acme", status="needs_next_round")
    candidate = SimpleNamespace(
        company=company,
        display_name="Jane Doe",
        round_number=2,
        search_role="CFO",
        search_location="Austin, TX",
        raw_title="Jane Doe - CFO at Acme",
        raw_snippet="Raw Gemini-visible snippet",
        raw_url="https://linkedin.com/in/jane",
        gemini_company_match="exact",
        gemini_role_match="related",
        gemini_location_match="metro",
        gemini_employment_status="current",
        gemini_name_collision=False,
        retrieval_score=85,
        investment_score=90,
        times_seen=3,
        processing_status="scored",
        is_winner=True,
        rejection_reason=None,
    )

    lines = audit_csv(FakeDb([candidate])).splitlines()

    assert lines[0] == (
        "company_name,company_status,round_number,search_role,search_location,"
        "candidate_name,raw_title,raw_snippet,url,gemini_company_match,gemini_role_match,"
        "gemini_location_match,gemini_employment_status,gemini_name_collision,retrieval_score,"
        "investment_score,times_seen,processing_status,is_winner,rejection_reason"
    )
    assert "Acme,needs_next_round,2,CFO," in lines[1]
    assert "Jane Doe - CFO at Acme" in lines[1]
    assert ",exact,related,metro,current,false,85,90,3,scored,true," in lines[1]