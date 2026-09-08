from utils import json_loads
from models import Standard, StandardItem

def build_knowledge_graph(db_session, standard_ids):
    nodes = []
    edges = []
    standards = db_session.query(Standard).filter(Standard.id.in_(standard_ids), Standard.is_enabled == True).all() if standard_ids else []
    for std in standards:
        std_node = {'type': 'standard', 'id': std.id, 'code': std.code, 'name': std.name, 'source_type': std.source_type, 'jurisdiction': std.jurisdiction, 'publisher': std.publisher}
        nodes.append(std_node)
        items = db_session.query(StandardItem).filter_by(standard_id=std.id, is_enabled=True).order_by(StandardItem.order_index.asc()).all()
        for item in items:
            item_node = {
                'type': 'item', 'id': item.id, 'standard_id': std.id, 'item_code': item.item_code,
                'category': item.category, 'title': item.title,
                'keywords': json_loads(item.keywords_json, default=[]), 'weight': item.weight,
            }
            nodes.append(item_node)
            edges.append({'from': std.id, 'to': item.id, 'relation': 'contains'})
    return {'nodes': nodes, 'edges': edges}

def retrieve_relevant_items(graph, extracted_text, top_k=25):
    text_lower = (extracted_text or '').lower()
    scored = []
    for node in graph.get('nodes', []):
        if node.get('type') != 'item':
            continue
        hits = sum(1 for kw in node.get('keywords', []) if kw.lower() in text_lower)
        if hits > 0:
            scored.append((hits, node))
    scored.sort(key=lambda x: (-x[0], x[1]['item_code']))
    return [x[1] for x in scored[:top_k]]
