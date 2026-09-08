"""Ei-GDA V14 migration.

No destructive schema change is required. The V13 physical `templates` table and legacy
completeness columns are retained to protect foreign keys and historical assessments.
This migration only rebrands existing five Test Suite records while preserving IDs and mappings.
"""
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
    db.create_all()
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
