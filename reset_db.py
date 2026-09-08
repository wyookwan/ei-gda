from flask import Flask
from config import Config
from extensions import db
import models  # registers all models

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

if __name__ == '__main__':
    with app.app_context():
        db.drop_all()
        db.create_all()
    print('Tables recreated from models.py. Now run: python seed.py')
