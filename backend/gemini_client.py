import json
import os
import re

from dotenv import load_dotenv

from .config import GEMINI_MODEL
from .schemas import GeminiBatch

load_dotenv()

SYSTEM_PROMPT = """You extract independent matching signals for LinkedIn search results.
Return only JSON matching the requested schema. Never score, rank, recommend, keep, or reject anyone.

Definitions:
- company_match: "exact" if the target company name (or an unambiguous variant/abbreviation) appears clearly associated with the person's current or past role in the snippet/title; "partial" for weak/ambiguous association such as one mention without clear role linkage; "absent" if it does not appear.
- role_match: "exact" if the person holds the target search_role or a title containing it; "related" for a clearly adjacent operational/leadership title; "absent" if nothing operational/relevant appears.
- location_match: best evidence relative to search_location (a US state): "city" for a specific city in that state, "metro" for a named metro within/near it, "state" for just the state, "country_only" for only United States, or "absent".
- employment_status: "current" for a present role at the target company (Present, no end date, or current phrasing); "former" for a clear end date or past framing; "unclear" otherwise.
- name_company_collision: true only if the person's name shares a word with the target company and there is no other positive company-association evidence; false otherwise.

Treat every array item independently. Echo its url exactly. Do not infer one item's context from another."""


def _strip_fences(text):
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)


class GeminiExtractor:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env before processing an upload.")
        from google import genai

        self.client = genai.Client(api_key=api_key)

    async def extract(self, items):
        from google.genai import types

        payload = [
            {
                "url": item.url,
                "title": item.raw_title,
                "snippet": item.raw_snippet,
                "search_company": item.company.display_name if hasattr(item, "company") else item.search_company,
                "search_role": item.search_role,
                "search_location": item.search_location,
            }
            for item in items
        ]
        response = await self.client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=GeminiBatch,
                temperature=0,
            ),
        )
        if not response.text:
            raise ValueError("Gemini returned an empty response")
        print("Gemini result:", response.text, flush=True)
        return GeminiBatch.model_validate_json(_strip_fences(response.text)).results
