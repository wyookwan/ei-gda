# Ei-GDA V14

**Evidence-driven Intelligent Platform for Governance & Digital Assurance**

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
