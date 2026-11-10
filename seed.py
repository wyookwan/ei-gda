from flask import Flask
import argparse
import os
import shutil
from werkzeug.security import generate_password_hash
from config import Config
from extensions import db
from models import (User, Template, Standard, StandardItem, AuditLog, DocumentCheck,
                    DocumentFile, CommitteeAssignment, CommitteeReview)
from seed_data import SEED_DATA
from utils import json_dumps

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

def _clear_folder(folder):
    if not folder:
        return 0
    root = os.path.abspath(folder)
    if not os.path.isdir(root):
        return 0
    removed = 0
    for name in os.listdir(root):
        path = os.path.join(root, name)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed += 1
        except FileNotFoundError:
            pass
    return removed

def full_reset():
    counts = {
        'users': User.query.count(),
        'assessments': DocumentCheck.query.count(),
        'document_files': DocumentFile.query.count(),
        'assignments': CommitteeAssignment.query.count(),
        'reviews': CommitteeReview.query.count(),
        'audit_logs': AuditLog.query.count(),
        'test_suites': Template.query.count(),
        'standards': Standard.query.count(),
        'standard_items': StandardItem.query.count(),
    }
    print('\nDANGER: FULL DATABASE RESET')
    print('This will permanently delete all users, assessments, uploaded-document records,')
    print('results/evidence, committee data, audit logs, and the Test Suite/reference catalog.')
    print('The .env file, database account, API keys, ThaiD configuration and model endpoint are NOT changed.')
    print('Current records:', ', '.join(f'{k}={v}' for k,v in counts.items()))
    if not args.yes:
        confirmation = input('\nType RESET ALL to continue: ').strip()
        if confirmation != 'RESET ALL':
            print('Reset cancelled. No data was deleted.')
            raise SystemExit(1)

    # Child -> parent order avoids foreign-key violations.
    CommitteeReview.query.delete(synchronize_session=False)
    CommitteeAssignment.query.delete(synchronize_session=False)
    DocumentFile.query.delete(synchronize_session=False)
    DocumentCheck.query.delete(synchronize_session=False)
    AuditLog.query.delete(synchronize_session=False)
    StandardItem.query.delete(synchronize_session=False)
    Standard.query.delete(synchronize_session=False)
    Template.query.delete(synchronize_session=False)
    User.query.delete(synchronize_session=False)
    db.session.commit()

    removed_uploads = _clear_folder(app.config.get('UPLOAD_FOLDER'))
    removed_reports = _clear_folder(app.config.get('REPORT_FOLDER'))
    print(f'Full reset complete. Removed upload entries/files: {removed_uploads}; report files: {removed_reports}.')

parser = argparse.ArgumentParser(description='Seed Ei-GDA master data and optional development reset.')
parser.add_argument('--clear', action='store_true', help='FULL RESET: delete all users, assessments, reviews and master catalog before seeding.')
parser.add_argument('--yes', action='store_true', help='Skip RESET ALL confirmation. Intended for development/CI only.')
args = parser.parse_args()
if args.yes and not args.clear:
    parser.error('--yes can only be used together with --clear')

