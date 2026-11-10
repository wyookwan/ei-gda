"""Additive columns. Older migration scripts call this first, because the ORM models already list these columns.

Every column here is nullable or has a default, so existing rows stay valid and older versions (V15) that share
the database keep working: they never select these columns.
"""
from sqlalchemy import inspect, text

ADDITIVE_COLUMNS = {
    'templates': {'suite_code': 'VARCHAR(10) NULL'},
    'document_files': {'content_hash': 'VARCHAR(64) NULL',
                       # MHESI pilot: document protection facts
                       'disclosure_class': 'VARCHAR(30) NULL', 'personal_data': 'VARCHAR(20) NULL', 'is_redacted': 'BOOLEAN NULL',
                       'classified_by': 'INTEGER NULL', 'classified_at': 'DATETIME NULL'},
    'document_checks': {'organization_id': 'INTEGER NULL'},
    'committee_assignments': {'assigned_by': 'INTEGER NULL', 'revoked_by': 'INTEGER NULL', 'revoked_at': 'DATETIME NULL', 'revoke_reason': 'VARCHAR(500) NULL'},
    'domain_assessments': {'organization_id': 'INTEGER NULL', 'round_id': 'INTEGER NULL', 'created_by_id': 'INTEGER NULL', 'responsible_user_id': 'INTEGER NULL',
                           'criteria_set_id': 'INTEGER NULL', 'criteria_version': 'VARCHAR(40) NULL', 'workflow_status': 'VARCHAR(30) NULL',
                           'workflow_version': 'INTEGER NOT NULL DEFAULT 0', 'submitted_at': 'DATETIME NULL', 'confirmed_at': 'DATETIME NULL'},
    'domain_assessment_findings': {'judgement': 'VARCHAR(30) NULL', 'judgement_reason': 'LONGTEXT NULL', 'judged_by': 'INTEGER NULL', 'judged_at': 'DATETIME NULL'},
    'regulatory_references': {'details_json': 'LONGTEXT NULL'},
}
ADDITIVE_INDEXES = {
    'templates': {'uq_templates_suite_code': 'CREATE UNIQUE INDEX uq_templates_suite_code ON templates (suite_code)'},
    'document_files': {'ix_document_files_content_hash': 'CREATE INDEX ix_document_files_content_hash ON document_files (content_hash)'},
    'document_checks': {'ix_document_checks_organization_id': 'CREATE INDEX ix_document_checks_organization_id ON document_checks (organization_id)'},
    'domain_assessments': {'ix_domain_assessments_organization_id': 'CREATE INDEX ix_domain_assessments_organization_id ON domain_assessments (organization_id)',
                           'ix_domain_assessments_round_id': 'CREATE INDEX ix_domain_assessments_round_id ON domain_assessments (round_id)',
                           'ix_domain_assessments_workflow_status': 'CREATE INDEX ix_domain_assessments_workflow_status ON domain_assessments (workflow_status)'},
}


def ensure_additive_columns(engine):
    """Add missing columns and indexes. Safe to repeat; does nothing to a table that does not exist yet."""
    changes = []
    sqlite = engine.dialect.name == 'sqlite'
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table, columns in ADDITIVE_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            for column, definition in columns.items():
                if column not in existing:
                    if sqlite:
                        definition = definition.replace('LONGTEXT', 'TEXT')
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))
                    changes.append(f'{table}.{column}')
            names = {i['name'] for i in inspect(connection).get_indexes(table)}
            for name, statement in ADDITIVE_INDEXES.get(table, {}).items():
                if name not in names:
                    connection.execute(text(statement))
                    changes.append(name)
    return changes
