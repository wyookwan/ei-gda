"""Run with --apply to update only the researched international catalog.

Default: read-only preview. No seed/reset, user updates, external AI calls or schema changes.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask
from config import Config
from extensions import db
from models import Standard, StandardItem
from services.catalog_update import snapshot_catalog, update_catalog
from services.standards_catalog import load_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        **app.config['SQLALCHEMY_ENGINE_OPTIONS'], 'connect_args': {'connect_timeout': 5}}
    db.init_app(app)
    catalog = load_catalog()
    with app.app_context():
        try:
            existing_codes = {row.code for row in Standard.query.all()}
            existing_items = {row.item_code for row in StandardItem.query.all()}
            new_codes = [s['code'] for s in catalog['standards'] if s['code'] not in existing_codes]
            new_items = [i for s in catalog['standards'] for i in s['items']
                         if i['item_code'] not in existing_items]
            print(f'Catalog: {len(catalog["standards"])} references; '
                  f'{sum(len(s["items"]) for s in catalog["standards"])} researched readiness items')
            print(f'Planned additions: {len(new_codes)} references; {len(new_items)} items')
            print('Suite mappings: 8; users and assessment history: unchanged')
            if not args.apply:
                print('Preview only. Use --apply to import.')
                return
            backup_dir = Path(__file__).resolve().parent / 'reports'
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup_path = backup_dir / f'catalog_before_v14_3_{stamp}.json'
            snapshot = snapshot_catalog(db.session)
            backup_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            stats = update_catalog(db.session)
            db.session.commit()
            print('Applied:', json.dumps(stats))
            print('Catalog backup:', backup_path)
        except Exception as exc:
            db.session.rollback()
            # Do not print connection URIs, credentials or document content.
            print(f'Catalog update failed ({type(exc).__name__}); transaction rolled back.')
            raise SystemExit(1) from None


if __name__ == '__main__':
    main()
