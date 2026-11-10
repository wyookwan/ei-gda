"""Public-source readiness catalog; no network or database side effects."""
import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / 'data' / 'international_standards_v14_3.json'


@lru_cache(maxsize=1)
def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def standard_metadata():
    return {row['code']: row for row in load_catalog()['standards']}


@lru_cache(maxsize=1)
def item_metadata():
    return {item['item_code']: dict(item, standard_code=row['code'],
                                   checked_on=row['checked_on'])
            for row in load_catalog()['standards'] for item in row['items']}


def standard_fields(row):
    description = (
        row['scope_summary'] + '\n' + row['applicability'] + '\n'
        'Ei-GDA readiness questions derived from public scope; not ISO clauses or certification criteria. '
        'Evidence examples are suggestions. Source checked: ' + row['checked_on']
    )
    return {**{key: row[key] for key in (
        'name', 'source_type', 'jurisdiction', 'publisher', 'reference_url',
        'published_year', 'status')}, 'description': description}


def merge_into_seed(seed_data):
    """Add new entries while retaining legacy item identifiers and other references."""
    catalog = load_catalog()
    existing = {row['code']: row for row in seed_data['standards']}
    for source in catalog['standards']:
        target = existing.get(source['code'])
        if target is None:
            target = {'code': source['code'], 'items': []}
            seed_data['standards'].append(target)
            existing[source['code']] = target
        target.update(standard_fields(source))
        by_code = {item[0]: index for index, item in enumerate(target['items'])}
        for item in source['items']:
            value = [item['item_code'], item['category'], item['title'], item['keywords']]
            if item['item_code'] in by_code:
                target['items'][by_code[item['item_code']]] = value
            else:
                target['items'].append(value)
    for suite in seed_data['templates']:
        additions = catalog['suite_mappings'].get(suite['name'], [])
        suite['applicable_framework_codes'] = list(dict.fromkeys(
            suite.get('applicable_framework_codes', []) + additions))
    return seed_data
