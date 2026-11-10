"""V16 domain-aware knowledge graph. Extends, and does not replace, services/kg_service.py.

Nodes are namespaced. Every edge carries provenance, so a finding can be traced to a
regulation and to source evidence. Nothing is inferred beyond stored records.
"""
from models import DocumentFile, DomainFinding, EvidenceMapping
from utils import json_loads

SUPPORTS, CONTRADICTS = 'SUPPORTED_BY', 'CONTRADICTED_BY'


def build_assessment_graph(assessment, config):
    nodes, edges = {}, []

    def node(node_id, node_type, label, provenance, **attrs):
        nodes.setdefault(node_id, {'id': node_id, 'type': node_type, 'label': label, 'provenance': provenance, **attrs})

    def edge(src, dst, relation, provenance):
        edges.append({'from': src, 'to': dst, 'relation': relation, 'provenance': provenance})

    pack = f"domain-pack:{config.get('domain')}@{config.get('pack_version')}"
    profile = config.get('profile') or {}
    labels = config.get('labels') or {}
    domain_id = f"domain:{config.get('domain')}"
    org_id = f'org:assessment-{assessment.id}'
    node(domain_id, 'Domain', config.get('domain_title_th') or config.get('domain'), pack)
    node(org_id, 'Organization', assessment.organization_name or '-', 'assessment:user-input')
    edge(org_id, domain_id, 'IN_DOMAIN', 'assessment:user-input')
    for key, prefix, node_type in (('org_type', 'orgtype', 'OrganizationType'), ('functional_area', 'function', 'FunctionalArea'), ('use_case', 'usecase', 'AIUseCase')):
        value = profile.get(key)
        if value:
            node(f'{prefix}:{value}', node_type, labels.get(value, value), pack)
            edge(org_id, f'{prefix}:{value}', 'OPERATES', 'assessment:user-input')

    findings = {f.control_id: f for f in DomainFinding.query.filter_by(assessment_id=assessment.id).all()}
    mappings = {}
    for row in EvidenceMapping.query.filter_by(assessment_id=assessment.id).all():
        mappings.setdefault(row.requirement_id, []).append(row)
    refs = {r['source_id']: r for r in config.get('references', [])}
    for control in config.get('controls', []):
        if control.get('final_status') == 'not_applicable':
            continue
        control_id = f"control:{control['id']}"
        node(control_id, 'GovernanceControl', control.get('title_th') or control['title'], pack, critical=control.get('is_critical', False))
        edge(control_id, domain_id, 'APPLIES_TO', pack)
        for ref in control.get('references', []):
            info = refs.get(ref) or {}
            reg_id = f'regulation:{ref}'
            node(reg_id, 'Regulation', info.get('title_th') or info.get('title') or ref, 'registry', verification_status=info.get('verification_status'), normative_class=info.get('normative_class'))
            req_id = f"requirement:{control['id']}:{ref}"
            node(req_id, 'Requirement', control.get('objective_th') or control['title'], pack + ' (ข้อกำหนดร่างของ pack ไม่ใช่ถ้อยคำของกฎหมาย)')
            edge(control_id, req_id, 'DERIVED_FROM', pack)
            edge(req_id, reg_id, 'DERIVED_FROM', 'registry')
        finding = findings.get(control['id'])
        finding_id = f"finding:{assessment.id}:{control['id']}"
        if finding is not None:
            node(finding_id, 'AssessmentFinding', f"{control['id']}: {finding.state}", f'{finding.method or "-"}', state=finding.state, level=finding.level)
            edge(finding_id, control_id, 'ASSESSED_USING', config['rubric'].get('id', 'rubric'))
        for requirement in control.get('evidence', []):
            rows = mappings.get(requirement, [])
            title = (config.get('evidence_requirements') or {}).get(requirement, {}).get('title_th', requirement)
            req_node = f'evidence-req:{requirement}'
            node(req_node, 'Requirement', title, pack)
            edge(control_id, req_node, 'REQUIRES_EVIDENCE', pack)
            if finding is None:
                continue
            relation = CONTRADICTS if finding.human_stance == 'contradicted' else SUPPORTS
            for row in rows:
                evidence_id = f'evidence:file-{row.document_file_id}:p{row.page or 0}'
                filename = row.document_file.original_filename if row.document_file else '-'
                node(evidence_id, 'Evidence', f'{filename} หน้า {row.page or "-"}', f'{row.source}-mapping', file_id=row.document_file_id, page=row.page)
                edge(finding_id, evidence_id, relation, f'{row.source}-mapping')
    return {'schema': 'eigda.domain-kg/1', 'assessment_id': assessment.id, 'snapshot_hash': assessment.snapshot_hash,
            'nodes': list(nodes.values()), 'edges': edges}


def finding_trace(graph, control_id, assessment_id):
    """Return both trace chains for a finding: to the regulation and to the evidence."""
    finding_id = f'finding:{assessment_id}:{control_id}'
    by_id = {n['id']: n for n in graph['nodes']}
    outgoing = {}
    for edge in graph['edges']:
        outgoing.setdefault(edge['from'], []).append(edge)
    regulations, evidence = [], []
    control_key = f'control:{control_id}'
    for edge in outgoing.get(control_key, []):
        if edge['relation'] == 'DERIVED_FROM':
            for next_edge in outgoing.get(edge['to'], []):
                if next_edge['relation'] == 'DERIVED_FROM':
                    regulations.append(by_id[next_edge['to']])
    for edge in outgoing.get(finding_id, []):
        if edge['relation'] in (SUPPORTS, CONTRADICTS):
            evidence.append({**by_id[edge['to']], 'relation': edge['relation']})
    return {'regulations': regulations, 'evidence': evidence}
