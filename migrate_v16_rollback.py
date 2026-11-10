"""Removes ONLY the tables and columns that V16 added. Requires --confirm-drop-v16-data.

Domain assessments, findings and decisions recorded in V16 are lost; take a backup first.
Files and DocumentCheck rows created by V16 assessments remain and stay visible in the classic pages.
"""
import argparse

from sqlalchemy import inspect, text

from app import app
from extensions import db

V16_TABLES = ['evidence_control_mappings', 'domain_assessment_findings', 'assessment_applicability_decisions', 'domain_assessments', 'regulatory_references',
              'domain_rubrics', 'evidence_requirements', 'domain_controls', 'taxonomy_edges', 'taxonomy_nodes', 'domain_profiles', 'domain_pack_versions']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-drop-v16-data', action='store_true')
    args = parser.parse_args()
    with app.app_context():
        existing = set(inspect(db.engine).get_table_names())
        targets = [t for t in V16_TABLES if t in existing]
        print('Would remove tables:', targets)
        print('Would remove columns: templates.suite_code, document_files.content_hash')
        if not args.confirm_drop_v16_data:
            print('Nothing changed. Re-run with --confirm-drop-v16-data after taking a backup.')
            return
        with db.engine.begin() as connection:
            for table in targets:
                connection.execute(text(f'DROP TABLE {table}'))
            for table, column, index in (('templates', 'suite_code', 'uq_templates_suite_code'), ('document_files', 'content_hash', 'ix_document_files_content_hash')):
                names = {i['name'] for i in inspect(connection).get_indexes(table)}
                if index in names:
                    connection.execute(text(f'DROP INDEX {index} ON {table}'))
                if column in {c['name'] for c in inspect(connection).get_columns(table)}:
                    connection.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
        print('V16 additions removed.')


if __name__ == '__main__':
    main()
