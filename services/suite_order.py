"""Additive schema upgrade for persistent Test Suite display order."""
from sqlalchemy import inspect, text


def ensure_suite_order(engine):
    if 'display_order' in {column['name'] for column in inspect(engine).get_columns('templates')}:
        return False
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE templates ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0'))
        rows = connection.execute(text('SELECT id FROM templates ORDER BY name, id')).all()
        for position, row in enumerate(rows, 1):
            connection.execute(text('UPDATE templates SET display_order = :position WHERE id = :id'),
                               {'position': position, 'id': row.id})
    return True
