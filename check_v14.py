from flask import Flask
from config import Config
from extensions import db
from models import Template, Standard, DocumentCheck, CommitteeReview
from utils import json_loads
from services.local_model_service import local_model_enabled, resolve_local_model_name

app=Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

EXPECTED = {
    'Core AI Governance',
    'Data Governance & Privacy',
    'High-Risk AI & Risk Management',
    'Public Sector AI Governance',
    'Generative AI Governance',
}

ok=True
with app.app_context():
    print('=== Ei-GDA V14 System Check ===')
    print('Platform: Evidence-driven Intelligent Platform for Governance & Digital Assurance')
    print('Local endpoint:', Config.LOCAL_MODEL_API_URL)
    if Config.LOCAL_MODEL_API_URL != 'http://10.80.39.43:8087/v1/chat/completions':
        print('WARN: LOCAL_MODEL_API_URL differs from V14 project default.')
    print('Local enabled:', local_model_enabled())
    print('Resolved model:', resolve_local_model_name())
    suites=Template.query.filter_by(is_enabled=True).all()
    names={x.name for x in suites}
    missing=EXPECTED-names
    if missing:
        ok=False; print('FAIL missing Test Suites:', sorted(missing))
    else:
        print('PASS 5 core Test Suites present.')
    for t in sorted(suites, key=lambda x:x.name):
        mapped=json_loads(t.applicable_framework_codes_json, default=[])
        if t.name in EXPECTED:
            print(f'  {t.name}: {len(mapped)} mapped references')
            if not mapped: ok=False
    print('Standards/laws/guidelines:', Standard.query.filter_by(is_enabled=True).count())
    print('Historical assessments:', DocumentCheck.query.count())
    print('Committee reviews:', CommitteeReview.query.count())
    print('RESULT:', 'PASS' if ok else 'FAIL')
