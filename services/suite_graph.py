"""Read-only knowledge graph of the Test Suite catalog for the 3D explorer.

Layers: Test Suite -> Standard/Law -> Category -> Item, plus Keyword nodes that
link items across standards (the same keywords the Hybrid KG retrieval uses).
Only keywords shared by at least `min_shared` items are kept, so the keyword
layer shows real cross-links instead of one leaf per word.
"""
from collections import Counter, defaultdict

from models import Standard, StandardItem, Template
from services.standards_catalog import item_metadata
from utils import json_loads

THAI_TYPES = {'thai_standard', 'thai_guideline', 'thai_law'}
MAX_KEYWORDS = 80


def enabled_suites():
    return Template.query.filter_by(is_enabled=True).order_by(Template.display_order, Template.name, Template.id).all()


def build_suite_graph(suite_ids, include_keywords=True, min_shared=2):
    suites = [s for s in enabled_suites() if s.id in set(suite_ids)]
    mapping = {s.id: json_loads(s.applicable_framework_codes_json, default=[]) for s in suites}
    codes = {c for values in mapping.values() for c in values}
    standards = Standard.query.filter(Standard.is_enabled.is_(True), Standard.code.in_(codes)).order_by(Standard.code).all() if codes else []
    std_by_code = {s.code: s for s in standards}
    items = StandardItem.query.filter(StandardItem.is_enabled.is_(True), StandardItem.standard_id.in_([s.id for s in standards])) \
        .order_by(StandardItem.standard_id, StandardItem.order_index, StandardItem.id).all() if standards else []

    nodes, links, seen = [], [], set()

    def add(node):
        if node['id'] not in seen:
            seen.add(node['id'])
            nodes.append(node)

    suites_per_standard = defaultdict(list)
    for s in suites:
        add({'id': f'suite:{s.id}', 'kind': 'suite', 'label': s.name, 'code': s.suite_code or '',
             'detail': s.description or '', 'standards': 0})
        for code in mapping[s.id]:
            st = std_by_code.get(code)
            if st:
                suites_per_standard[st.id].append(s.id)
                links.append({'source': f'suite:{s.id}', 'target': f'std:{st.id}', 'rel': 'maps_to'})

    items_per_standard = Counter(i.standard_id for i in items)
    for st in standards:
        add({'id': f'std:{st.id}', 'kind': 'standard', 'label': st.name, 'code': st.code,
             'region': 'thai' if st.source_type in THAI_TYPES else 'international',
             'source_type': st.source_type, 'publisher': st.publisher or '', 'jurisdiction': st.jurisdiction or '',
             'year': st.published_year, 'status': st.status or '', 'url': st.reference_url or '',
             'items': items_per_standard.get(st.id, 0), 'shared_by': len(suites_per_standard[st.id])})
    for n in nodes:
        if n['kind'] == 'suite':
            n['standards'] = sum(1 for l in links if l['source'] == n['id'])

    keyword_items = defaultdict(set)
    meta = item_metadata()
    for it in items:
        cat_name = it.category or 'อื่น ๆ'
        cat_id = f'cat:{it.standard_id}:{cat_name}'
        if cat_id not in seen:
            add({'id': cat_id, 'kind': 'category', 'label': cat_name, 'standard_id': f'std:{it.standard_id}'})
            links.append({'source': f'std:{it.standard_id}', 'target': cat_id, 'rel': 'contains'})
        researched = meta.get(it.item_code) or {}
        add({'id': f'item:{it.id}', 'kind': 'item', 'label': it.title, 'code': it.item_code, 'weight': it.weight,
             'evidence': researched.get('evidence_expected', ''), 'standard_id': f'std:{it.standard_id}'})
        links.append({'source': cat_id, 'target': f'item:{it.id}', 'rel': 'contains'})
        for kw in json_loads(it.keywords_json, default=[]):
            key = (kw or '').strip().lower()
            if key:
                keyword_items[key].add(it.id)

    keyword_count = 0
    if include_keywords:
        shared = sorted(((k, ids) for k, ids in keyword_items.items() if len(ids) >= min_shared),
                        key=lambda kv: (-len(kv[1]), kv[0]))[:MAX_KEYWORDS]
        for key, ids in shared:
            add({'id': f'kw:{key}', 'kind': 'keyword', 'label': key, 'items': len(ids)})
            links.extend({'source': f'item:{i}', 'target': f'kw:{key}', 'rel': 'keyword'} for i in sorted(ids))
        keyword_count = len(shared)

    counts = Counter(n['kind'] for n in nodes)
    return {'nodes': nodes, 'links': links,
            'stats': {'suites': counts['suite'], 'standards': counts['standard'], 'categories': counts['category'],
                      'items': counts['item'], 'keywords': keyword_count, 'links': len(links),
                      'shared_standards': sum(1 for v in suites_per_standard.values() if len(v) > 1)}}
