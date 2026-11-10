import json
import re
import requests
from config import Config


class TokenBudgetExhausted(Exception):
    """The model used its whole token budget without producing an answer."""


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


def score_with_local_model(extracted_text, retrieved_items, evidence_map=None, instruction=None):
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

    def request_batch(batch_items):
        """Call the model once. Reasoning models can spend the token budget and return no content."""
        prompt = {
            'instruction': instruction or (
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
        resp = requests.post(
            Config.LOCAL_MODEL_API_URL,
            headers=headers,
            json=body,
            timeout=Config.LOCAL_MODEL_TIMEOUT,
            verify=Config.LOCAL_MODEL_VERIFY_SSL,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            detail = ''
            try:
                detail = resp.json().get('error', {}).get('message') or ''
            except Exception:
                pass
            raise RuntimeError(detail or str(exc)) from exc
        choice = resp.json()['choices'][0]
        content = (choice.get('message') or {}).get('content')
        if not (content or '').strip():
            raise TokenBudgetExhausted(f"model returned no content (finish_reason={choice.get('finish_reason')})")
        return _parse_json_content(content)

    def run_batch(batch_items):
        """Halve a batch when the answer is cut off or unparsable, so one large batch cannot fail a run."""
        try:
            result = request_batch(batch_items)
        except (TokenBudgetExhausted, ValueError) as exc:
            if len(batch_items) <= 1:
                raise
            middle = len(batch_items) // 2
            return run_batch(batch_items[:middle]) + run_batch(batch_items[middle:])
        returned = result.get('items', [])
        if not returned:
            raise ValueError('The model returned no item scores.')
        if result.get('summary'):
            summaries.append(str(result['summary']))
        return returned

    for batch_number, batch_items in enumerate(batches, start=1):
        try:
            merged_items.extend(run_batch(batch_items))
        except Exception as exc:
            return {
                'used': False,
                'error': f'Batch {batch_number}/{len(batches)} failed: {exc}',
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
