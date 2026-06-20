from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATABASE_URL = f"sqlite:///{(BASE_DIR / 'decision_makers.db').as_posix()}"

PRIMARY_THRESHOLD = 90
FALLBACK_THRESHOLD = 85
MAX_ROUNDS = 4
GEMINI_BATCH_SIZE = 5
GEMINI_RPM = 14
GEMINI_WINDOW_SECONDS = 60.0
GEMINI_MAX_ATTEMPTS = 3
GEMINI_MODEL = "gemini-3.1-flash-lite"

SIGNAL_VALUES = {
    "company_match": {"exact": 1.0, "partial": 0.5, "absent": 0.0},
    "role_match": {"exact": 1.0, "related": 0.6, "absent": 0.0},
    "location_match": {
        "city": 1.0,
        "metro": 0.8,
        "state": 0.6,
        "country_only": 0.2,
        "absent": 0.0,
    },
}
RETRIEVAL_WEIGHTS = {"company_match": 0.5, "role_match": 0.35, "location_match": 0.15}

