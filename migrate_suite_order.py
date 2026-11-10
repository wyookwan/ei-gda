"""Add persistent ordering without changing accounts or assessment history."""
from flask import Flask
from config import Config
from extensions import db
from services.suite_order import ensure_suite_order

if __name__ == '__main__':
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    with app.app_context():
        changed = ensure_suite_order(db.engine)
        print('Test Suite display order:', 'added; initialized by name' if changed else 'already installed; order preserved')
