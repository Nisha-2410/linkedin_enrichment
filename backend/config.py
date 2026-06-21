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

# Rounds 3+ search senior, company-wide roles (General Manager, Director of
# Operations) where location is not a meaningful signal -- those roles aren't
# tied to one office. From this round onward, location_match is dropped from
# the retrieval formula entirely (not just down-weighted), and its 0.15
# weight is redistributed proportionally onto company_match/role_match so the
# weights still sum to 1.0. The investment-score location penalty (-15 for
# location_match == "absent") is skipped for the same rounds, since punishing
# "absent" while also excluding location from the positive weight would
# silently undo the point of this rule.
LOCATION_AGNOSTIC_MIN_ROUND = 3

_LOCATION_AGNOSTIC_BASE = RETRIEVAL_WEIGHTS["company_match"] + RETRIEVAL_WEIGHTS["role_match"]
LOCATION_AGNOSTIC_WEIGHTS = {
    "company_match": RETRIEVAL_WEIGHTS["company_match"] / _LOCATION_AGNOSTIC_BASE,
    "role_match": RETRIEVAL_WEIGHTS["role_match"] / _LOCATION_AGNOSTIC_BASE,
}