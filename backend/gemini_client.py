import json
import os
import re

from dotenv import load_dotenv

from .config import GEMINI_MODEL
from .schemas import GeminiBatch

load_dotenv()

SYSTEM_PROMPT = """You are an information extraction engine.

Your job is ONLY to extract factual information from LinkedIn search result titles and snippets.

You MUST NOT:

* score candidates
* rank candidates
* decide whether someone is a match
* decide whether a role is related
* decide whether a company matches
* decide whether a location matches

Only extract facts explicitly supported by the text.

Return JSON only.

For each input item return:

{
"url": "...",
"person_name": "...",
"companies_found": [],
"titles_found": [],
"locations_found": [],
"employment_indicators": [],
"raw_employment_status": "current | former | unclear"
}

Rules:

person_name:

* Extract the person's name if visible.
* Otherwise return "".

companies_found:

* List every company name explicitly mentioned.
* Do not normalize names.
* Preserve wording from the snippet.

titles_found:

* List every job title explicitly mentioned.
* Preserve wording.

locations_found:

* List every location explicitly mentioned.
* Preserve wording.

employment_indicators:

* Extract phrases that indicate employment timing.
* Examples:

  * "Present"
  * "Current"
  * "Apr 2025 - Present"
  * "2019 - 2024"
  * "Former"

raw_employment_status:

* "current" if the text clearly indicates a present role.
* "former" if the text clearly indicates a past role.
* "unclear" otherwise.

Treat every item independently.

Echo the url exactly.

Return only valid JSON matching the schema."""


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
        return GeminiBatch.model_validate_json(_strip_fences(response.text)).results
