"""Idempotent additive V15 migration. Run after MySQL is reachable; backups recommended."""
from sqlalchemy import inspect, text
from app import app
from extensions import db
from models import DocumentCheck

with app.app_context():
    inspector = inspect(db.engine)
    if not inspector.has_table('document_checks'):
        print('No existing document_checks table; creating all current schema tables')
        db.create_all()
    else:
        existing = {c['name'] for c in inspector.get_columns('document_checks')}
        changes = {
            'domain_slug': "VARCHAR(50) NOT NULL DEFAULT 'general'",
            'domain_subdomain': 'VARCHAR(150) NULL',
            'assessment_use_case': 'VARCHAR(255) NULL',
            'domain_review_json': 'LONGTEXT NULL',
        }
        with db.engine.begin() as connection:
            for column, definition in changes.items():
                if column not in existing:
                    connection.execute(text(f'ALTER TABLE document_checks ADD COLUMN {column} {definition}'))
                    print('Added document_checks.' + column)
            connection.execute(text("UPDATE document_checks SET domain_slug='general' WHERE domain_slug IS NULL OR domain_slug=''"))
        db.create_all()
    print('V15 domain schema ready. Historical checks default to general.')
