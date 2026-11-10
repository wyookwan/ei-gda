"""Apply the retention policy in services/retention.py.

  python purge_retention.py                 # report only
  python purge_retention.py --apply         # delete expired notifications and logs (evidence is report-only)
  python purge_retention.py --database-url sqlite:///demo/pilot_demo.db
"""
import argparse
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--database-url')
    args = parser.parse_args()
    if args.database_url:
        os.environ['DATABASE_URL'] = args.database_url
    from app import app
    from services.retention import POLICY, report
    with app.app_context():
        result = report(apply=args.apply)
    for key, count in result.items():
        action = 'deleted' if args.apply and POLICY[key]['auto_delete'] else 'found'
        print(f"{POLICY[key]['th']}: {count} {action} (older than {POLICY[key]['days']} days)")


if __name__ == '__main__':
    main()
