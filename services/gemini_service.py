import json

import requests

from config import Config


def gemini_enabled():
    return bool(Config.GEMINI_API_KEY and Config.GEMINI_MODEL)


def score_with_gemini(extracted_text, retrieved_items, evidence_map=None):
    """Score OPEN documents with Gemini using traceable PDF evidence."""
    if not gemini_enabled():
        return {'used': False, 'error': 'Gemini is not configured.', 'items': [], 'model': Config.GEMINI_MODEL}
    if not retrieved_items:
        return {
            'used': False,
            'error': 'No relevant assessment items were found for the uploaded document.',
            'items': [],
            'model': Config.GEMINI_MODEL,
        }

    evidence_map = evidence_map or {}
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{Config.GEMINI_MODEL}:generateContent"
    )
    items_payload = []
    for item in retrieved_items:
        refs = [
            {
                'source_file': evidence.get('filename'),
                'page': evidence.get('page'),
                'evidence': (evidence.get('snippet') or '')[:900],
                'relevance': evidence.get('relevance'),
            }
            for evidence in evidence_map.get(item['item_code'], [])[:4]
        ]
        items_payload.append({
            'item_code': item['item_code'],
            'title': item['title'],
            'category': item.get('category'),
            'keywords': item.get('keywords', []),
            'traceable_evidence': refs,
        })

    prompt = {
        'instruction': (
            'You are an evidence-grounded digital assurance auditor. Score every checklist item '
            'using ONLY traceable evidence supplied from the uploaded PDF files. Use integer '
            'maturity scores 0-5: 0 Not Implemented, 1 Initial, 2 Defined, 3 Implemented, '
            '4 Managed, 5 Optimized. Return strict JSON. Do not invent evidence. If evidence is '
            'absent or insufficient, score conservatively. For every item provide a concise reason, '
            'governance/compliance gap, and actionable recommendation.'
        ),
        'schema': {
            'items': [{
                'item_code': 'string', 'score': 0, 'reason': 'string',
                'gap': 'string', 'recommendation': 'string'
            }],
            'summary': 'string',
        },
        'items': items_payload,
        'document_excerpt_for_context_only': (extracted_text or '')[:8000],
    }
    body = {
        'contents': [{'parts': [{'text': json.dumps(prompt, ensure_ascii=False)}]}],
        'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json'},
    }
    try:
        response = requests.post(
            endpoint,
            headers={'Content-Type': 'application/json', 'x-goog-api-key': Config.GEMINI_API_KEY},
            json=body,
            timeout=Config.GEMINI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        text = data['candidates'][0]['content']['parts'][0]['text']
        result = json.loads(text)
        result['used'] = True
        result['model'] = Config.GEMINI_MODEL
        return result
    except requests.HTTPError as exc:
        message = f'Gemini API returned HTTP {exc.response.status_code}.'
        try:
            api_error = exc.response.json().get('error', {})
            api_message = api_error.get('message')
            api_status = api_error.get('status')
            if api_message:
                message = f'{api_status + ": " if api_status else ""}{api_message}'
        except (ValueError, AttributeError):
            pass
        return {
            'used': False,
            'error': message,
            'http_status': exc.response.status_code,
            'items': [],
            'model': Config.GEMINI_MODEL,
        }
    except Exception as exc:
        return {
            'used': False,
            'error': str(exc),
            'items': [],
            'model': Config.GEMINI_MODEL,
        }
