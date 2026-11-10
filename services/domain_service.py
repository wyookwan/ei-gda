"""V15 declarative domain packs. Pilot controls are NOT legal determinations."""
import json
from pathlib import Path
from functools import lru_cache
PACK_DIR = Path(__file__).resolve().parent.parent / 'domain_packs'

@lru_cache(maxsize=32)
def get_pack(slug):
    if not isinstance(slug, str) or not slug.replace('_', '').isalnum():
        return None
    path = PACK_DIR / (slug + '.json')
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('slug') != slug or not isinstance(data.get('controls'), list):
        return None
    return data

def list_packs():
    result = []
    for path in sorted(PACK_DIR.glob('*.json')):
        pack = get_pack(path.stem)
        if pack:
            result.append(pack)
    return result

def evidence_review(pack, statuses):
    """Manual evidence-review coverage, not legal compliance or model score."""
    controls = pack['controls']
    allowed = {'evidenced', 'partial', 'missing', 'not_assessed', 'not_applicable'}
    if set(statuses) - {row['id'] for row in controls}:
        raise ValueError('Unknown control')
    if any(value not in allowed for value in statuses.values()):
        raise ValueError('Invalid status')
    active = [c for c in controls if statuses.get(c['id']) != 'not_applicable']
    covered = sum(1 if statuses.get(c['id']) == 'evidenced' else .5 if statuses.get(c['id']) == 'partial' else 0 for c in active)
    return {'coverage_percent': round(100 * covered / len(active), 1) if active else None,
            'assessed_count': sum(statuses.get(c['id'], 'not_assessed') not in ('not_assessed','not_applicable') for c in active),
            'applicable_count': len(active),
            'critical_open': [c['id'] for c in active if c.get('critical') and statuses.get(c['id']) != 'evidenced'],
            'method': 'manual_evidence_coverage_not_compliance'}
