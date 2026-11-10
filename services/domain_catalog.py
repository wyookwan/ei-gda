"""V16 domain catalog: versioned pack files synced into database tables.

Sync is idempotent and additive. Records missing from a new pack are marked inactive,
never deleted. An expert verification made in the application is never overwritten.
"""
import hashlib
import json
from pathlib import Path

from utils import json_dumps, json_loads

PACK_DIR = Path(__file__).resolve().parent.parent / 'domain_packs' / 'v16'
DOMAIN_SLUGS = ('justice', 'education', 'healthcare', 'local_government', 'general', 'ops_mhesi', 'higher_education', 'administrative_court')
LAYER_SLUGS = ('common_aidg',)
# A layer pack is a shared criteria layer, not a domain a user picks.
LAYER_STATUS = 'layer'
DETAIL_FIELDS = ('clauses', 'scope_th', 'supersedes', 'superseded_by', 'in_force', 'historical_only', 'excluded_use_cases', 'not_basis_for_th',
                 'enforcement_hold', 'hold_reason_th', 'checked_on', 'checked_by', 'url_kind')
CORE_SUITES = (
    ('TS01', 'AI Foundation & Architecture'), ('TS02', 'AI Governance & Management'),
    ('TS03', 'AI Ethics, Transparency & Trustworthiness'), ('TS04', 'AI Risk, Security & Privacy'),
    ('TS05', 'AI Data Quality & Governance'), ('TS06', 'AI Evaluation & Quality Assurance'),
    ('TS07', 'AI Life Cycle Assurance'), ('TS08', 'AI Application & Use-Case Assurance'))


def read_pack_file(slug):
    return json.loads((PACK_DIR / f'{slug}.json').read_text(encoding='utf-8'))


def disabled_domains():
    """Domains switched off by configuration (EIGDA_DISABLED_DOMAINS=administrative_court). Used for rollback."""
    import os
    return {x.strip() for x in os.getenv('EIGDA_DISABLED_DOMAINS', '').split(',') if x.strip() and x.strip() != 'general'}


def read_sila_pack(name):
    """Domain red-teaming pack (specification). Returns None when the pack has none."""
    path = PACK_DIR / 'sila' / f'{name}.json'
    return json.loads(path.read_text(encoding='utf-8')) if name and path.exists() else None


def read_registry_file():
    return json.loads((PACK_DIR / 'regulatory_registry.json').read_text(encoding='utf-8'))


