"""Read-only verification of the installed V14.3 catalog and Explorer rendering."""
from app import app
from models import Standard, StandardItem, Template
from services.standards_catalog import load_catalog
from utils import json_loads


def main():
    catalog = load_catalog()
    with app.app_context():
        totals = {'published': 0, 'drafts': 0, 'items': 0}
        for source in catalog['standards']:
            standard = Standard.query.filter_by(code=source['code']).one()
            assert standard.is_enabled
            assert standard.reference_url == source['reference_url']
            assert standard.source_type == source['source_type']
            assert standard.published_year == source['published_year']
            assert standard.status == source['status']
            totals['drafts' if source['source_type'].endswith('_draft') else 'published'] += 1
            items = {i.item_code: i for i in StandardItem.query.filter_by(standard_id=standard.id, is_enabled=True)}
            totals['items'] += len(items)
            for payload in source['items']:
                assert items[payload['item_code']].title == payload['title']
        # Synthetic session, no real user identity or ThaiD tokens; GETs are read-only.
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=-1, role='user', full_name='Catalog verification')
        for name, codes in catalog['suite_mappings'].items():
            suite = Template.query.filter_by(name=name, is_enabled=True).one()
            assert set(codes).issubset(json_loads(suite.applicable_framework_codes_json))
            response = client.get('/test-suites/explorer', query_string={'suite': suite.id})
            assert response.status_code == 200, name
            html = response.get_data(as_text=True)
            for code in codes:
                assert code in html, code
            print('PASS Explorer:', name)
        response = client.get('/dashboard')
        assert response.status_code == 200
        assert 'International Standards — Draft readiness' in response.get_data(as_text=True)
        print('PASS Dashboard draft reference selection')
        for role in ['user', 'admin']:
            with client.session_transaction() as session:
                session['role'] = role
            for route in ['/test-suites/tree', '/test-suites/explorer'] + (['/admin/templates'] if role == 'admin' else []):
                assert client.get(route).status_code == 200, (role, route)
                print('PASS navigation:', role, route)
        print('Installed catalog:', totals)


if __name__ == '__main__':
    main()
