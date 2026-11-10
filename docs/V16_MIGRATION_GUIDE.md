# V16 migration guide

The migration is additive and repeatable. It compares row counts for core tables and stops with an error if any count decreases.

## Upgrade an existing database

```bash
mysqldump -h127.0.0.1 -u<user> -p --single-transaction --set-gtid-purged=OFF --no-tablespaces --default-character-set=utf8mb4 <db> > backup.sql
python migrate_v16_domain_engine.py
```

It adds 12 tables, `templates.suite_code`, `document_files.content_hash`, and two indexes, then syncs the catalog. TS codes are assigned by exact suite name, and `display_order` is not changed. Expect `suites_mapped: 8`.

Copy `uploads/` and `reports/` from the previous version, or historical source PDFs will not open. Keep the same `SECRET_KEY` and database.

V14.3 and V15 keep working on the migrated database. V15 pages were checked after migration. Do not run `seed.py --clear`, because it deletes all data.

## New installation

```bash
python migrate_v14_eigda.py && python migrate_v15_domains.py && python migrate_v16_domain_engine.py
EIGDA_ADMIN_PASSWORD=... EIGDA_COMMITTEE_PASSWORD=... python seed.py
python migrate_v16_domain_engine.py   # assigns TS codes now that suites exist
```

## Optional: clear legacy plaintext passwords

Irreversible, and it does not affect login, which uses `password_hash`.

```bash
python migrate_v16_domain_engine.py --purge-plaintext-passwords
```

## Rollback

Preferred: stop V16, restore the backup, and run the previous version's source.

Partial, removing only V16 tables and columns:

```bash
python migrate_v16_rollback.py                         # dry run
python migrate_v16_rollback.py --confirm-drop-v16-data # deletes V16 assessments and findings
```

Only the dry run has been executed. Restoring a backup and a real rollback have not been tested. `DocumentCheck` and file rows created by V16 assessments remain after a partial rollback.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Unknown column templates.suite_code` | Migration not run yet |
| Portal says there are no domains | Catalog not synced. Run the migration |
| `SECRET_KEY is missing or insecure` | Set a random value of at least 32 characters |
| "Session expired or invalid form token" | Reload the page. Check that cookies are enabled and `SESSION_COOKIE_SECURE` is False on plain HTTP |
| Migration hangs on `ALTER TABLE` | Another connection holds a metadata lock. Check `SHOW PROCESSLIST` |
| Model note `finish_reason=length` | Raise `LOCAL_MODEL_MAX_TOKENS` and `LOCAL_MODEL_TOKEN_CAP`, or lower the batch size |
| Findings are all `evidence_only` | The model did not answer. See the run note on the results page |
| ThaiD shows `redirect or callback url mismatch` | The provider registration differs from `THAID_REDIRECT_URI` |
| Scanned PDF finds no evidence | No OCR. Use a PDF with a text layer |
