"""Read-only hierarchy using the same enabled catalog as assessment selection."""
from collections import OrderedDict
from models import Template, Standard, StandardItem
from services.standards_catalog import item_metadata
from utils import json_loads

TYPE_LABELS = OrderedDict([
    ('international_standard', 'International Standards'),
    ('international_standard_draft', 'International Standards — Draft readiness'),
    ('international_framework', 'International Frameworks'),
    ('international_principles', 'International Principles'),
    ('international_regulation', 'International Laws / Regulations'),
    ('thai_standard', 'Thai Standards / Data Governance'),
    ('thai_guideline', 'Thai Guidelines'),
    ('thai_law', 'Thai Laws & Regulations'),
])


def build_suite_tree(evidence_for_item):
    suites = Template.query.filter_by(is_enabled=True).order_by(Template.display_order, Template.name, Template.id).all()
    mappings = {s.id: json_loads(s.applicable_framework_codes_json, default=[]) for s in suites}
    codes = {code for values in mappings.values() for code in values}
    standards = Standard.query.filter(Standard.is_enabled.is_(True), Standard.code.in_(codes)).order_by(Standard.code).all()
    items = StandardItem.query.filter(StandardItem.is_enabled.is_(True), StandardItem.standard_id.in_([s.id for s in standards])).order_by(StandardItem.order_index, StandardItem.id).all()
    by_standard = {}
    for item in items:
        domains = by_standard.setdefault(item.standard_id, OrderedDict())
        domains.setdefault(item.category or 'Other', []).append({
            'item': item, 'evidence': evidence_for_item(item),
            'provenance': item_metadata().get(item.item_code),
        })
    tree = []
    for suite in suites:
        mapped = set(mappings[suite.id])
        groups = OrderedDict()
        for standard in standards:
            if standard.code not in mapped:
                continue
            domains = by_standard.get(standard.id, {})
            groups.setdefault(standard.source_type, []).append({
                'standard': standard,
                'domains': [{'name': name, 'rows': rows} for name, rows in domains.items()],
                'count': sum(len(rows) for rows in domains.values()),
            })
        keys = sorted(groups, key=lambda key: (list(TYPE_LABELS).index(key) if key in TYPE_LABELS else len(TYPE_LABELS), key))
        tree.append({'suite': suite, 'reference_count': sum(len(refs) for refs in groups.values()),
                     'groups': [{'label': TYPE_LABELS.get(key, key.replace('_', ' ').title()),
                                 'references': groups[key]} for key in keys]})
    return tree
