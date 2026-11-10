"""Prove the pilot migration on a COPY of an existing database, without touching MySQL.

Loads a mysqldump file into a temporary SQLite database (pre-pilot V16 schema), runs
migrate_mhesi_pilot twice, and checks that row counts are unchanged, no existing work gained an
organization, and existing owners keep access. Prints counts only, never row contents.

  python tools/verify_migration_on_dump.py <dump.sql> <work_dir> [--keep]
"""
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESC = {'0': '\0', 'n': '\n', 'r': '\r', 't': '\t', 'Z': '\x1a', 'b': '\b'}


def parse_values(text):
    """Parse the VALUES part of a mysqldump INSERT into tuples."""
    rows, row, i, n = [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '(' and row is None:
            row, i = [], i + 1
            continue
        if row is None:
            i += 1
            continue
        if ch == "'":
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == '\\':
                    buf.append(ESC.get(text[i + 1], text[i + 1]))
                    i += 2
                elif c == "'" and i + 1 < n and text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                elif c == "'":
                    i += 1
                    break
                else:
                    buf.append(c)
                    i += 1
            row.append(''.join(buf))
        elif ch in ',\n ':
            i += 1
        elif ch == ')':
            rows.append(tuple(row))
            row, i = None, i + 1
        else:
            m = re.match(r"NULL|-?[0-9.eE+-]+|0x[0-9A-Fa-f]+", text[i:])
            token = m.group(0)
            row.append(None if token == 'NULL' else (int(token) if re.fullmatch(r'-?\d+', token) else float(token) if not token.startswith('0x') else bytes.fromhex(token[2:])))
            i += len(token)
    return rows


def load(dump, db_path):
    sql = Path(dump).read_text(encoding='utf-8', errors='replace')
    columns = {m.group(1): re.findall(r'^\s+`(\w+)`', m.group(2), re.M) for m in re.finditer(r'CREATE TABLE `(\w+)` \((.*?)\n\) ENGINE', sql, re.S)}
    con = sqlite3.connect(db_path)
    con.executescript((ROOT / 'tests' / 'fixtures' / 'legacy_v16_schema.sql').read_text())
    counts = {}
    for m in re.finditer(r'^INSERT INTO `(\w+)` VALUES (.*);$', sql, re.M):
        table, rows = m.group(1), parse_values(m.group(2))
        existing = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        cols = columns[table]
        keep = [i for i, c in enumerate(cols) if c in existing]
        names = ', '.join(cols[i] for i in keep)
        con.executemany(f'INSERT INTO {table} ({names}) VALUES ({", ".join("?" * len(keep))})', [tuple(r[i] for i in keep) for r in rows])
        counts[table] = counts.get(table, 0) + len(rows)
    con.commit()
    con.close()
    return counts


def main():
    dump, work = sys.argv[1], Path(sys.argv[2]).resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    db_path = work / 'copy.db'
    loaded = load(dump, db_path)
    print('Loaded rows from dump:', loaded)
    os.environ.update(DATABASE_URL=f'sqlite:///{db_path}', GEMINI_API_KEY='', LOCAL_MODEL_API_URL='', UPLOAD_FOLDER=str(work / 'uploads'), REPORT_FOLDER=str(work / 'reports'))
    sys.path.insert(0, str(ROOT))
    from app import app
    from migrate_mhesi_pilot import run
    first, second = run(app), run(app)
    print('First run added', len(first['columns_added']), 'columns/indexes; second run added', len(second['columns_added']))
    print('Counts before:', first['before'])
    print('Counts after: ', second['after'])
    ok = all(second['after'][t] == first['before'][t] for t in first['before']) and not second['columns_added']
    con = sqlite3.connect(db_path)
    scoped = con.execute('SELECT COUNT(*) FROM document_checks WHERE organization_id IS NOT NULL').fetchone()[0]
    con.close()
    from services import access_policy as ap
    from models import DocumentCheck
    with app.test_request_context('/'):
        from flask import session
        kept = 0
        checks = DocumentCheck.query.all()
        for check in checks:
            session.clear()
            session.update(user_id=check.user_id, role='user')
            kept += ap.READ_SOURCE in ap.check_permissions(check)
    print(f'Existing checks scoped to an organization: {scoped}; owners keeping source access: {kept}/{len(checks)}')
    ok = ok and scoped == 0 and kept == len(checks)
    print('RESULT:', 'PASS' if ok else 'FAIL')
    if '--keep' not in sys.argv:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
