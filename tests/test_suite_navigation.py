import unittest
from sqlalchemy import create_engine, text
from extensions import db
from models import Template, Standard, StandardItem, AuditLog
from services.suite_order import ensure_suite_order
from services.catalog_update import update_catalog
import test_international_catalog as fixtures
from html import unescape


class SuiteNavigationTests(unittest.TestCase):
    setUp = fixtures.CatalogTests.setUp
    tearDown = fixtures.CatalogTests.tearDown
    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=1, role='admin', email='admin@example.invalid')
        self.assertEqual(client.get('/admin/templates').status_code, 200)
        with client.session_transaction() as session:
            token = session['suite_order_token']
        return client, {'X-Suite-Order-Token': token}

    def ordered_ids(self):
        return [s.id for s in Template.query.order_by(Template.display_order, Template.name, Template.id)]

    def test_order_persists_across_pages_and_catalog_updates(self):
        client, headers = self.admin_client()
        original = self.ordered_ids()
        desired = original[::-1]
        response = client.post('/admin/templates/reorder', json={'order':desired, 'previous_order':original}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ordered_ids(), desired)
        self.assertEqual(AuditLog.query.filter_by(action='reorder_test_suites').count(), 1)
        update_catalog(db.session); db.session.commit()
        self.assertEqual(self.ordered_ids(), desired)
        for role, routes in [('admin', ['/test-suites/explorer','/test-suites/tree']),
                             ('user', ['/dashboard','/test-suites/explorer','/test-suites/tree'])]:
            with client.session_transaction() as session:
                session['role'] = role
            for route in routes:
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                html = unescape(response.get_data(as_text=True))
                first = db.session.get(Template, desired[0]).name
                last = db.session.get(Template, desired[-1]).name
                self.assertLess(html.index(first), html.index(last), route)
                self.assertIn('/test-suites/tree', html)

    def test_rejects_invalid_stale_and_unauthorized_order(self):
        client, headers = self.admin_client()
        original = self.ordered_ids()
        for order, status in [(original[:-1],409), ([original[0]]*len(original),400),
                              (['1'],400), ([True],400)]:
            response = client.post('/admin/templates/reorder', json={'order':order, 'previous_order':original}, headers=headers)
            self.assertEqual(response.status_code, status)
            self.assertEqual(self.ordered_ids(), original)
        self.assertEqual(client.post('/admin/templates/reorder', json={'order':original,'previous_order':original}).status_code,403)
        stale = client.post('/admin/templates/reorder',json={'order':original, 'previous_order':original[::-1]},headers=headers)
        self.assertEqual(stale.status_code,409)
        for role in ['user','committee']:
            with client.session_transaction() as session:
                session['role']=role
            result=client.post('/admin/templates/reorder',json={'order':original[::-1],'previous_order':original},headers=headers)
            self.assertEqual(result.status_code,302)
            self.assertEqual(self.ordered_ids(),original)

    def test_tree_permissions_disabled_nodes_and_empty_catalog(self):
        client, _ = self.admin_client()
        html = client.get('/test-suites/explorer').get_data(as_text=True)
        self.assertIn('จัดการ Test Suites',html)
        self.assertNotIn('Start assessment',html)
        update_catalog(db.session); db.session.commit()
        standard=Standard.query.filter_by(code='ISO5392').one()
        disabled=StandardItem.query.filter_by(standard_id=standard.id).first()
        disabled.is_enabled=False
        hidden_suite=Template.query.first(); hidden_suite.is_enabled=False
        db.session.commit()
        for role in ['admin','user']:
            with client.session_transaction() as session:
                session['role']=role
            response=client.get('/test-suites/tree')
            self.assertEqual(response.status_code,200)
            html=response.get_data(as_text=True)
            self.assertNotIn(f'data-suite-id="{hidden_suite.id}"',html)
            self.assertNotIn(disabled.item_code,html)
            self.assertIn('EVIDENCE EXPECTED',html)
        with client.session_transaction() as session:
            session['role']='committee'
        self.assertEqual(client.get('/test-suites/tree').status_code,403)
        with client.session_transaction() as session:
            session.clear()
        self.assertEqual(client.get('/test-suites/tree').status_code,302)
        Template.query.update({'is_enabled':False}); db.session.commit()
        with client.session_transaction() as session:
            session.update(user_id=1,role='user')
        self.assertIn('ยังไม่มี Test Suite',client.get('/test-suites/tree').get_data(as_text=True))

    def test_status_action_preserves_mapping_and_edit_does_not_disable(self):
        client, headers = self.admin_client()
        suite = Template.query.first()
        original = suite.applicable_framework_codes_json
        route = f'/admin/templates/{suite.id}/status'
        token = headers['X-Suite-Order-Token']
        self.assertEqual(client.post(route, data={'is_enabled':'0'}).status_code, 403)
        self.assertEqual(client.post(route, data={'is_enabled':'bad','token':token}).status_code, 400)
        for value in ['0','1']:
            response = client.post(route, data={'is_enabled':value, 'token':token})
            self.assertEqual(response.status_code,302)
            self.assertIn(f'suite={suite.id}', response.location)
            self.assertEqual(suite.is_enabled, value == '1')
            self.assertEqual(suite.applicable_framework_codes_json, original)
        client.post(f'/admin/templates/{suite.id}/update',data={'description':'Edited'})
        self.assertTrue(suite.is_enabled)
        with client.session_transaction() as session:
            session['role']='user'
        self.assertEqual(client.post(route,data={'is_enabled':'0','token':token}).status_code,302)
        self.assertTrue(suite.is_enabled)

    def test_new_suite_appends_to_order(self):
        client,_=self.admin_client()
        old=self.ordered_ids()
        result=client.post('/admin/templates',data={'name':'AAA newly created','sections_text':'Scope'})
        self.assertEqual(result.status_code,302)
        self.assertEqual(self.ordered_ids()[:-1],old)


class OrderMigrationTests(unittest.TestCase):
    def test_additive_migration_initializes_once(self):
        engine=create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE templates (id INTEGER PRIMARY KEY, name TEXT)'))
            connection.execute(text("INSERT INTO templates VALUES (1,'Z'),(2,'A')"))
        self.assertTrue(ensure_suite_order(engine))
        with engine.begin() as connection:
            self.assertEqual(connection.execute(text('SELECT id FROM templates ORDER BY display_order')).scalars().all(),[2,1])
            connection.execute(text('UPDATE templates SET display_order=9 WHERE id=2'))
        self.assertFalse(ensure_suite_order(engine))
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT display_order FROM templates WHERE id=2')).scalar(),9)
        engine.dispose()


if __name__=='__main__':
    unittest.main()
