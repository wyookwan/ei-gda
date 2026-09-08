import json
import re
import requests
from config import Config


def local_model_enabled():
    return bool(Config.LOCAL_MODEL_API_URL.strip())


def _models_url():
    url = Config.LOCAL_MODEL_API_URL.rstrip('/')
    suffix = '/v1/chat/completions'
    if url.endswith(suffix):
        return url[:-len('/chat/completions')] + '/models'
    return None


def resolve_local_model_name():
    """Use LOCAL_MODEL_NAME when supplied; otherwise discover the first OpenAI-compatible model."""
    configured = (Config.LOCAL_MODEL_NAME or '').strip()
    if configured:
        return configured
    models_url = _models_url()
    if not models_url:
        return 'local-model'
    try:
        response = requests.get(models_url, timeout=min(20, Config.LOCAL_MODEL_TIMEOUT), verify=Config.LOCAL_MODEL_VERIFY_SSL)
        response.raise_for_status()
        data = response.json().get('data', [])
        if data and data[0].get('id'):
            return data[0]['id']
    except Exception:
        pass
    return 'local-model'


def _parse_json_content(text):
    text = (text or '').strip().replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def score_with_local_model(extracted_text, retrieved_items, evidence_map=None):
    """Score a confidential assessment in context-safe batches.

    Multiple PDFs can produce more evidence than the local model's context window can
    hold. Each batch is an independent OpenAI-compatible request and the item results
    are merged before hybrid scoring. No Authorization/API-key header is sent.
    """
    model_name = resolve_local_model_name()
    if not local_model_enabled():
        return {'used': False, 'error': 'Local Model API is not configured.', 'items': [], 'model': model_name}
    if not retrieved_items:
        return {'used': False, 'error': 'No relevant assessment items were found for the uploaded documents.', 'items': [], 'model': model_name}
    evidence_map = evidence_map or {}
    items_payload = []
    for x in retrieved_items:
        refs = []
        for e in evidence_map.get(x['item_code'], [])[:2]:
            refs.append({
                'source_file': e.get('filename'),
                'page': e.get('page'),
                'evidence': (e.get('snippet') or '')[:600],
                'relevance': e.get('relevance'),
            })
        items_payload.append({
            'item_code': x['item_code'],
            'title': x['title'],
            'category': x.get('category'),
            'keywords': x.get('keywords', []),
            'traceable_evidence': refs,
        })

    headers = {'Content-Type': 'application/json'}
    batch_size = Config.LOCAL_MODEL_BATCH_SIZE
    batches = [items_payload[i:i + batch_size] for i in range(0, len(items_payload), batch_size)]
    merged_items = []
    summaries = []

    for batch_number, batch_items in enumerate(batches, start=1):
        prompt = {
            'instruction': (
                'You are an evidence-grounded digital assurance auditor. Score EVERY supplied checklist item '
                'using ONLY its traceable evidence. Use integer maturity scores 0-5: 0 Not Implemented, '
                '1 Initial, 2 Defined, 3 Implemented, 4 Managed, 5 Optimized. Return strict JSON. '
                'Do not invent evidence. If evidence is absent or insufficient, score conservatively. '
                'For each item provide a concise reason, gap, and actionable recommendation.'
            ),
            'schema': {
                'items': [{'item_code':'string','score':0,'reason':'string','gap':'string','recommendation':'string'}],
                'summary':'string'
            },
            'items': batch_items,
            'document_excerpt_for_context_only': (extracted_text or '')[:3000],
        }
        body = {
            'model': model_name,
            'temperature': 0,
            'max_tokens': Config.LOCAL_MODEL_MAX_TOKENS,
            'messages': [{'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)}],
        }
        resp = None
        try:
            resp = requests.post(
                Config.LOCAL_MODEL_API_URL,
                headers=headers,
                json=body,
                timeout=Config.LOCAL_MODEL_TIMEOUT,
                verify=Config.LOCAL_MODEL_VERIFY_SSL,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data['choices'][0]['message']['content']
            batch_result = _parse_json_content(content)
            returned_items = batch_result.get('items', [])
            if not returned_items:
                raise ValueError('The model returned no item scores.')
            merged_items.extend(returned_items)
            if batch_result.get('summary'):
                summaries.append(str(batch_result['summary']))
        except Exception as exc:
            detail = str(exc)
            try:
                api_error = resp.json().get('error', {}) if resp is not None else {}
                detail = api_error.get('message') or detail
            except Exception:
                pass
            return {
                'used': False,
                'error': f'Batch {batch_number}/{len(batches)} failed: {detail}',
                'items': [],
                'model': model_name,
                'batch_count': len(batches),
            }

    return {
        'used': True,
        'items': merged_items,
        'summary': ' '.join(summaries),
        'model': model_name,
        'batch_count': len(batches),
    }
