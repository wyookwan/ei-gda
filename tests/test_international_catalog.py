import ast
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles

from config import Config
from extensions import db
from models import User, Template, Standard, StandardItem, DocumentCheck
from services.catalog_update import update_catalog
from services.standards_catalog import load_catalog, merge_into_seed, item_metadata
from utils import json_dumps, json_loads


@compiles(LONGTEXT, 'sqlite')
def compile_longtext_for_test(type_, compiler, **kw):
    return 'TEXT'


class CatalogTests(unittest.TestCase):
    def setUp(self):
        with patch.multiple(Config, SQLALCHEMY_DATABASE_URI='sqlite://',
                            SQLALCHEMY_ENGINE_OPTIONS={}, THAID_ENABLED=False):
            from app import create_app
            self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='catalog-test-only')
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        # The literal is the pre-upgrade catalog; execute no seed/account code.
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'seed_data.py').read_text())
        self.original = ast.literal_eval(tree.body[0].value)
        for source in self.original['templates']:
            db.session.add(Template(name=source['name'], description=source['description'],
                                    prompt_structure='', sections_json=json_dumps(source['sections']),
                                    applicable_framework_codes_json=json_dumps(source['applicable_framework_codes'])))
        for source in self.original['standards']:
            row = Standard(code=source['code'], name=source['name'],
                           source_type=source['source_type'])
            db.session.add(row)
            db.session.flush()
            for n, (code, category, title, keywords) in enumerate(source['items'], 1):
                db.session.add(StandardItem(standard_id=row.id, item_code=code, category=category,
                                            title=title, keywords_json=json_dumps(keywords), order_index=n))
        user = User(full_name='Existing ThaiD user', email='fixture@example.invalid',
                    password_hash='unchanged-hash', auth_provider='thaid')
        db.session.add(user)
        db.session.flush()
        db.session.add(DocumentCheck(user_id=user.id, template_id=Template.query.first().id,
                                     original_filename='existing.pdf', stored_filename='existing.pdf',
                                     selected_standard_ids_json='[]', compliance_score=72,
                                     compliance_results_json='[{"historical":true}]'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_additive_idempotent_update_preserves_history_and_credentials(self):
        before = {i.id: (i.item_code, i.title, i.keywords_json) for i in StandardItem.query.all()}
        user_before = User.query.first().password_hash
        first = update_catalog(db.session)
        db.session.commit()
        self.assertEqual(first['new_items'], 208)
        self.assertGreater(first['new_standards'], 0)
        for item_id, expected in before.items():
            item = db.session.get(StandardItem, item_id)
            self.assertEqual((item.item_code, item.title, item.keywords_json), expected)
        second = update_catalog(db.session)
        db.session.commit()
        self.assertEqual(second, {'new_items': 0, 'new_standards': 0, 'new_suites': 0})
        self.assertEqual(User.query.first().password_hash, user_before)
        self.assertEqual(User.query.first().auth_provider, 'thaid')
        self.assertEqual(DocumentCheck.query.first().compliance_score, 72)
        self.assertEqual(DocumentCheck.query.first().compliance_results_json, '[{"historical":true}]')

    def test_all_suites_render_with_sources_drafts_and_watchlist(self):
        update_catalog(db.session)
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=User.query.first().id, role='user', full_name='ThaiD fixture')
        for suite in Template.query.all():
            response = client.get('/test-suites/explorer', query_string={'suite': suite.id})
            self.assertEqual(response.status_code, 200, suite.name)
            html = response.get_data(as_text=True)
            self.assertIn('Public-scope readiness', html, suite.name)
            for code in load_catalog()['suite_mappings'][suite.name]:
                self.assertIn(code, html)
            self.assertTrue(set(load_catalog()['suite_mappings'][suite.name]).issubset(
                json_loads(suite.applicable_framework_codes_json)))
        html = client.get('/dashboard').get_data(as_text=True)
        self.assertIn('International Standards — Draft readiness', html)
        for code in ['ISO27090', 'ISO27091', 'ISO42006']:
            self.assertIn(code, html)
        # No AI call: confirm new items enter the normal assessment graph.
        from services.kg_service import build_knowledge_graph
        standard = Standard.query.filter_by(code='ISO5392').one()
        graph = build_knowledge_graph(db.session, [standard.id])
        self.assertEqual(sum(n['type'] == 'item' for n in graph['nodes']), 5)

    def test_catalog_integrity_and_seed_repeatability(self):
        catalog = load_catalog()
        codes = [s['code'] for s in catalog['standards']]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(item_metadata()), 208)
        for standard in catalog['standards']:
            self.assertTrue(standard['reference_url'].startswith('https://www.iso.org/'))
            self.assertLessEqual(len(standard['name']), 255)
            if standard['source_type'].endswith('_draft'):
                self.assertIsNone(standard['published_year'])
                self.assertIn('กำลังพัฒนา', standard['status'])
            for item in standard['items']:
                self.assertTrue(item['source_topic'])
                self.assertTrue(item['evidence_expected'])
                self.assertTrue(item['keywords'])
                self.assertIsNone(item['normative_clause'])
        for project in catalog['watchlist']:
            self.assertEqual(project['items'], [])
        seed = merge_into_seed(copy.deepcopy(self.original))
        once = copy.deepcopy(seed)
        merge_into_seed(seed)
        self.assertEqual(seed, once)
        available = {s['code'] for s in seed['standards']}
        for suite in seed['templates']:
            self.assertTrue(set(suite['applicable_framework_codes']).issubset(available))
        all_codes = [i[0] for s in seed['standards'] for i in s['items']]
        self.assertEqual(len(all_codes), len(set(all_codes)))


if __name__ == '__main__':
    unittest.main()
