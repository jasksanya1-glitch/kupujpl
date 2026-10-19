# IGDB Game Discovery (local)

Isolated Quenly discovery — **never** writes production `games`/`offers`, never starts scanners, never deploys.

## Modes

```bash
cd backend
# Reports only
python tools/igdb_discovery/run_prototype.py --mode dry-run --limit 50

# Reports + isolated staging SQLite
python tools/igdb_discovery/run_prototype.py --mode stage --limit 50

pytest tests/test_igdb_discovery_prototype.py -q
```

Open: `reports/discovery_report.html`

## Env

Copy `backend/.env.igdb.example` → `backend/.env` (gitignored).

Commercial IGDB use requires approval from `partner@igdb.com` before production.
