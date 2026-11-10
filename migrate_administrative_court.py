"""Add the Administrative Court domain (administrative_court). Additive and idempotent.

The domain lives in domain_packs/v16/administrative_court.json and the registry; this script runs the same
safe migration as the pilot (no schema change is needed for this domain) and reports what was synced.

  python migrate_administrative_court.py [--database-url sqlite:///copy.db]

Rollback (keeps all data): set EIGDA_DISABLED_DOMAINS=administrative_court in .env and re-run this script.
The domain disappears from selectors; existing assessments stay readable by their links.
"""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database-url')
    args = parser.parse_args()
    if args.database_url:
        os.environ['DATABASE_URL'] = args.database_url
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import app
    from migrate_mhesi_pilot import run
    from services.domain_catalog import disabled_domains
    report = run(app)
    from models import DomainControl, DomainProfile
    from extensions import db
    with app.app_context():
        profile = db.session.get(DomainProfile, 'administrative_court')
        controls = DomainControl.query.filter_by(domain_slug='administrative_court', is_active=True).count()
        state = 'disabled (rollback)' if 'administrative_court' in disabled_domains() else ('active' if profile and profile.is_active else 'missing')
    print('Catalog synced:', report['catalog'])
    print('Row counts unchanged:', report['before'] == {k: v for k, v in report['after'].items() if k in report['before']})
    print(f'administrative_court: {state}; {controls} active controls')


if __name__ == '__main__':
    main()