with app.app_context():
    db.create_all()
    if args.clear:
        full_reset()

    # Core accounts
    if not User.query.filter_by(role='admin').first() and not os.getenv('EIGDA_ADMIN_PASSWORD'):
        raise RuntimeError('Set EIGDA_ADMIN_PASSWORD before first-time seed.')
    if not User.query.filter_by(email='committee1@buu.local').first() and not os.getenv('EIGDA_COMMITTEE_PASSWORD'):
        raise RuntimeError('Set EIGDA_COMMITTEE_PASSWORD before first-time seed.')
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(full_name='Admin BUU', email='admin@buu.local', organization='Burapha University', role='admin')
        db.session.add(admin)
    admin.full_name='Admin BUU'; admin.email='admin@buu.local'; admin.organization='Burapha University'
    if not admin.password_hash:
        admin.password_hash=generate_password_hash(os.getenv('EIGDA_ADMIN_PASSWORD') or os.urandom(24).hex())
    admin.password_plain=None
    admin.role='admin'; admin.is_active=True; admin.auth_provider='local'

    committee = User.query.filter_by(email='committee1@buu.local').first()
    if not committee:
        committee = User(full_name='Committee Demo', email='committee1@buu.local', organization='ETDA / BUU', role='committee')
        db.session.add(committee)
    committee.full_name='Committee Demo'; committee.organization='ETDA / BUU'
    if not committee.password_hash:
        committee.password_hash=generate_password_hash(os.getenv('EIGDA_COMMITTEE_PASSWORD') or os.urandom(24).hex())
    committee.password_plain=None
    committee.role='committee'; committee.is_active=True; committee.auth_provider='local'
    db.session.commit()

    # Disable legacy non-Ei-GDA records. We keep rows for historical FK integrity.
    for legacy_name in ['IEEE Access', 'วิทยานิพนธ์', 'T-NAGF']:
        legacy = Template.query.filter_by(name=legacy_name).first()
        if legacy:
            legacy.is_enabled = False

    # Upsert Ei-GDA Test Suites and their mapped frameworks/laws.
    active_template_names=[]
    for tpl in SEED_DATA['templates']:
        active_template_names.append(tpl['name'])
        obj=Template.query.filter_by(name=tpl['name']).first()
        if not obj:
            obj=Template(name=tpl['name'], prompt_structure='', sections_json='[]',
                         display_order=(db.session.query(db.func.max(Template.display_order)).scalar() or 0) + 1)
            db.session.add(obj)
        obj.description=tpl.get('description','')
        obj.prompt_structure='\n'.join(tpl['sections'])
        obj.sections_json=json_dumps(tpl['sections'])
        obj.applicable_framework_codes_json=json_dumps(tpl.get('applicable_framework_codes', []))
        obj.pass_threshold=tpl['pass_threshold']
        obj.is_enabled=True
    db.session.commit()

    # Only the current eight category-based Test Suites are selectable. Historical rows remain for FK/history.
    for old_suite in Template.query.all():
        if old_suite.name not in active_template_names:
            old_suite.is_enabled = False
    db.session.commit()

    # Upsert standards, frameworks, guidelines and Thai laws.
    for std in SEED_DATA['standards']:
        standard=Standard.query.filter_by(code=std['code']).first()
        if not standard:
            standard=Standard(code=std['code'], name=std['name'])
            db.session.add(standard)
            db.session.flush()
        standard.name=std['name']
        standard.description=std.get('description','')
        standard.source_type=std.get('source_type','international_standard')
        standard.jurisdiction=std.get('jurisdiction')
        standard.publisher=std.get('publisher')
        standard.reference_url=std.get('reference_url')
        standard.published_year=std.get('published_year')
        standard.status=std.get('status','ประกาศใช้แล้ว')
        standard.is_enabled=True
        db.session.flush()

        existing={x.item_code:x for x in StandardItem.query.filter_by(standard_id=standard.id).all()}
        seen=set()
        for idx,item in enumerate(std['items'], start=1):
            item_code, category, title, keywords=item
            seen.add(item_code)
            obj=existing.get(item_code)
            if not obj:
                obj=StandardItem(standard_id=standard.id,item_code=item_code,title=title,keywords_json='[]')
                db.session.add(obj)
            obj.category=category; obj.title=title; obj.keywords_json=json_dumps(keywords)
            obj.weight=1.0; obj.order_index=idx; obj.is_enabled=True
        # Keep historical items but disable items no longer in current definition.
        for code,obj in existing.items():
            if code not in seen:
                obj.is_enabled=False

    db.session.add(AuditLog(actor_email='system', action='seed_database_v14',
                            target_type='system',
                            detail='Ei-GDA V14 seed complete: Test Suites + standards + laws + guidelines'))
    db.session.commit()
    print('Seed complete: Ei-GDA V14')
    print('Test Suites:', ', '.join(active_template_names))
    print('Committee: committee1@buu.local / Committee@2026')
