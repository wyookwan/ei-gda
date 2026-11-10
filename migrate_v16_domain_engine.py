"""Idempotent additive V16 migration: new tables, two new nullable columns, catalog sync.

It never drops, renames or rewrites existing assessments, standards, test suites, users or evidence.
Back up first. Rollback: see docs/V16_MIGRATION_GUIDE.md and migrate_v16_rollback.py.

Optional, explicit, irreversible: --purge-plaintext-passwords clears the legacy users.password_plain values.
"""
import argparse

from sqlalchemy import inspect, text

from app import app
from extensions import db
from services.domain_catalog import sync_catalog
from services.schema_additions import ensure_additive_columns
import models  # noqa: F401  registers all tables

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--purge-plaintext-passwords', action='store_true')
    args = parser.parse_args()
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        before = {name: db.session.execute(text(f'SELECT COUNT(*) FROM {name}')).scalar() for name in ('users', 'document_checks', 'document_files', 'standards', 'standard_items', 'templates') if name in tables}
        db.session.commit()  # Release metadata locks; ALTER below uses its own connection.
        for change in ensure_additive_columns(db.engine):
            print('Added', change)
        db.create_all()
        stats = sync_catalog(db.session)
        db.session.commit()
        print('Catalog synced:', stats)
        if stats['suites_mapped'] != 8:
            print(f"WARNING: only {stats['suites_mapped']} of 8 core Test Suites matched by name. Check templates.name.")
        after = {name: db.session.execute(text(f'SELECT COUNT(*) FROM {name}')).scalar() for name in before}
        db.session.commit()
        print('Row counts before:', before)
        print('Row counts after: ', after)
        if any(after[name] < before[name] for name in before):
            raise SystemExit('Row count decreased; investigate before serving requests.')
        if args.purge_plaintext_passwords:
            changed = db.session.execute(text('UPDATE users SET password_plain = NULL WHERE password_plain IS NOT NULL')).rowcount
            db.session.commit()
            print('Cleared plaintext passwords:', changed)
        else:
            count = db.session.execute(text('SELECT COUNT(*) FROM users WHERE password_plain IS NOT NULL')).scalar()
            if count:
                print(f'NOTICE: {count} legacy plaintext password(s) remain. Re-run with --purge-plaintext-passwords to clear them.')
        print('V16 schema ready. Existing records were not modified.')


if __name__ == '__main__':
    main()
