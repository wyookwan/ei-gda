"""Explicit first-install setup; refuses non-empty application databases."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from getpass import getpass
from app import app
from extensions import db
from models import User, Template, Standard, StandardItem
from seed_data import SEED_DATA
from utils import json_dumps
from werkzeug.security import generate_password_hash


def main():
    with app.app_context():
        db.create_all()
        if User.query.first() or Template.query.first() or Standard.query.first():
            raise SystemExit('Database is not empty. Bootstrap refused; existing data is unchanged.')
        email = input('Admin email: ').strip()
        password = getpass('Admin password (12+ characters): ')
        if '@' not in email or len(password) < 12 or password != getpass('Confirm password: '):
            raise SystemExit('Invalid email/password or confirmation mismatch.')
        db.session.add(User(email=email, full_name='Administrator', role='admin',
                            password_hash=generate_password_hash(password), auth_provider='local', is_active=True))
        for index, source in enumerate(SEED_DATA['templates'], 1):
            db.session.add(Template(name=source['name'], description=source['description'],
                sections_json=json_dumps(source['sections']), prompt_structure='\n'.join(source['sections']),
                pass_threshold=source['pass_threshold'], display_order=index,
                applicable_framework_codes_json=json_dumps(source['applicable_framework_codes'])))
        for source in SEED_DATA['standards']:
            standard = Standard(**{key:source[key] for key in ('code','name','description','source_type','jurisdiction','publisher','reference_url','published_year','status') if key in source})
            db.session.add(standard); db.session.flush()
            for index, (code, category, title, keywords) in enumerate(source['items'],1):
                db.session.add(StandardItem(standard_id=standard.id,item_code=code,category=category,title=title,keywords_json=json_dumps(keywords),order_index=index))
        db.session.commit()
        print('Initial catalog and administrator created. No demo users created.')

if __name__ == '__main__':
    main()
