> **Current version: V16 beta. Start with [README_V16.md](README_V16.md).** MHESI / OPS-MHESI pilot: [README_PILOT_MHESI.md](README_PILOT_MHESI.md). The sections below describe earlier versions.

# Ei-GDA V14

**Evidence-driven Intelligent Platform for Governance & Digital Assurance**

## V14.3 international standards catalog

The researched expansion adds 38 references and 208 public-scope readiness items,
with source links, evidence suggestions, explicit draft status and a metadata-only
development watchlist. See [research, coverage and update instructions](RESEARCH_SOURCES_V14_3.md).
For an existing installation use `python update_international_catalog.py --apply`;
this updates the catalog without running account seeding or resetting assessment history.

## What changed from V13

1. Rebranded platform from T-NAGF/TNAGF to **Ei-GDA**.
2. User-facing **Template** concept is replaced by **Test Suite**.
   - The physical MySQL table remains `templates` for backward compatibility.
   - Existing Test Suite ↔ Standard/Law/Guideline mappings are retained.
   - There is no document-completeness gate before compliance assessment.
3. Model routing follows document classification:
   - **Open** documents use Gemini, configured with `GEMINI_API_KEY` and `GEMINI_MODEL`.
   - **Confidential** documents use the local OpenAI-compatible model endpoint.
   - Confidential document content is never sent to Gemini, including when the local model fails.
4. Owner/Admin comparison workflow:
   - system result
   - committee review result(s)
   - item-level delta (`committee average - system score`)
   - committee comments and system evidence
5. Gap Analysis and Recommendation are grouped into a separate **tab for each selected reference**.
6. Docker and Git deployment files are prepared.
7. Added Colab integration notes in `README_COLAB.md`.

## Important compatibility note

Legacy columns such as `completeness_score` and the physical `templates` table are intentionally kept so an existing V13 database can be migrated without breaking foreign keys or historical assessments. They are no longer part of the active user workflow.

## Local run

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python migrate_v14_eigda.py
python seed.py
python check_v14.py
python app.py
```

Open: `http://127.0.0.1:5000`

## Existing V13 database

Run only:

```bash
python migrate_v14_eigda.py
```

The migration renames the five legacy `TNAGF-*` Test Suite records to their neutral Test Suite names while preserving IDs and framework mappings.

## Docker

```bash
cp .env.example .env
# Edit MYSQL passwords and optional ThaiD settings

docker compose build
docker compose up -d
docker compose exec web python migrate_v14_eigda.py
docker compose exec web python seed.py
```

Then open `http://SERVER-IP:5000`.

## Git safety

`.env`, uploaded PDFs, generated reports, Python virtual environments and local database artifacts are excluded through `.gitignore` / `.dockerignore`.


### Assessment workspace updates

- Admin → Test Suites supports drag-and-drop ordering, with accessible up/down buttons and automatic save. Dashboard, Explorer and Tree share this order. Existing deployments must run `python migrate_suite_order.py` once before using the new model; this adds `templates.display_order` without replacing suites or results.
- Users and admins can open `/test-suites/tree`, search references/items, and expand/collapse branches.
- `/check/<id>` now groups the report into overview charts, paginated assessment items with a full detail panel, and document/context information. Graphs support reference/category comparisons, score distribution and item heatmap, with drilldown to matching results. All categories remain available through pagination.
- Upload requires acknowledging Open/Confidential in the classification dialog before the existing final assessment confirmation. Open sends document text and evidence to Google Gemini API; Confidential uses the configured Local Model API and never falls back to Gemini. Classification does not publish documents.
- Verification: `python -m unittest discover -s tests -p 'test_*.py'`. DOM checks use `tests/render_report_fixture.py` + `tests/test_report.cjs`, and `tests/render_dashboard_fixture.py` + `tests/test_dashboard.cjs` (jsdom required only for tests).

Docker deployment and Git handoff: see [README_DOCKER.md](README_DOCKER.md).
