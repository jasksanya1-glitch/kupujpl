# kupujpl

Backend and tooling for [kupujpl.pl](https://kupujpl.pl).

## Structure

- `backend/app/` — FastAPI application
- `backend/scripts/` — maintenance and audit scripts
- `backend/tools/` — local workers and deployment helpers

## Local setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy example env files before running workers locally.
