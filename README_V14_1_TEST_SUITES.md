# Ei-GDA V14.1 — 8 Cross-Framework Test Suites

This build starts from the supplied Ei-GDA V14 and preserves the existing `.env` file unchanged.

## New Test Suites
1. AI Foundation & Architecture
2. AI Governance & Management
3. AI Ethics, Transparency & Trustworthiness
4. AI Risk, Security & Privacy
5. AI Data Quality & Governance
6. AI Evaluation & Quality Assurance
7. AI Life Cycle Assurance
8. AI Application & Use-Case Assurance

Each Test Suite maps to relevant international standards/frameworks, Thai guidelines and applicable laws. Reference records now include `published_year` and `status`; these are displayed on the user reference-selection screen.

## Data provenance
New normalized assessment items were prepared from authoritative public source scopes/guidance, including ISO public standard pages, NIST AI RMF, ASEAN AI Governance and Ethics, UNESCO AI Ethics, EU AI Act, DGA Data Governance Framework and ETDA guidance. The item text is an Ei-GDA normalized assessment statement, not a reproduction of copyrighted ISO clause text. For certification/legal use, validate against licensed full standards and current legal text.

## Local run (existing database)
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python migrate_v14_eigda.py
python seed.py
python check_v14.py
python app.py
```
Open http://127.0.0.1:5000

## Fresh database
Use the same commands. `db.create_all()` creates the base schema and the migration adds the reference metadata fields where needed.

## Docker
```bash
docker compose build
docker compose up -d
docker compose exec web python migrate_v14_eigda.py
docker compose exec web python seed.py
```
Open `http://SERVER-IP:5000`.

## Model routing
Both Open and Confidential assessments use the existing Local Model endpoint configured by `LOCAL_MODEL_API_URL`. No existing passwords, API keys, or other `.env` values were changed.

## V14.2 — Test Suite Explorer

เพิ่มหน้า **Test Suite Explorer** เพื่อสำรวจโครงสร้างก่อนเริ่มประเมิน:

`Test Suite → Standards / Laws / Guidelines → Domains → Items → Evidence Expected`

เปิดจากเมนู **Test Suite Explorer** หรือ URL `/test-suites/explorer` หลังเข้าสู่ระบบ ผู้ใช้สามารถสลับ 8 Test Suites, ดูปีประกาศ/สถานะ/แหล่งอ้างอิง, ค้นหา items, filter ตาม domain และเปิด official source ของแต่ละ reference ได้

Evidence Expected ในหน้า Explorer เป็นคำแนะนำประเภทหลักฐานเพื่อเตรียมเอกสาร ไม่ใช่ผล compliance และไม่เปลี่ยน scoring logic เดิม

## V14.2.2 Full Reset before Seed

For a clean development database, including removal of all user accounts and all assessment history, run:

```bash
python seed.py --clear
```

The command displays current record counts and requires typing `RESET ALL` before deletion. It removes application users, assessments, uploaded-document records, results/evidence stored with assessments, committee assignments/reviews, audit logs, legacy/current Test Suite catalog records, standards/guidelines/laws and their items. It also clears files currently stored in the configured upload and report folders. It then seeds the current 8 Test Suites, reference catalog, and system Admin/Committee accounts again.

For development/CI only, confirmation can be skipped:

```bash
python seed.py --clear --yes
```

Normal seeding remains non-destructive:

```bash
python seed.py
```

The reset does **not** modify `.env`, database credentials, API keys, ThaiD settings, local model endpoint, or MySQL account/database configuration.

Recommended clean-start sequence:

```bash
python migrate_v14_eigda.py
python seed.py --clear
python check_v14.py
python app.py
```
