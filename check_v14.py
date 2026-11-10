from flask import Flask
from config import Config
from extensions import db
from models import Template, Standard, DocumentCheck, CommitteeReview
from utils import json_loads
from services.local_model_service import local_model_enabled, resolve_local_model_name

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# V14.2+ uses the eight category-based Cross-Framework Test Suites.
EXPECTED = {
    'AI Foundation & Architecture',
    'AI Governance & Management',
    'AI Ethics, Transparency & Trustworthiness',
    'AI Risk, Security & Privacy',
    'AI Data Quality & Governance',
    'AI Evaluation & Quality Assurance',
    'AI Life Cycle Assurance',
    'AI Application & Use-Case Assurance',
}

ok = True
with app.app_context():
    print('=== Ei-GDA V14.2 System Check ===')
    print('Platform: Evidence-driven Intelligent Platform for Governance & Digital Assurance')
    print('Local endpoint:', Config.LOCAL_MODEL_API_URL)
    if Config.LOCAL_MODEL_API_URL != 'http://10.80.39.43:8087/v1/chat/completions':
        print('WARN: LOCAL_MODEL_API_URL differs from project default.')
    print('Local enabled:', local_model_enabled())
    print('Resolved model:', resolve_local_model_name())

    suites = Template.query.filter_by(is_enabled=True).all()
    names = {x.name for x in suites}
    missing = EXPECTED - names
    unexpected = names - EXPECTED

    if missing:
        ok = False
        print('FAIL missing Test Suites:', sorted(missing))
    else:
        print('PASS 8 current Test Suites present.')

    if unexpected:
        print('WARN additional enabled Test Suites:', sorted(unexpected))

    for t in sorted(suites, key=lambda x: x.name):
        mapped = json_loads(t.applicable_framework_codes_json, default=[])
        sections = json_loads(t.sections_json, default=[])
        marker = 'PASS' if mapped and sections else 'FAIL'
        if t.name in EXPECTED:
            print(f'  {marker} {t.name}: {len(mapped)} mapped references, {len(sections)} domains')
            if not mapped or not sections:
                ok = False

    print('Standards/laws/guidelines:', Standard.query.filter_by(is_enabled=True).count())
    print('Historical assessments:', DocumentCheck.query.count())
    print('Committee reviews:', CommitteeReview.query.count())
    print('RESULT:', 'PASS' if ok else 'FAIL')
