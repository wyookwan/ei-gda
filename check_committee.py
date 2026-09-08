from flask import Flask
from werkzeug.security import check_password_hash
from config import Config
from extensions import db
from models import User

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    u = User.query.filter_by(email='committee1@buu.local').first()
    if not u:
        print('Committee: MISSING (run python seed.py)')
    else:
        print('Committee ID:', u.id)
        print('Email:', u.email)
        print('Role:', u.role)
        print('Active:', u.is_active)
        print('Auth provider:', u.auth_provider)
        print('Password check:', check_password_hash(u.password_hash, 'Committee@2026'))
        print('LOGIN CHECK:', 'PASS' if u.role == 'committee' and u.is_active and check_password_hash(u.password_hash, 'Committee@2026') else 'FAIL')
