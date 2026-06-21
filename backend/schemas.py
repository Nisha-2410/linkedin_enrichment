from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


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