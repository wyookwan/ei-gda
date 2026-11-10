# EI-GDA V16: Domain-Adaptive Governance Assessment Platform

One shared core, eight Test Suites, and domain packs for Justice, Education, Healthcare & EMS, Local Government, and General. Domain, use case, data, and risk change the controls, evidence, and rubric that an assessment actually uses.

**Status: beta.** Domain packs are pilot drafts and the registry has not had legal review, so results show governance readiness and not legal compliance.

Docs: [audit](docs/V16_SYSTEM_AUDIT.md) · [architecture](docs/V16_ARCHITECTURE.md) · [taxonomy](docs/V16_DOMAIN_TAXONOMY.md) · [regulatory model](docs/V16_REGULATORY_MODEL.md) · [workflow](docs/V16_ASSESSMENT_WORKFLOW.md) · [migration](docs/V16_MIGRATION_GUIDE.md) · [changelog](docs/V16_CHANGELOG.md)

## Local run

Tested on Python 3.13. The Dockerfile uses 3.11.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set SECRET_KEY, MySQL, and model values
python migrate_v16_domain_engine.py
python app.py               # http://127.0.0.1:5000
```

For a new database or an upgrade, follow the [migration guide](docs/V16_MIGRATION_GUIDE.md).

## Docker

```bash
cp .env.example .env        # set strong values, and MYSQL_HOST=db
docker compose build && docker compose up -d
docker compose exec web python seed.py                       # new database only
docker compose exec web python migrate_v16_domain_engine.py  # after seed
```

`AUTO_MIGRATE=True` runs the migrations on startup. The Docker image build has **not** been executed for V16, because the Docker daemon was not running. Only `docker compose config` was checked.

## Configuration added in V16

| Variable | Purpose |
|---|---|
| `ADMIN_LOGIN_ALIAS` | Optional shortcut username for the first admin. Empty disables it |
| `SESSION_COOKIE_SECURE` | Set True on HTTPS |
| `LOCAL_MODEL_TOKEN_CAP` | Upper limit for `LOCAL_MODEL_MAX_TOKENS`. Default 3500 |

Routing is unchanged: Open documents go to Gemini, Confidential documents to the local model only.

To edit domains, change `domain_packs/v16/*.json` and re-run the migration. To verify a law, use `/regulations` as an admin. To review findings, an admin or assigned committee member uses the results page.

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py'

# DOM tests, using jsdom from your own install
PYTHONPATH=.:tests python tests/render_report_fixture.py /tmp/report.html
NODE_PATH=<node_modules> node tests/test_report.cjs /tmp/report.html
PYTHONPATH=.:tests python tests/render_dashboard_fixture.py /tmp/dashboard.html
NODE_PATH=<node_modules> node tests/test_dashboard.cjs /tmp/dashboard.html

# Browser E2E on a temporary SQLite database; never touches MySQL. Needs Chrome.
pip install -r requirements-dev.txt
python tests/e2e/serve_e2e.py /tmp/e2e 5116 &
python tests/e2e/run_e2e.py http://127.0.0.1:5116 /tmp/e2e/shots
```

E2E sends synthetic text to the configured local model if it is reachable.

## Known limitations

- EMS taxonomy is provisional because no source documents were available. All controls await expert review.
- No registry entry is expert-verified, so compliance reads "not determined" until people verify it.
- Evidence location is keyword-based. There is no OCR and no separate Document KG.
- Access is per user. There is no organization entity or tenant isolation.
- Assessment runs synchronously, so a long run keeps the request open.
- Older pages (classic dashboard, committee, admin) inherit the new shell but keep their inner layouts.

See the [audit](docs/V16_SYSTEM_AUDIT.md) for open security items.
