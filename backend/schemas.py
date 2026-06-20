from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class UploadRecord(BaseModel):
    search_company: str = Field(min_length=1)
    search_role: str = Field(min_length=1)
    search_location: str = Field(min_length=1)
    position: int = Field(ge=1)
    title: str
    snippet: str
    url: HttpUrl

    @field_validator("search_company", "search_role", "search_location")
    @classmethod
    def strip_required(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value


class GeminiItem(BaseModel):
    url: str
    company_match: Literal["exact", "partial", "absent"]
    role_match: Literal["exact", "related", "absent"]
    location_match: Literal["city", "metro", "state", "country_only", "absent"]
    employment_status: Literal["current", "former", "unclear"]
    name_company_collision: bool


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

