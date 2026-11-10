# EI-GDA V16 system audit

Audit of the V15-beta.1 source and the local `tnagf_db` database, done on 2026-11-05 before V16 changes. Each item was checked by reading code, querying the database, or running the system. V15 was kept unchanged in `Ei-GDA-V15-beta`.

## Baseline

| Check | Result |
|---|---|
| Stack | Flask 3, SQLAlchemy, MySQL 8, Jinja, Bootstrap 5, Chart.js, gunicorn, Docker |
| Python unit tests (V15) | 15 passed |
| Data | 5 users, 4 assessments, 5 evidence files, 8 Test Suites, 69 standards, 426 items |
| Committee data | 0 assignments, 0 reviews, so the workflow had never been exercised on this database |

## Existing and functioning

- Email login, roles (user, committee, admin), owner-based access checks.
- The eight Test Suites exist and are enabled. Display order differs from the TS numbering (`Risk` is shown 8th, `Application` 4th).
- PDF text extraction by page, keyword evidence location with file and page.
- Provider routing: Open goes to Gemini, Confidential to the local model, with no fallback between them.
- Hybrid score: `35% keyword + 15% keyword+evidence + 50% model`.
- Committee scoring pages and system-versus-committee comparison render. Their full flow had no real data to confirm it.
- Audit log and Docker files.

## Partially implemented

| Capability | What was actually found |
|---|---|
| Hybrid KG | A list of standard and item nodes with `contains` edges. "Hybrid" is keywords plus a model call. No graph database or traversal. |
| Domain Portal (V15) | 5 JSON packs with 3 to 4 controls each. Selecting a domain did **not** change controls, evidence, or scores. Only a label and manual status were stored. |
| Evidence Review (V15) | Manual statuses with a coverage percentage. No link to evidence files. |
| PDF reports | Generated, but **Thai text was lost**. `system_report_22.pdf` extracted as ` .pdf` for Thai file names because of the CID font. |
| CSRF | Only on domain review and suite reorder. |
| ThaiD | The app redirects correctly. On 2026-11-04 the provider rejected the request with `redirect or callback url mismatch`. Code and configuration match the last success (2026-09-23), so this needs a check on the provider side. Still open. |

## Missing

- **Document KG and Reference KG as separate graphs do not exist.** The brief assumed they did. Only the reference list above exists.
- Taxonomy, applicability logic, regulatory registry, domain rubrics, critical-control gates, configuration snapshots, guided workflow with save and resume.
- Organization entity and multi-tenant isolation. Users hold a free-text organization.
- OCR. Scanned PDFs yield no text.
- EMS source documents. No final report, TOR, or use-case specification is in the workspace, only the concept decks.

## Bugs and security concerns found

| Severity | Finding | V16 status |
|---|---|---|
| High | `/admin/users` displayed `users.password_plain` to admins | Fixed in the page |
| High | 2 rows in `users.password_plain` still hold plaintext passwords | **Open, needs your decision.** Clear with `--purge-plaintext-passwords` |
| High | Known default `SECRET_KEY` allows forged admin sessions | App now refuses to start |
| High | `DEBUG` defaulted to True | Default is now False |
| Medium | CSRF missing on almost all forms | Enforced on all POST requests |
| Medium | Reloading `/run-compliance` resent documents to a model | GET no longer re-runs a finished check |
| Medium | Hard-coded `adminbuu` login alias | Now optional, through `ADMIN_LOGIN_ALIAS`. Kept on in the local `.env` for compatibility |
| Medium | Thai text lost in PDF | Fixed with the bundled Sarabun font |
| Medium | Local model client failed when a reasoning model used its whole token budget | Batch now halves and retries, with a clear error |
| Low | Upload trusted the `.pdf` extension | Header is checked |
| Low | No registration password policy | Minimum 10 characters |

## Still open

- `LOCAL_MODEL_VERIFY_SSL` defaults to False. No login rate limiting. Logout uses GET. No Content-Security-Policy, because templates use inline scripts. Evidence files are not encrypted at rest.
- Keyword scoring keeps 50% of the V14 hybrid score. A document that only mentions terms can score 2.5 of 5. It was left unchanged so historical scores stay comparable.
- Items outside the top 50 keyword matches are scored by keywords alone in the V14 engine.

## Technical debt

- `app.py` holds most routes inside one 1,000-line function.
- Physical table `templates` still backs Test Suites. Legacy columns such as `completeness_score` and `password_plain` remain.
- `run-compliance` still accepts GET for the first run after a classic upload.
- Several minified single-line templates and stylesheets are hard to review.

## Migration requirements

Additive only: 12 new tables, plus `templates.suite_code` and `document_files.content_hash`. See [V16_MIGRATION_GUIDE.md](V16_MIGRATION_GUIDE.md).
