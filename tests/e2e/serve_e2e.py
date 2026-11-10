"""Isolated E2E server: temporary SQLite database, synthetic users, Gemini disabled.

Usage: python tests/e2e/serve_e2e.py <work_dir> <port>
It never connects to the configured MySQL database.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
work, port = sys.argv[1], int(sys.argv[2])

from sqlalchemy.dialects.mysql import LONGTEXT  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402

from config import Config  # noqa: E402


@compiles(LONGTEXT, 'sqlite')
def _longtext(type_, compiler, **kw):
    return 'TEXT'


Config.SQLALCHEMY_DATABASE_URI = f'sqlite:///{work}/e2e.db'
Config.SQLALCHEMY_ENGINE_OPTIONS = {}
Config.GEMINI_API_KEY = ''
Config.THAID_ENABLED = False
Config.UPLOAD_FOLDER = f'{work}/uploads'
Config.REPORT_FOLDER = f'{work}/reports'
Config.SECRET_KEY = 'e2e-only-' + 'x' * 40
Config.ADMIN_LOGIN_ALIAS = ''

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Standard, StandardItem, Template, User  # noqa: E402
from seed_data import SEED_DATA  # noqa: E402
from services.domain_catalog import sync_catalog  # noqa: E402
from utils import json_dumps  # noqa: E402

app = create_app()
with app.app_context():
    db.create_all()
    PASSWORD = 'e2e-test-password-1'
    for email, role in (('owner@e2e.invalid', 'user'), ('admin@e2e.invalid', 'admin'), ('committee@e2e.invalid', 'committee'), ('other@e2e.invalid', 'user')):
        db.session.add(User(full_name=role.title() + ' E2E', email=email, password_hash=generate_password_hash(PASSWORD), role=role, organization='E2E Org', auth_provider='local'))
    names = ['AI Foundation & Architecture', 'AI Governance & Management', 'AI Ethics, Transparency & Trustworthiness', 'AI Risk, Security & Privacy', 'AI Data Quality & Governance', 'AI Evaluation & Quality Assurance', 'AI Life Cycle Assurance', 'AI Application & Use-Case Assurance']
    for index, name in enumerate(names, 1):
        db.session.add(Template(name=name, description='', prompt_structure='', sections_json='[]', applicable_framework_codes_json='[]', display_order=index))
    for source in SEED_DATA['standards'][:12]:
        row = Standard(code=source['code'], name=source['name'], source_type=source['source_type'])
        db.session.add(row)
        db.session.flush()
        for n, (code, category, title, keywords) in enumerate(source['items'][:3], 1):
            db.session.add(StandardItem(standard_id=row.id, item_code=code, category=category, title=title, keywords_json=json_dumps(keywords), order_index=n))
    db.session.commit()
    print(sync_catalog(db.session))
    db.session.commit()
app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