def content_hash(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def validate_pack_references(pack, registry_refs):
    """Refuse a pack where a control could use a reference outside the use cases that reference allows.

    Example: a curriculum notice must never become the binding basis for automated applicant screening.
    """
    refs = {r['source_id']: r for r in registry_refs}
    all_cases = {u['id'] for u in pack.get('use_cases', [])}
    problems = []
    for control in pack.get('controls', []):
        allowed_cases = set((control.get('applies_when') or {}).get('use_cases') or all_cases or {'*'})
        for ref_id in control.get('references', []):
            excluded = set((refs.get(ref_id) or {}).get('excluded_use_cases') or [])
            if excluded and (allowed_cases & excluded or '*' in allowed_cases):
                problems.append(f"{control['id']} uses {ref_id} for excluded use case(s) {sorted(excluded & allowed_cases) or 'all'}")
    control_ids = {c['id'] for c in pack.get('controls', [])}
    shared = {c['id'] for name in pack.get('layers', []) for c in read_pack_file(name)['controls']}
    for suite in pack.get('domain_suites', []):
        for section in suite.get('sections', []):
            for cid in section.get('control_ids', []):
                if cid not in control_ids | shared:
                    problems.append(f"domain suite {suite['id']} lists unknown control {cid}")
    sila = read_sila_pack(pack.get('sila_test_pack'))
    known_tests = {t['test_id'] for t in (sila or {}).get('test_cases', [])}
    for control in pack.get('controls', []):
        for test_id in control.get('sila_tests', []):
            if test_id not in known_tests:
                problems.append(f"{control['id']} links unknown SILA test {test_id}")
    if problems:
        raise ValueError('Invalid pack ' + pack.get('slug', '?') + ': ' + '; '.join(problems))


def build_taxonomy(pack, registry_refs, general=None, layers=None):
    """Return (nodes, edges) for one domain. A node may have many parents."""
    slug = pack['slug']
    version = pack['pack_version']
    root = f'DOM.{slug}'
    nodes, edges = {}, []

    def node(node_id, node_type, row=None, owner=slug, **attrs):
        row = row or {}
        nodes.setdefault(node_id, {'node_id': node_id, 'domain_slug': owner, 'node_type': node_type,
                                   'title': row.get('title') or row.get('title_th') or node_id, 'title_th': row.get('title_th'),
                                   'attrs': attrs, 'pack_version': version})

    def edge(src, dst, relation):
        edges.append({'domain_slug': slug, 'src_id': src, 'dst_id': dst, 'relation': relation})

    node(root, 'domain', pack, summary_th=pack.get('summary_th'), key_concerns=pack.get('key_concerns'), provisional_note_th=pack.get('provisional_note_th'))
    org_ids = [o['id'] for o in pack['organization_types']]
    for org in pack['organization_types']:
        node(org['id'], 'org_type', org)
        edge(root, org['id'], 'HAS_ORG_TYPE')
    for area in pack['functional_areas']:
        node(area['id'], 'functional_area', area, provisional=area.get('provisional', False))
        for org in area.get('org_types') or org_ids:
            edge(org, area['id'], 'OPERATES')
    dims_with_parent = set()
    for case in pack['use_cases']:
        node(case['id'], 'use_case', case, floor_impact=case.get('floor_impact'), provisional=case.get('provisional', False), details_th=case.get('details_th'))
        for area in case['functional_areas']:
            edge(area, case['id'], 'HAS_USE_CASE')
        for dim in case.get('dimensions') or []:
            edge(case['id'], dim, 'CONCERNS')
            dims_with_parent.add(dim)
    for dim in pack['dimensions']:
        node(dim['id'], 'dimension', dim)
        if dim['id'] not in dims_with_parent:
            edge(root, dim['id'], 'HAS_DIMENSION')

    packs = [(pack, slug)]
    layer_packs = layers if layers is not None else [read_pack_file(name) for name in pack.get('layers', [])]
    for layer in layer_packs:
        packs.append((layer, layer['slug']))
        for dim in layer['dimensions']:
            node(dim['id'], 'dimension', dim, owner=layer['slug'])
            edge(root, dim['id'], 'INHERITS_CORE')
    if general and slug != 'general':
        packs.append((general, 'general'))
        for dim in general['dimensions']:
            node(dim['id'], 'dimension', dim, owner='general')
            edge(root, dim['id'], 'INHERITS_CORE')
    refs = {r['source_id']: r for r in registry_refs}
    referenced = set()
    for source_pack, owner in packs:
        evidence = {e['id']: e for e in source_pack['evidence_requirements']}
        rubric = source_pack['rubric']
        for control in source_pack['controls']:
            node(control['id'], 'control', control, owner=owner, objective_th=control.get('objective_th'), critical=control.get('critical', False),
                 critical_when=control.get('critical_when'), risk=control.get('risk'), provisional=control.get('provisional', False), applies_when=control.get('applies_when'))
            for dim in control['dimensions']:
                edge(dim, control['id'], 'GOVERNED_BY')
            for suite in control['suites']:
                edge(control['id'], f'SUITE.{suite}', 'IN_SUITE')
            for ref in control['references']:
                edge(control['id'], f'REG.{ref}', 'DERIVED_FROM')
                referenced.add(ref)
            for req in control['evidence']:
                row = evidence.get(req)
                if row is None and general:
                    row = next((e for e in general['evidence_requirements'] if e['id'] == req), None)
                if row is None:
                    row = next((e for layer in layer_packs for e in layer['evidence_requirements'] if e['id'] == req), None)
                node(req, 'evidence', row, owner=owner, why_th=(row or {}).get('why_th'))
                edge(control['id'], req, 'REQUIRES_EVIDENCE')
            node(rubric['id'], 'rubric', {'title': rubric['id'], 'title_th': 'เกณฑ์ประเมิน ' + rubric['id']}, owner=owner, version=rubric.get('version'), levels=rubric.get('levels'), gate_min_level=rubric.get('gate_min_level'))
            if owner == slug:
                edge(control['id'], rubric['id'], 'ASSESSED_USING')
            elif slug != 'general':
                edge(control['id'], pack['rubric']['id'], 'ASSESSED_USING')
    if slug != 'general':
        node(pack['rubric']['id'], 'rubric', {'title': pack['rubric']['id'], 'title_th': 'เกณฑ์ประเมิน ' + pack['rubric']['id']}, version=pack['rubric'].get('version'), levels=pack['rubric'].get('levels'), gate_min_level=pack['rubric'].get('gate_min_level'))
        nodes.pop(general['rubric']['id'], None)
        for layer in layer_packs:
            nodes.pop(layer['rubric']['id'], None)
    # Domain-specific suite overlay (e.g. JUD-01..08) and the red-teaming cases that validate controls.
    for suite in pack.get('domain_suites', []):
        node(f'DSUITE.{suite["id"]}', 'domain_suite', suite, criticality=suite.get('criticality'), status=suite.get('status'), objective_th=suite.get('objective_th'))
        edge(root, f'DSUITE.{suite["id"]}', 'HAS_DOMAIN_SUITE')
        for section in suite.get('sections', []):
            for cid in section.get('control_ids', []):
                if cid in nodes:
                    edge(f'DSUITE.{suite["id"]}', cid, 'GROUPS')
    sila = read_sila_pack(pack.get('sila_test_pack'))
    if sila:
        tests = {t['test_id']: t for t in sila['test_cases']}
        for control in pack.get('controls', []):
            for test_id in control.get('sila_tests', []):
                t = tests[test_id]
                node(f'SILA.{test_id}', 'test_case', {'title': test_id, 'title_th': t['scenario_th']}, category=t['category'], risk_severity=t['risk_severity'],
                     expert_verification=t['benchmark']['expert_verification'], status=t['status'])
                edge(control['id'], f'SILA.{test_id}', 'VALIDATED_BY')
    for code, name in CORE_SUITES:
        node(f'SUITE.{code}', 'test_suite', {'title': f'{code} {name}'}, owner='shared', code=code, focus_th=(pack.get('suite_focus') or {}).get(code))
    for ref_id, ref in refs.items():
        if slug in ref.get('domains', []) or ref_id in referenced:
            node(f'REG.{ref_id}', 'regulation', ref, owner='shared', normative_class=ref.get('normative_class'), verification_status=ref.get('verification_status'),
                 official_url=ref.get('official_url'), condition_th=ref.get('condition_th'), source_id=ref_id)
            if ref_id not in referenced:
                edge(root, f'REG.{ref_id}', 'DOMAIN_REFERENCE')
    return list(nodes.values()), edges


def sync_catalog(session):
    """Load all pack files into the database. Safe to run repeatedly."""
    from models import (DomainControl, DomainPackVersion, DomainProfile, DomainRubric, EvidenceRequirement,
                        RegulatoryReference, Standard, TaxonomyEdge, TaxonomyNode, Template)
    stats = {'domains': 0, 'nodes': 0, 'edges': 0, 'controls': 0, 'references': 0, 'suites_mapped': 0}
    registry = read_registry_file()
    existing_refs = {r.source_id: r for r in session.query(RegulatoryReference).all()}
    seen_refs = set()
    for ref in registry['references']:
        row = existing_refs.get(ref['source_id'])
        if row is None:
            row = RegulatoryReference(source_id=ref['source_id'])
            session.add(row)
        for field in ('title', 'title_th', 'issuing_authority', 'jurisdiction', 'document_type', 'normative_class', 'publication_date',
                      'effective_date', 'version', 'official_url', 'condition_th', 'standard_code'):
            setattr(row, field, ref.get(field))
        row.applicability_json = json_dumps(ref.get('applies_when') or {})
        row.domains_json = json_dumps(ref.get('domains') or [])
        row.registry_version = registry['registry_version']
        row.details_json = json_dumps({k: ref[k] for k in DETAIL_FIELDS if k in ref})
        row.is_active = True
        if row.verification_status != 'expert_verified':
            row.verification_status = ref.get('verification_status', 'pending_verification')
            row.verification_note = ref.get('verification_note')
        seen_refs.add(ref['source_id'])
        stats['references'] += 1
    for source_id, row in existing_refs.items():
        if source_id not in seen_refs:
            row.is_active = False
    session.flush()
    # Live statuses feed the taxonomy so an expert verification is visible there too.
    live = {r.source_id: r.verification_status for r in session.query(RegulatoryReference).all()}
    registry_refs = [{**r, 'verification_status': live.get(r['source_id'], r.get('verification_status'))} for r in registry['references']]

    general = read_pack_file('general')
    node_ids, edge_keys = set(), set()
    existing_nodes = {n.node_id: n for n in session.query(TaxonomyNode).all()}
    existing_edges = {(e.domain_slug, e.src_id, e.dst_id, e.relation): e for e in session.query(TaxonomyEdge).all()}
    existing_controls = {c.control_id: c for c in session.query(DomainControl).all()}
    existing_reqs = {r.requirement_id: r for r in session.query(EvidenceRequirement).all()}
    existing_rubrics = {r.rubric_id: r for r in session.query(DomainRubric).all()}
    disabled = disabled_domains()
    for slug in disabled:
        profile = session.get(DomainProfile, slug)
        if profile is not None:
            profile.is_active = False  # rollback without deleting: assessments and findings stay readable by ID
    for slug in DOMAIN_SLUGS + LAYER_SLUGS:
        if slug in disabled:
            continue
        pack = read_pack_file(slug)
        validate_pack_references(pack, registry['references'])
        digest = content_hash(pack)
        profile = session.get(DomainProfile, slug) or DomainProfile(slug=slug)
        for field in ('title', 'title_th', 'icon', 'accent', 'pack_version'):
            setattr(profile, field, pack.get(field))
        profile.display_order = pack.get('display_order', 99)
        profile.status = LAYER_STATUS if pack.get('kind') == 'layer' else pack.get('status', 'pilot_draft')
        profile.content_hash = digest
        profile.payload_json = json_dumps(pack)
        profile.is_active = True
        session.add(profile)
        if not session.query(DomainPackVersion).filter_by(slug=slug, content_hash=digest).first():
            session.add(DomainPackVersion(slug=slug, pack_version=pack['pack_version'], content_hash=digest, payload_json=json_dumps(pack)))
        nodes, edges = build_taxonomy(pack, registry_refs, general)
        for item in nodes:
            row = existing_nodes.get(item['node_id'])
            if row is None:
                row = TaxonomyNode(node_id=item['node_id'])
                existing_nodes[item['node_id']] = row
                session.add(row)
            # Shared rows are written once per domain; the first owner-specific attrs win only for suites.
            row.domain_slug, row.node_type, row.title, row.title_th = item['domain_slug'], item['node_type'], item['title'][:300], (item['title_th'] or None)
            row.attrs_json, row.pack_version, row.is_active = json_dumps(item['attrs']), item['pack_version'], True
            node_ids.add(item['node_id'])
        for item in edges:
            key = (item['domain_slug'], item['src_id'], item['dst_id'], item['relation'])
            if key in edge_keys:
                continue
            row = existing_edges.get(key)
            if row is None:
                row = TaxonomyEdge(**item)
                existing_edges[key] = row
                session.add(row)
            row.is_active = True
            edge_keys.add(key)
        for control in pack['controls']:
            row = existing_controls.get(control['id'])
            if row is None:
                row = DomainControl(control_id=control['id'])
                existing_controls[control['id']] = row
                session.add(row)
            row.domain_slug, row.title, row.title_th = slug, control['title'], control.get('title_th')
            row.critical, row.risk_level, row.pack_version, row.is_active = control.get('critical', False), control.get('risk'), pack['pack_version'], True
            stats['controls'] += 1
        for req in pack['evidence_requirements']:
            row = existing_reqs.get(req['id'])
            if row is None:
                row = EvidenceRequirement(requirement_id=req['id'])
                existing_reqs[req['id']] = row
                session.add(row)
            row.domain_slug, row.title, row.title_th, row.is_active = slug, req['title'], req.get('title_th'), True
        rubric = pack['rubric']
        row = existing_rubrics.get(rubric['id'])
        if row is None:
            row = DomainRubric(rubric_id=rubric['id'])
            existing_rubrics[rubric['id']] = row
            session.add(row)
        row.domain_slug, row.version, row.definition_json = slug, rubric.get('version', '1.0'), json_dumps(rubric)
        stats['domains'] += 0 if slug in LAYER_SLUGS else 1
    for node_id, row in existing_nodes.items():
        if node_id not in node_ids:
            row.is_active = False
    for key, row in existing_edges.items():
        if key not in edge_keys:
            row.is_active = False
    pack_controls = {c['id'] for s in DOMAIN_SLUGS + LAYER_SLUGS if s not in disabled for c in read_pack_file(s)['controls']}
    for control_id, row in existing_controls.items():
        if control_id not in pack_controls:
            row.is_active = False
    stats['nodes'], stats['edges'] = len(node_ids), len(edge_keys)
    stats['suites_mapped'] = map_core_suites(session)
    # Explicit model-processing allow rules (default deny). Existing rows, including disabled ones, are left alone.
    from services.model_gate import seed_default_rules
    stats['model_rules_added'] = seed_default_rules(session)
    session.flush()
    return stats


def map_core_suites(session):
    """Assign stable TS codes by existing names. Display order and IDs stay as they are."""
    from models import Template
    mapped = 0
    for code, name in CORE_SUITES:
        suite = session.query(Template).filter_by(name=name).first()
        if suite is not None:
            if suite.suite_code != code:
                suite.suite_code = code
            mapped += 1
    return mapped


def get_pack(session, slug, include_inactive=False):
    """Active pack by slug. include_inactive=True lets existing work open after its domain was switched off."""
    from models import DomainProfile
    profile = session.get(DomainProfile, slug)
    return json_loads(profile.payload_json, default=None) if profile and (profile.is_active or include_inactive) else None


def list_profiles(session, include_layers=False):
    from models import DomainProfile
    query = session.query(DomainProfile).filter_by(is_active=True)
    if not include_layers:
        query = query.filter(DomainProfile.status != LAYER_STATUS)
    return query.order_by(DomainProfile.display_order, DomainProfile.slug).all()


def layer_packs(session, pack):
    return [p for p in (get_pack(session, name) for name in (pack or {}).get('layers', [])) if p]


def taxonomy_payload(session, slug):
    """Nodes, edges and a control filter index for the explorer API."""
    from models import TaxonomyEdge, TaxonomyNode
    edges = session.query(TaxonomyEdge).filter_by(domain_slug=slug, is_active=True).all()
    ids = {f'DOM.{slug}'} | {e.src_id for e in edges} | {e.dst_id for e in edges}
    rows = session.query(TaxonomyNode).filter(TaxonomyNode.node_id.in_(ids), TaxonomyNode.is_active == True).all()
    pack = get_pack(session, slug) or {}
    nodes = {r.node_id: {'id': r.node_id, 'type': r.node_type, 'title': r.title, 'title_th': r.title_th, 'domain': r.domain_slug,
                         'attrs': json_loads(r.attrs_json, default={})} for r in rows}
    # Suite focus text is per domain, so it is taken from this domain's pack rather than the shared row.
    for code, focus in (pack.get('suite_focus') or {}).items():
        if f'SUITE.{code}' in nodes:
            nodes[f'SUITE.{code}']['attrs']['focus_th'] = focus
    edge_rows = [{'src': e.src_id, 'dst': e.dst_id, 'rel': e.relation} for e in edges if e.src_id in nodes and e.dst_id in nodes]
    return {'slug': slug, 'pack_version': pack.get('pack_version'), 'root': f'DOM.{slug}', 'nodes': nodes, 'edges': edge_rows,
            'control_index': _control_index(pack, session), 'provisional_note_th': pack.get('provisional_note_th')}


def _control_index(pack, session):
    """Map each control to its filter facets so the browser can filter without guessing."""
    from models import RegulatoryReference
    statuses = {r.source_id: r.verification_status for r in session.query(RegulatoryReference).all()}
    general = get_pack(session, 'general') if pack.get('slug') != 'general' else None
    org_ids = [o['id'] for o in pack.get('organization_types', [])]
    area_ids = [a['id'] for a in pack.get('functional_areas', [])]
    case_ids = [c['id'] for c in pack.get('use_cases', [])]
    index = {}
    for source in [pack] + layer_packs(session, pack) + ([general] if general else []):
        for control in (source or {}).get('controls', []):
            rule = control.get('applies_when') or {}
            cases = rule.get('use_cases') or case_ids
            areas = rule.get('functional_areas') or sorted({a for c in pack.get('use_cases', []) if c['id'] in cases for a in c['functional_areas']} or set(area_ids))
            index[control['id']] = {'org_types': rule.get('org_types') or org_ids, 'functional_areas': areas, 'use_cases': cases,
                                    'suites': control['suites'], 'dimensions': control['dimensions'], 'risk': control.get('risk'),
                                    'reg_statuses': sorted({statuses.get(r, 'pending_verification') for r in control['references']})}
    return index
