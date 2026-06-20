# Decision Maker Discovery Engine

A persistent local FastAPI + React app for turning scraped LinkedIn search results into deterministic, auditable decision-maker selections. Gemini extracts structured evidence only; Python owns every score, threshold, rank, and stopping decision.

## Setup

Requirements: Python 3.11+ and Node.js 20+.

```powershell
cd decision_maker_engine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

Put your Gemini key in `.env`, then install the frontend once:

```powershell
cd frontend
npm install
cd ..
```

## Run both services together (recommended)

Install the root development dependency once:

```powershell
npm.cmd install
```

Then start the backend and frontend together:

```powershell
npm.cmd run dev
```

Open `http://localhost:5173`. Press `Ctrl+C` to stop both services.

## Run in two terminals (alternative)

Backend:

```powershell
cd decision_maker_engine
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --port 8000
```

Frontend:

```powershell
cd decision_maker_engine\frontend
npm run dev
```

Open `http://localhost:5173`. SQLite state is stored at `backend/decision_makers.db` and survives restarts. The backend resumes any job that was still marked running.

## Workflow

1. Drop a JSON array matching the specified scrape format into the upload panel.
2. Review the company/candidate/role preview and start extraction.
3. Watch job progress; processing continues in persisted batches of five under a shared rolling 15-RPM limiter.
4. Download **Still-Needed CSV** for the next scrape round, upload that round, and repeat.
5. Download **Final Decision Makers** at any time. Unresolved companies are explicitly marked as forced-finalized early.

Industry can be edited inline in the company table. It controls the next-role suggestion; unset companies use the default persona order.

## Tests

From `decision_maker_engine` with the virtual environment active:

```powershell
pytest backend\tests -q
```

The suite covers hand-computed scoring examples, every stop/continue branch (including no early 85 fallback), tie-breaking, hard rejection overrides, corroboration, and simulated rolling-window burst limiting.

## Configuration

All weights, thresholds, Gemini batch/model settings, RPM limits, and maximum rounds live in `backend/config.py`. Persona sequences live in `backend/personas.json`.
