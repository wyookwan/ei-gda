import re


def maturity_from_avg05(avg):
    if avg <= 1.0: return 'Initial'
    if avg <= 2.5: return 'Basic'
    if avg <= 3.5: return 'Operational'
    if avg <= 4.5: return 'Managed'
    return 'Optimized'


def maturity_label_for_item(score):
    score = int(round(max(0, min(5, score))))
    return {0:'Not Implemented',1:'Initial',2:'Defined',3:'Implemented',4:'Managed',5:'Optimized'}[score]


def keyword_rule_score(text_lower, keywords):
    """Deterministic rule score directly on the 0-5 maturity scale."""
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    total = max(1, len(keywords))
    ratio = hits / total
    if hits == 0: return 0
    if ratio < 0.25: return 1
    if ratio < 0.50: return 2
    if ratio < 0.75: return 3
    if ratio < 1.0: return 4
    return 5


def _snippet(text, terms, max_chars=420):
    """Return a readable evidence window around the first matched term."""
    clean = re.sub(r'\s+', ' ', text or '').strip()
    if not clean:
        return ''
    low = clean.lower()
    positions = [low.find(t.lower()) for t in terms if t and low.find(t.lower()) >= 0]
    pos = min(positions) if positions else 0
    start = max(0, pos - max_chars // 3)
    end = min(len(clean), start + max_chars)
    out = clean[start:end]
    if start > 0: out = '…' + out
    if end < len(clean): out += '…'
    return out


def build_evidence_map(document_files, graph, json_loader, max_evidence_per_item=4):
    """Locate traceable evidence by source file and page for every compliance item.

    The score is intentionally transparent: keyword hits are primary and title-token
    overlap provides a small fallback signal. This evidence locator does not assign
    maturity; it only provides provenance for the scoring engine and UI.
    """
    page_records = []
    for doc_file in document_files:
        pages = json_loader(doc_file.pages_json, default=[])
        if not pages and doc_file.extracted_text:
            pages = [{'page': 1, 'text': doc_file.extracted_text}]
        for p in pages:
            page_records.append({
                'file_id': doc_file.id,
                'filename': doc_file.original_filename,
                'page': int(p.get('page') or 1),
                'text': p.get('text') or ''
            })

    evidence_map = {}
    for node in graph.get('nodes', []):
        if node.get('type') != 'item':
            continue
        keywords = [str(x).strip() for x in node.get('keywords', []) if str(x).strip()]
        title_tokens = [x for x in re.findall(r'[A-Za-z0-9ก-๙]{4,}', node.get('title','').lower()) if len(x) >= 4][:12]
        candidates = []
        for page in page_records:
            low = page['text'].lower()
            matched = [kw for kw in keywords if kw.lower() in low]
            title_hits = [t for t in title_tokens if t in low]
            if not matched and not title_hits:
                continue
            relevance = len(matched) * 2.0 + min(3, len(title_hits)) * 0.35
            terms = matched or title_hits
            candidates.append({
                'file_id': page['file_id'],
                'filename': page['filename'],
                'page': page['page'],
                'snippet': _snippet(page['text'], terms),
                'matched_keywords': matched[:8],
                'relevance': round(relevance, 2)
            })
        candidates.sort(key=lambda x: (-x['relevance'], x['filename'], x['page']))
        evidence_map[node['item_code']] = candidates[:max_evidence_per_item]
    return evidence_map


def run_hybrid_compliance(extracted_text, graph, model_result=None, provider='rule+kg', evidence_map=None):
    text_lower = (extracted_text or '').lower()
    evidence_map = evidence_map or {}
    item_nodes = [n for n in graph.get('nodes', []) if n.get('type') == 'item']
    model_map = {}
    if model_result and isinstance(model_result, dict):
        for item in model_result.get('items', []):
            model_map[item.get('item_code')] = item

    per_standard_map, all_items = {}, []
    category_map = {}
    standard_info = {n['id']: n for n in graph.get('nodes', []) if n.get('type') == 'standard'}
    for node in item_nodes:
        rule_score = keyword_rule_score(text_lower, node.get('keywords', []))
        item_evidence = evidence_map.get(node['item_code'], [])
        evidence_bonus = 0.5 if item_evidence else 0
        model = model_map.get(node['item_code'])
        raw_model_score = model.get('score') if model else None
        try:
            model_score = float(raw_model_score) if raw_model_score is not None else None
        except (TypeError, ValueError):
            model_score = None

        if model_score is None:
            final_score = max(0, min(5, round(rule_score + evidence_bonus, 2)))
            reason = f'{provider} deterministic fallback'
            gap = '' if final_score >= 3 else f"ยังครอบคลุมหัวข้อ {node['item_code']} ไม่เพียงพอ"
            recommendation = '' if final_score >= 3 else f"ควรเพิ่มรายละเอียด หลักฐาน ผู้รับผิดชอบ และการนำไปใช้งานจริงสำหรับ '{node['title']}'"
        else:
            model_score = max(0, min(5, model_score))
            final_score = max(0, min(5, round(rule_score * 0.35 + min(5, rule_score + evidence_bonus) * 0.15 + model_score * 0.50, 2)))
            reason = model.get('reason', provider)
            gap = model.get('gap', '')
            recommendation = model.get('recommendation', '')

        std_id = node['standard_id']
        weight = node.get('weight', 1.0)
        category = node.get('category') or 'Other'
        std_info = standard_info.get(std_id, {})
        item = {
            'item_id': node['id'], 'item_code': node['item_code'], 'title': node['title'],
            'standard': std_info.get('code', f'STD-{std_id}'), 'standard_name': std_info.get('name', ''),
            'category': category, 'score': final_score, 'score_percent': round(final_score / 5 * 100, 2),
            'maturity': maturity_label_for_item(final_score), 'weight': weight, 'reason': reason,
            'gap': gap, 'recommendation': recommendation, 'evidence': item_evidence
        }
        per_standard_map.setdefault(std_id, {'items': [], 'weighted_sum': 0.0, 'total_weight': 0.0})
        per_standard_map[std_id]['items'].append(item)
        per_standard_map[std_id]['weighted_sum'] += final_score * weight
        per_standard_map[std_id]['total_weight'] += weight
        all_items.append(item)
        cat = category_map.setdefault(category, {'sum':0.0,'count':0})
        cat['sum'] += final_score; cat['count'] += 1

    per_standard = []
    for std_id, bundle in per_standard_map.items():
        avg05 = round(bundle['weighted_sum'] / bundle['total_weight'], 2) if bundle['total_weight'] else 0.0
        info = standard_info.get(std_id, {})
        per_standard.append({
            'standard_id': std_id, 'code': info.get('code', f'STD-{std_id}'), 'name': info.get('name', ''),
            'avg_score_0_to_5': avg05, 'percent': round(avg05 / 5 * 100, 2), 'items': bundle['items']
        })
    per_standard.sort(key=lambda x: x['code'])
    category_summary = [
        {'category': k, 'avg_score_0_to_5': round(v['sum']/v['count'],2), 'percent': round((v['sum']/v['count'])/5*100,2)}
        for k,v in category_map.items() if v['count']
    ]
    category_summary.sort(key=lambda x: x['category'])
    maturity_distribution = {str(i): 0 for i in range(6)}
    for item in all_items:
        maturity_distribution[str(int(round(item['score'])))] += 1
    overall_avg05 = round(sum(x['avg_score_0_to_5'] for x in per_standard) / len(per_standard), 2) if per_standard else 0.0
    return {
        'overall_avg_0_to_5': overall_avg05,
        'overall_percent': round(overall_avg05 / 5 * 100, 2),
        'maturity_level': maturity_from_avg05(overall_avg05),
        'per_standard': per_standard,
        'category_summary': category_summary,
        'maturity_distribution': maturity_distribution,
        'all_items': all_items
    }
