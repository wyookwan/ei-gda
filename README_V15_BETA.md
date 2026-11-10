# EI-GDA V15-beta.1 · Domain Assurance Portal

Built on the user-supplied V14.3 Flask/MySQL source; existing model scoring, Hybrid KG, test suites, PDFs, committee review, ThaiD and Docker remain in place.

## Key enhancements
- `/domains`: responsive cross-sector portal, 5 domain packs (general, justice, education, healthcare/EMS, local government).
- `/domains/<slug>`: domain workspace with subtypes, draft control catalogue, evidence checklist and candidate references.
- `/dashboard?domain=<slug>`: selects assessment context; persists subtype and AI use-case to `document_checks`.
- `/check/<id>/domain-review`: owner/admin manual evidence status, coverage calculation, critical evidence list; audit logged.
- `/domain_packs/*.json`: versioned declarative control profiles. Update/validate with domain experts before operational legal use.
- Historical assessments remain `general` by default. `migrate_v15_domains.py` uses additive schema changes; no reset needed.
- Seed script no longer rewrites passwords or stores plaintext passwords. For a *new* database, pass `EIGDA_ADMIN_PASSWORD` and `EIGDA_COMMITTEE_PASSWORD` to seed.

## Local install (Python 3.11 + MySQL 8.4)
1. Create an empty MySQL DB/user and grant access to it.
2. Copy `.env.example` to `.env`; set `SECRET_KEY`, `MYSQL_HOST=127.0.0.1`, `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`, `EIGDA_ADMIN_PASSWORD`, and model settings. Do not use demo defaults in production.
3. `python3.11 -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
4. `pip install -r requirements.txt`
5. `python migrate_v15_domains.py`
6. **Only for new installations:** `python seed.py` (without `--clear`). For existing V14 databases, skip seed to preserve custom catalog; optionally `python update_international_catalog.py --apply` if appropriate.
7. `python app.py`, then visit `http://127.0.0.1:5000/login`, sign in and open `Domain Portal`.

## Docker (recommended)
1. Copy `.env.example` to `.env`, configure strong passwords, `EIGDA_ADMIN_PASSWORD`, `EIGDA_COMMITTEE_PASSWORD`, `SECRET_KEY`, model endpoints and credentials. Set `APP_BIND_ADDRESS` and `APP_PORT` as needed.
2. `docker compose build && docker compose up -d`
3. `AUTO_MIGRATE=True` runs the V14 and V15 migrations automatically on startup; optionally verify with `docker compose exec web python migrate_v15_domains.py`
4. **Fresh install only:** `docker compose exec web python seed.py`
5. Open `http://127.0.0.1:5000` (or configured host/port). Use `docker compose logs -f web` to inspect issues.

## Upgrading an existing V14.3 installation
- Back up DB and uploads. Use the *same* MySQL database and application secret.
- Replace application source with V15; keep `.env`, existing database, uploads and report volumes.
- Run `python migrate_v15_domains.py` once before serving requests; it is safe to repeat.
- Do **not** use `seed.py --clear`, and do not re-seed unless intentionally refreshing catalog.

## Data privacy / model routing
The existing V14 behavior remains: **Open** PDFs use configured Gemini, **Confidential** PDFs use local model only, with no automatic cloud fallback. No AI assessment can run until the appropriate model endpoint is configured. Domain manual evidence review requires no AI key. Domain slug and subtype are saved with each assessment; it does not introduce multi-tenant database isolation or domain-level authorization.

## Limitations and roadmap
- These domain packs are *pilot drafts*, not authoritative legal mapping or sector accreditation. Legal applicability, dates and citations require expert verification.
- No new domain-specific AI benchmark execution, legal reasoning agent, automatic legal amendments feed, per-sector validated scoring rubric, production tenant isolation, or regulatory certification is claimed.
- Evidence coverage is manually entered; `N/A` requires a typed justification in the UI but is not independently legally validated.
- The original KG/scoring engine operates on standards selected in the existing Test Suite workflow; V15 domain pack content does **not** silently modify scores or introduce fictitious compliance results.
- Before public deployment, review CSRF protection, account policy, confidential storage encryption and access-control boundaries; seeded demo accounts are not suitable for production.

## Tests
`python -m unittest discover -s tests -p 'test_*.py'`

V15-specific tests: `python -m unittest tests.test_domain_service`

## Verification note
The project was statically checked and domain-pack unit tests were executed. Full Flask/MySQL/Docker integration tests require external dependencies and MySQL, which were unavailable in the packaging runtime; do not interpret unit success as proof of production readiness.
