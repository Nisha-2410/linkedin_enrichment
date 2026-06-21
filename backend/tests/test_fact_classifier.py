from types import SimpleNamespace

from backend.fact_classifier import (
    classify_company,
    classify_employment_status,
    classify_location,
    classify_observation,
    classify_role,
)


def test_company_match_is_deterministic_from_extracted_companies():
    assert classify_company("CFAN Company", ["C-FAN"], "", "") == "exact"
    assert classify_company("CFAN Company", [], "Jane Doe - CFAN Company", "") == "partial"
    assert classify_company("CFAN Company", ["Other Co"], "", "") == "absent"


def test_role_match_is_deterministic_from_titles():
    assert classify_role("Operations Manager", ["Operations Manager"]) == "exact"
    assert classify_role("Operations Manager", ["Manufacturing Director"]) == "related"
    assert classify_role("Operations Manager", ["Graphic Designer"]) == "absent"


def test_location_match_detects_state_and_specific_city():
    assert classify_location("Texas", ["San Marcos, Texas"]) == "city"
    assert classify_location("Texas", ["Texas"]) == "state"
    assert classify_location("Texas", ["United States"]) == "country_only"


def test_former_employee_detection_is_deterministic():
    assert classify_employment_status(["2019-2024"]) == "former"
    assert classify_employment_status(["Former Operations Manager"]) == "former"
    assert classify_employment_status(["Nov 2023 - Present"]) == "current"


def test_observation_classifier_turns_facts_into_scoring_inputs():
    observation = SimpleNamespace(
        company=SimpleNamespace(display_name="CFAN Company"),
        search_role="Operations Manager",
        search_location="Texas",
        raw_title="Rory Mitchell - Cell Leader at C-FAN",
        raw_snippet="San Marcos, Texas · CFAN Company · Nov 2023 - Present",
    )
    facts = SimpleNamespace(
        person_name="Rory Mitchell",
        companies_found=["C-FAN", "CFAN Company"],
        titles_found=["Cell Leader"],
        locations_found=["San Marcos, Texas"],
        employment_indicators=["Nov 2023 - Present"],
        raw_employment_status="current",
    )

    result = classify_observation(observation, facts)

    assert result["company_match"] == "exact"
    assert result["role_match"] == "related"
    assert result["location_match"] == "city"
    assert result["employment_status"] == "current"
    assert result["raw_employment_status"] == "current"
    assert result["name_collision"] is False