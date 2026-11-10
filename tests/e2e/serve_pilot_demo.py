"""Pilot DEMO server for browser E2E: fresh SQLite database + DEMO seed. Never connects to MySQL or a model.

Usage: python tests/e2e/serve_pilot_demo.py <work_dir> <port>
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
work, port = Path(sys.argv[1]).resolve(), int(sys.argv[2])
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
# Environment wins over .env, so the DEMO cannot reach the real database, Gemini or the local model.
os.environ.update(DATABASE_URL=f'sqlite:///{work}/pilot_demo.db', UPLOAD_FOLDER=str(work / 'uploads'), REPORT_FOLDER=str(work / 'reports'), DEMO_MODE='True',
                  GEMINI_API_KEY='', LOCAL_MODEL_API_URL='', THAID_ENABLED='False', ADMIN_LOGIN_ALIAS='', SECRET_KEY='pilot-e2e-only-' + 'x' * 40)
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from app import app  # noqa: E402
from migrate_mhesi_pilot import run  # noqa: E402
from services.pilot_demo import seed  # noqa: E402

run(app)
print(seed(app, os.getenv('DEMO_PASSWORD', 'Demo-Pilot-2569')), flush=True)
app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
