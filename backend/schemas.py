from typing import Literal
import re

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator


class UploadRecord(BaseModel):
    search_company: str = Field(min_length=1)
    search_role: str = Field(min_length=1)
    search_location: str = ""
    position: int = Field(ge=1)
    title: str
    snippet: str
    url: HttpUrl

    @field_validator("search_company", "search_role")
    @classmethod
    def strip_required(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("search_location", mode="before")
    @classmethod
    def normalize_location(cls, value):
        # Round 3+ searches (General Manager, Director of Operations) are
        # location-agnostic, so the scraper may send null or omit this field
        # entirely. A "before" validator intercepts the raw value ahead of
        # str type-checking, so None no longer crashes the whole upload --
        # it's just treated as "no location". classify_location() already
        # treats a blank target as "absent", which is the correct, harmless
        # outcome for those rounds. This doesn't relax round 1/2 uploads in
        # any way that matters in practice: a real boss scrape for those
        # rounds still sends a real location string, which passes through
        # unchanged.
        if value is None:
            return ""
        return " ".join(str(value).split())


class DomainRecord(BaseModel):
    company_name: str = Field(min_length=1, validation_alias=AliasChoices("company_name", "company"))
    domain: str = Field(
        min_length=1, validation_alias=AliasChoices("domain", "company_domain", "website", "url")
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("company_name")
    @classmethod
    def strip_company_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value):
        value = value.strip().lower()
        if not value:
            raise ValueError("must not be blank")
        # Accept either a bare domain ("acme.com") or a full URL
        # ("https://www.acme.com/about") -- strip protocol, leading "www.",
        # and any path/query so both forms land on the same value.
        value = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", value)
        value = value.split("/", 1)[0]
        value = value.split("?", 1)[0]
        if value.startswith("www."):
            value = value[4:]
        if not value:
            raise ValueError("must not be blank")
        return value


class OpportunityRecord(BaseModel):
    """One row from the boss's opportunity-scoring CSV (Company Name, Company
    Opportunity Score, City, State, Supplier Type, Job Role, AI Insight, ...).
    Field names use the literal CSV headers as aliases since this comes
    straight from a csv.DictReader, not hand-written JSON."""

    company_name: str = Field(min_length=1, validation_alias=AliasChoices("Company Name", "company_name"))
    opportunity_score: float | None = Field(
        default=None, validation_alias=AliasChoices("Company Opportunity Score", "opportunity_score")
    )
    city: str = Field(default="", validation_alias=AliasChoices("City", "city"))
    state: str = Field(default="", validation_alias=AliasChoices("State", "state"))
    supplier_type: str = Field(default="", validation_alias=AliasChoices("Supplier Type", "supplier_type"))
    job_role: str = Field(default="", validation_alias=AliasChoices("Job Role", "job_role"))
    ai_insight: str = Field(default="", validation_alias=AliasChoices("AI Insight", "ai_insight"))
    contact_details: str = Field(default="", validation_alias=AliasChoices("Contact Details", "contact_details"))

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("company_name")
    @classmethod
    def strip_company_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("opportunity_score", mode="before")
    @classmethod
    def blank_score_to_none(cls, value):
        # The CSV can hand us "", None, or a numeric string depending on the
        # exporting tool -- only an actual blank should become None; a real
        # numeric string still needs to parse as a number afterward.
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("city", "state", "supplier_type", "job_role", "ai_insight", "contact_details", mode="before")
    @classmethod
    def blank_string_field(cls, value):
        if value is None:
            return ""
        return str(value).strip()

    def primary_supplier_type(self):
        """First ';'-separated Supplier Type value, used to pick the round
        sequence from personas.json. Picking the FIRST one is a deliberate,
        simple tiebreak for companies with multiple supplier types -- not an
        attempt to rank them by relevance."""
        first = self.supplier_type.split(";")[0].strip()
        return first

    def primary_city(self):
        return self.city.split(";")[0].strip()

    def primary_state(self):
        return self.state.split(";")[0].strip()


class PersonRecord(BaseModel):
    """One row from the people CSV: first_name, last_name, company_name,
    company_url, email, linkedin_url. The linkedin_url here is read but
    NOT used in the merged export -- role + linkedin_url in the final CSV
    always come from the matched winner Candidate instead (see
    build_merged_rows), so this field exists only for completeness/future use."""

    first_name: str = Field(default="", validation_alias=AliasChoices("first_name", "First Name"))
    last_name: str = Field(default="", validation_alias=AliasChoices("last_name", "Last Name"))
    company_name: str = Field(min_length=1, validation_alias=AliasChoices("company_name", "Company Name"))
    company_url: str = Field(default="", validation_alias=AliasChoices("company_url", "Company URL"))
    email: str = Field(default="", validation_alias=AliasChoices("email", "Email"))
    linkedin_url: str = Field(default="", validation_alias=AliasChoices("linkedin_url", "LinkedIn URL"))

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("company_name")
    @classmethod
    def strip_company_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("first_name", "last_name", "company_url", "email", "linkedin_url", mode="before")
    @classmethod
    def blank_string_field(cls, value):
        if value is None:
            return ""
        return str(value).strip()

    def full_name(self):
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p)


class GeminiItem(BaseModel):
    url: str
    person_name: str = ""
    companies_found: list[str] = Field(default_factory=list)
    titles_found: list[str] = Field(default_factory=list)
    locations_found: list[str] = Field(default_factory=list)
    employment_indicators: list[str] = Field(default_factory=list)
    raw_employment_status: Literal["current", "former", "unclear"] = "unclear"


class GeminiBatch(BaseModel):
    results: list[GeminiItem]


class IndustryUpdate(BaseModel):
    industry: str


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    display_name: str
    industry: str
    status: str
    rounds_completed: int
    roles_tried: list[str]
    next_role: str | None
    winners: list[dict]