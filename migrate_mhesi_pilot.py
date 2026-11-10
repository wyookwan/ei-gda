"""Idempotent, additive migration for the MHESI / OPS-MHESI pilot.

What it does:
  * adds nullable pilot columns (organization_id, round_id, workflow fields, document protection facts)
  * creates the pilot tables (organizations, memberships, rounds, criteria sets, revisions, issues, ...)
  * syncs the domain packs, including common_aidg, ops_mhesi and higher_education, and the registry
  * seeds explicit model-processing allow rules (everything else is refused) and integration placeholders

What it never does:
  * drop, rename or rewrite existing rows
  * set organization_id on existing work, or infer membership from an organization name

Usage:
  python migrate_mhesi_pilot.py                                  # database from .env (back it up first)
  python migrate_mhesi_pilot.py --database-url sqlite:///copy.db  # a copy or a separate DEMO database
"""
import argparse
import os
import sys

COUNTED = ('users', 'document_checks', 'document_files', 'standards', 'standard_items', 'templates', 'domain_assessments',
           'domain_assessment_findings', 'evidence_control_mappings', 'committee_assignments', 'committee_reviews', 'audit_logs')

INTEGRATIONS = (
    ('DSV', 'Digital Single View (ข้อมูลสถาบันอุดมศึกษา)', ['API contract และ schema ของข้อมูลที่รับ', 'credentials ของระบบปลายทาง', 'ขอบเขตข้อมูลที่ อว. อนุญาตให้ส่ง', 'การยืนยันรหัสอ้างอิงสถาบัน']),
    ('MHESI_EOFFICE', 'MHESI e-Office (หนังสือราชการอิเล็กทรอนิกส์)', ['API contract สำหรับส่งรายงาน', 'credentials และ endpoint', 'รูปแบบเลขที่หนังสือและผู้ลงนาม']),
    ('TUC_ESIGN', 'ลายมือชื่อดิจิทัล Thai University Consortium', ['บริการลงนามและใบรับรองที่ใช้', 'credentials ของสถาบัน', 'ขั้นตอนตรวจสอบลายมือชื่อ']),
)


def run(app):
    from sqlalchemy import inspect, text
    from extensions import db
    from models import IntegrationEndpoint
    from services.domain_catalog import sync_catalog
    from services.model_gate import seed_default_rules
    from services.schema_additions import ensure_additive_columns
    from utils import json_dumps
    report = {}
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        before = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in COUNTED if t in tables}
        legacy_null = None
        if 'domain_assessments' in tables:
            legacy_null = before.get('domain_assessments')
        db.session.commit()
        report['columns_added'] = ensure_additive_columns(db.engine)
        db.create_all()
        report['catalog'] = sync_catalog(db.session)
        report['model_rules_added'] = seed_default_rules(db.session)
        for code, title, missing in INTEGRATIONS:
            row = db.session.get(IntegrationEndpoint, code)
            if row is None:
                db.session.add(IntegrationEndpoint(code=code, title=title, status='prepared', missing_json=json_dumps(missing),
                                                   note='เตรียมเชื่อมต่อ ยังไม่ได้เชื่อมบริการจริง'))
        db.session.commit()
        after = {t: db.session.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in before}
        db.session.commit()
        report['before'], report['after'] = before, after
        if any(after[t] < before[t] for t in before):
            raise SystemExit('Row count decreased; investigate before serving requests.')
        if legacy_null is not None:
            scoped = db.session.execute(text('SELECT COUNT(*) FROM domain_assessments WHERE organization_id IS NOT NULL')).scalar()
            report['org_scoped_assessments'] = scoped
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database-url', help='Run against this database instead of the one in .env')
    args = parser.parse_args()
    if args.database_url:
        os.environ['DATABASE_URL'] = args.database_url
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import app
    report = run(app)
    print('Added:', report['columns_added'] or 'nothing (already migrated)')
    print('Catalog synced:', report['catalog'])
    print('Model rules added:', report['model_rules_added'])
    print('Row counts before:', report['before'])
    print('Row counts after: ', report['after'])
    print('Organization-scoped assessments:', report.get('org_scoped_assessments'), '(existing work is never re-scoped by this script)')
    print('Pilot schema ready. Existing records were not modified.')


if __name__ == '__main__':
    main()
