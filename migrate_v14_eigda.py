"""Ei-GDA V14 migration.

No destructive schema change is required. The V13 physical `templates` table and legacy
completeness columns are retained to protect foreign keys and historical assessments.
This migration only rebrands existing five Test Suite records while preserving IDs and mappings.
"""
from services.schema_additions import ensure_additive_columns
from flask import Flask
from config import Config
from extensions import db
from models import Template

RENAMES = {
    'TNAGF-Core AI Governance': 'Core AI Governance',
    'TNAGF-Data Governance & Privacy': 'Data Governance & Privacy',
    'TNAGF-High-Risk AI & Risk Management': 'High-Risk AI & Risk Management',
    'TNAGF-Public Sector AI Governance': 'Public Sector AI Governance',
    'TNAGF-Generative AI Governance': 'Generative AI Governance',
}

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    ensure_additive_columns(db.engine)  # The ORM below already lists the V16 columns.
    db.create_all()
    from services.suite_order import ensure_suite_order
    ensure_suite_order(db.engine)

    # V14.1 reference metadata used on the user selection screen.
    # Additive migration only; existing data, passwords, keys and assessment history are preserved.
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    cols = {c['name'] for c in inspector.get_columns('standards')}
    if 'published_year' not in cols:
        db.session.execute(text('ALTER TABLE standards ADD COLUMN published_year INT NULL'))
    if 'status' not in cols:
        db.session.execute(text("ALTER TABLE standards ADD COLUMN status VARCHAR(120) NULL DEFAULT 'ประกาศใช้แล้ว'"))
    db.session.commit()
    renamed = 0
    for old, new in RENAMES.items():
        row = Template.query.filter_by(name=old).first()
        target = Template.query.filter_by(name=new).first()
        if row and not target:
            row.name = new
            renamed += 1
        elif row and target and row.id != target.id:
            # Keep the historical row enabled state safe; do not merge IDs automatically.
            row.is_enabled = False
    db.session.commit()
    print(f'Ei-GDA V14 migration complete. Test Suites renamed={renamed}.')
    print('No completeness schema columns were dropped; they remain legacy-only for DB compatibility.')
