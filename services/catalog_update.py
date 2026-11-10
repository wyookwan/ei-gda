"""Additive catalog import. Never updates users, assessments or existing legacy items."""
from models import Standard, StandardItem, Template
from services.standards_catalog import load_catalog, standard_fields
from utils import json_dumps, json_loads


def snapshot_catalog(session):
    codes = [s['code'] for s in load_catalog()['standards']]
    names = list(load_catalog()['suite_mappings'])
    standards = session.query(Standard).filter(Standard.code.in_(codes)).all()
    suites = session.query(Template).filter(Template.name.in_(names)).all()
    ids = [s.id for s in standards]
    items = session.query(StandardItem).filter(StandardItem.standard_id.in_(ids)).all()

    def serialize(row):
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    return {'standards': [serialize(s) for s in standards],
            'standard_items': [serialize(i) for i in items],
            'templates': [serialize(t) for t in suites]}


def update_catalog(session):
    """Stage an idempotent update; caller owns backup, commit and rollback."""
    from seed_data import SEED_DATA
    catalog = load_catalog()
    stats = {'new_standards': 0, 'new_items': 0, 'new_suites': 0}
    for source in catalog['standards']:
        standard = session.query(Standard).filter_by(code=source['code']).first()
        if standard is None:
            standard = Standard(code=source['code'], name=source['name'])
            session.add(standard)
            stats['new_standards'] += 1
        for key, value in standard_fields(source).items():
            setattr(standard, key, value)
        standard.is_enabled = True
        session.flush()
        existing = {i.item_code: i for i in session.query(StandardItem).filter_by(standard_id=standard.id)}
        next_order = max((i.order_index for i in existing.values()), default=0)
        # Only the new, source-traceable items are upserted. Legacy/custom items stay intact.
        for payload in source['items']:
            item = existing.get(payload['item_code'])
            if item is None:
                next_order += 1
                item = StandardItem(standard_id=standard.id, item_code=payload['item_code'],
                                    order_index=next_order, weight=1.0)
                session.add(item)
                stats['new_items'] += 1
            item.category = payload['category']
            item.title = payload['title']
            item.keywords_json = json_dumps(payload['keywords'])
            item.is_enabled = True
    seed_suites = {s['name']: s for s in SEED_DATA['templates']}
    for name, codes in catalog['suite_mappings'].items():
        suite = session.query(Template).filter_by(name=name).first()
        if suite is None:
            source = seed_suites[name]
            suite = Template(name=name, description=source['description'],
                             display_order=max((row.display_order for row in session.query(Template)), default=0) + 1,
                             sections_json=json_dumps(source['sections']),
                             prompt_structure='\n'.join(source['sections']),
                             pass_threshold=source['pass_threshold'],
                             applicable_framework_codes_json='[]')
            session.add(suite)
            stats['new_suites'] += 1
        current = json_loads(suite.applicable_framework_codes_json, default=[])
        suite.applicable_framework_codes_json = json_dumps(list(dict.fromkeys(current + codes)))
        suite.is_enabled = True
    session.flush()
    return stats
