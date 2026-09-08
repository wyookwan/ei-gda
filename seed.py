from flask import Flask
from werkzeug.security import generate_password_hash
from config import Config
from extensions import db
from models import User, Template, Standard, StandardItem, AuditLog
from seed_data import SEED_DATA
from utils import json_dumps

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    db.create_all()

    # Core accounts
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(full_name='Admin BUU', email='admin@buu.local', organization='Burapha University', role='admin')
        db.session.add(admin)
    admin.full_name='Admin BUU'; admin.email='admin@buu.local'; admin.organization='Burapha University'
    admin.password_hash=generate_password_hash('Pwd@buu2026'); admin.password_plain='Pwd@buu2026'
    admin.role='admin'; admin.is_active=True; admin.auth_provider='local'

    committee = User.query.filter_by(email='committee1@buu.local').first()
    if not committee:
        committee = User(full_name='Committee Demo', email='committee1@buu.local', organization='ETDA / BUU', role='committee')
        db.session.add(committee)
    committee.full_name='Committee Demo'; committee.organization='ETDA / BUU'
    committee.password_hash=generate_password_hash('Committee@2026'); committee.password_plain='Committee@2026'
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
            obj=Template(name=tpl['name'], prompt_structure='', sections_json='[]')
            db.session.add(obj)
        obj.description=tpl.get('description','')
        obj.prompt_structure='\n'.join(tpl['sections'])
        obj.sections_json=json_dumps(tpl['sections'])
        obj.applicable_framework_codes_json=json_dumps(tpl.get('applicable_framework_codes', []))
        obj.pass_threshold=tpl['pass_threshold']
        obj.is_enabled=True
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
