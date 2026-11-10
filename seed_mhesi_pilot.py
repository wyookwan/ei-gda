"""Create a separate DEMO database for the MHESI pilot. Never touches the database in .env.

  python seed_mhesi_pilot.py                       # demo/pilot_demo.db (SQLite) + demo/uploads
  python seed_mhesi_pilot.py --reset               # delete and recreate the DEMO database
  python seed_mhesi_pilot.py --complete-case-b     # also walk case B through review to confirmation

Then run the DEMO app:
  DATABASE_URL=sqlite:///$(pwd)/demo/pilot_demo.db UPLOAD_FOLDER=demo/uploads REPORT_FOLDER=demo/reports DEMO_MODE=True python app.py

All accounts are <name>@demo.invalid with the password printed at the end. All data is fictional.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database-url', default=f'sqlite:///{ROOT / "demo" / "pilot_demo.db"}')
    parser.add_argument('--uploads', default=str(ROOT / 'demo' / 'uploads'))
    parser.add_argument('--password', default=os.getenv('DEMO_PASSWORD', 'Demo-Pilot-2569'))
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--complete-case-b', action='store_true')
    args = parser.parse_args()
    url = args.database_url
    if not url.startswith('sqlite:///'):
        name = url.rsplit('/', 1)[-1].split('?')[0].lower()
        if 'demo' not in name and 'test' not in name:
            raise SystemExit('Refusing: a non-SQLite DEMO database name must contain "demo" or "test".')
        from dotenv import dotenv_values
        if name == (dotenv_values(ROOT / '.env').get('MYSQL_DB') or '').lower():
            raise SystemExit('Refusing: this is the database configured in .env.')
    db_file = Path(url.replace('sqlite:///', '')) if url.startswith('sqlite:///') else None
    if args.reset:
        if db_file and db_file.exists():
            db_file.unlink()
        shutil.rmtree(args.uploads, ignore_errors=True)
    if db_file:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    os.makedirs(args.uploads, exist_ok=True)
    # Environment wins over .env (python-dotenv does not override), so the DEMO never reaches real services or data.
    os.environ.update(DATABASE_URL=url, UPLOAD_FOLDER=args.uploads, REPORT_FOLDER=str(Path(args.uploads).parent / 'reports'), DEMO_MODE='True',
                      GEMINI_API_KEY='', LOCAL_MODEL_API_URL='', THAID_ENABLED='False')
    sys.path.insert(0, str(ROOT))
    from app import app
    from migrate_mhesi_pilot import run
    run(app)
    from services.pilot_demo import run_case_b, seed
    result = seed(app, args.password)
    if result['status'] == 'already_seeded':
        print('DEMO data already present. Use --reset to recreate.')
        return
    if args.complete_case_b:
        run_case_b(app, result['case_b'])
        print('Case B walked through submit -> request changes -> resubmit -> close issue -> confirm.')
    print('DEMO database:', url)
    print('Accounts (password: %s):' % args.password)
    for email in result['users']:
        print('  ', email)
    print('Case A assessment id:', result['case_a'], '(submitted, waiting for a reviewer)')
    print('Case B assessment id:', result['case_b'], '(confirmed)' if args.complete_case_b else '(ready to submit)')


if __name__ == '__main__':
    main()
