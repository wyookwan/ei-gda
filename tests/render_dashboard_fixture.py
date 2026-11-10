"""Render current Dashboard against an isolated in-memory test catalog.

Run: .eigda143/bin/python tests/render_dashboard_fixture.py /tmp/dashboard.html
Then: NODE_PATH=/path/to/jsdom/node_modules node tests/test_dashboard.cjs /tmp/dashboard.html
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_international_catalog import CatalogTests
from services.catalog_update import update_catalog
from extensions import db


def main():
    fixture = CatalogTests()
    fixture.setUp()
    try:
        update_catalog(db.session)
        db.session.commit()
        client = fixture.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=-1, role='user', full_name='Dashboard fixture')
        response = client.get('/dashboard')
        assert response.status_code == 200
        Path(sys.argv[1]).write_bytes(response.data)
        print('Rendered isolated dashboard fixture.')
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
