# AGENTS.md

## Cursor Cloud specific instructions

### What this product is
`matrix-parser` is a single Python/Flask job-search automation app (Russian UI). A user submits a
job-search form (optionally uploading a resume), the request is dispatched to a Celery worker via
Redis, the worker scrapes/aggregates vacancies (LinkedIn/HeadHunter/mock) into PostgreSQL, and the
user views ranked results. There is no README; `app/config.py` is the source of truth for config.

### Services (all run locally; no Docker/Makefile/compose in this repo)
| Service | Required | Run command (from repo root, after `source venv/bin/activate` or use `./venv/bin/...`) |
|---|---|---|
| PostgreSQL 16 | yes (app raises `RuntimeError` at startup if `DATABASE_URL` unset; `/health` checks it) | `sudo pg_ctlcluster 16 main start` |
| Redis | yes (Celery broker/result backend + web dispatch) | `sudo redis-server /etc/redis/redis.conf --daemonize yes` |
| Flask web app (dev) | yes | `./venv/bin/python run.py` → http://0.0.0.0:5000 (debug reloader on) |
| Celery worker | yes for actual parsing | `./venv/bin/celery -A app.tasks:celery_app worker --loglevel=info` (queue name `celery`) |

Health check: `GET /health`. Main UI: `/job-search`. Requests list: `/job-requests`.

### Startup notes (services do NOT auto-start on VM boot)
- Start PostgreSQL and Redis manually each session with the commands above (systemd `service`/
  `invoke-rc.d` is denied in this container; `pg_ctlcluster` and `redis-server --daemonize` work).
- DB role/db already created and `init_db.py` already run in the snapshot: role `matrix` / password
  `matrix`, database `matrix_parser`. To recreate: `sudo -u postgres psql -c "CREATE USER matrix WITH PASSWORD 'matrix';"`,
  `sudo -u postgres psql -c "CREATE DATABASE matrix_parser OWNER matrix;"`, then `./venv/bin/python init_db.py`.
- `.env` is git-ignored and must exist (holds `DATABASE_URL`, `REDIS_URL`, source toggles). It is
  kept in the snapshot; if missing, recreate it with at least `DATABASE_URL=postgresql+psycopg2://matrix:matrix@127.0.0.1:5432/matrix_parser`.
- For local dev the `.env` sets `PARSER_DEFAULT_SOURCES=mock` and `ENABLE_MOCK_SOURCE=1` so the
  pipeline works without external scraping. `LINKEDIN_BROWSER_PROFILE_DIR` is overridden to a repo
  path (the config default points at a prod `/var/www/matrix-parser` path). Real LinkedIn/HH
  scraping additionally needs `./venv/bin/playwright install chromium` and a logged-in browser profile.

### KNOWN PRE-EXISTING BUG (blocks the Celery worker + one test)
`app/parser.py` line 7 does `from app.hh_source import HHSourceError, ...`, but `HHSourceError` is
**not defined anywhere** in `app/hh_source.py` (it only exists in `app/parser.py.bak_*`). The
`try/except ModuleNotFoundError` guard around that import does NOT catch this (a missing *name* raises
`ImportError`, not `ModuleNotFoundError`). Consequences:
- `celery -A app.tasks:celery_app worker` fails to load (`app.tasks` imports `app.parser`).
- `python -m unittest discover tests` fails `tests/test_finance_fpa_relevance.py` (loads `parser.py`).
The Flask web app itself is unaffected (routes don't import `parser` at module load), so form
submission, DB writes, and Redis dispatch all work; only worker consumption/parsing is blocked.
This is a code defect in the baseline, not an environment issue — do not paper over it during setup;
fix it in code (e.g. define `HHSourceError` in `app/hh_source.py` or broaden the except) if asked.

### Testing
- Tests use stdlib `unittest`: `./venv/bin/python -m unittest discover -s tests -v`.
- `tests/test_form_recommendation_agent.py` (3 tests) passes. `tests/test_finance_fpa_relevance.py`
  fails only due to the bug above.
- No linter/formatter config is present in the repo.

### Misc
- Many `*.bak_*` / `*.save` files sit next to real modules in `app/` and `app/templates/`; the live
  modules are the non-`.bak` versions.
