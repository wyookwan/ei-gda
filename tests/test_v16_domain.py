"""V16 domain-adaptive behaviour. Runs on in-memory SQLite with synthetic PDFs only."""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import fitz

import test_international_catalog as fixtures
from config import Config, assert_safe_runtime
from extensions import db
from models import (ApplicabilityDecision, AuditLog, CommitteeAssignment, DocumentCheck, DocumentFile, DomainAssessment, DomainFinding, EvidenceMapping,
                    RegulatoryReference, TaxonomyEdge, TaxonomyNode, Template, User)
from services.applicability import build_context, derive_risk, resolve_control, resolve_critical, resolve_reference
from services.domain_catalog import CORE_SUITES, DOMAIN_SLUGS, build_taxonomy, get_pack, read_pack_file, read_registry_file, sync_catalog, taxonomy_payload
from services.domain_orchestrator import build_configuration, current_config
from services.domain_rubric import coverage_cap, score_finding, summarize
from utils import json_dumps, json_loads

PROFILE_TRIAGE = {'org_type': 'HLT.ORG.EMS', 'functional_area': 'EMS.STAGE.3', 'use_case': 'EMS.UC1', 'data_categories': ['HLT.DATA.HEALTH'], 'decision_impact': 'assistive', 'flags': {'is_public_agency': True}}


def make_pdf(*pages):
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((50, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return io.BytesIO(data)


class Base(unittest.TestCase):
    def setUp(self):
        fixtures.CatalogTests.setUp(self)
        self.uploads = tempfile.mkdtemp()
        self.app.config['UPLOAD_FOLDER'] = self.uploads
        for index, (code, name) in enumerate(CORE_SUITES, 1):
            if not Template.query.filter_by(name=name).first():
                db.session.add(Template(name=name, description='', prompt_structure='', sections_json='[]', display_order=100 + index))
        self.owner = User(full_name='Owner', email='owner@example.invalid', password_hash='x', role='user')
        self.other = User(full_name='Other', email='other@example.invalid', password_hash='x', role='user')
        self.admin = User(full_name='Admin', email='admin@example.invalid', password_hash='x', role='admin')
        self.committee = User(full_name='Committee', email='committee@example.invalid', password_hash='x', role='committee')
        db.session.add_all([self.owner, self.other, self.admin, self.committee])
        db.session.commit()
        self.stats = sync_catalog(db.session)
        db.session.commit()

    def tearDown(self):
        fixtures.CatalogTests.tearDown(self)
        shutil.rmtree(self.uploads, ignore_errors=True)

    def client_for(self, user):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=user.id, role=user.role, email=user.email, full_name=user.full_name)
        return client

    def assessment(self, slug='healthcare', profile=None, classification='confidential', frozen=True):
        row = DomainAssessment(user_id=self.owner.id, domain_slug=slug, name='A', organization_name='Org', profile_json=json_dumps(profile if profile is not None else PROFILE_TRIAGE), status='draft', current_step=4, data_classification=classification)
        db.session.add(row)
        db.session.commit()
        if frozen:
            self.assertEqual(self.client_for(self.owner).post(f'/assessments/{row.id}/freeze').status_code, 302)
            db.session.refresh(row)
        return row

    def upload(self, client, assessment, *pages, name='evidence.pdf'):
        return client.post(f'/assessments/{assessment.id}/evidence', data={'pdf_files': (make_pdf(*pages), name)}, content_type='multipart/form-data')


class TaxonomyTests(Base):
    def test_all_domains_load_and_ids_are_stable(self):
        # Pilot: ops_mhesi and higher_education joined the original five domains (common_aidg is a layer, not a domain).
        self.assertEqual(self.stats['domains'], len(DOMAIN_SLUGS))
        self.assertEqual(len(DOMAIN_SLUGS), 8)  # + administrative_court
        for slug in DOMAIN_SLUGS:
            pack = get_pack(db.session, slug)
            self.assertEqual(pack['slug'], slug)
            ids = [c['id'] for c in pack['controls']]
            self.assertEqual(len(ids), len(set(ids)))
        first = {n.node_id for n in TaxonomyNode.query.all()}
        sync_catalog(db.session)
        db.session.commit()
        self.assertEqual(first, {n.node_id for n in TaxonomyNode.query.all()})

    def test_relationships_are_valid_and_nothing_is_orphaned(self):
        registry = read_registry_file()['references']
        general = read_pack_file('general')
        for slug in DOMAIN_SLUGS:
            nodes, edges = build_taxonomy(read_pack_file(slug), registry, general)
            ids = {n['node_id'] for n in nodes}
            targets = {e['dst_id'] for e in edges}
            for edge in edges:
                self.assertIn(edge['src_id'], ids, edge)
                self.assertIn(edge['dst_id'], ids, edge)
            orphans = {n['node_id'] for n in nodes if n['node_type'] != 'domain' and n['node_id'] not in targets}
            self.assertEqual(orphans, set(), slug)

    def test_many_to_many_control_relationships(self):
        edges = TaxonomyEdge.query.filter_by(domain_slug='justice', src_id='JUS-01').all()
        self.assertGreaterEqual(len([e for e in edges if e.relation == 'IN_SUITE']), 2)
        self.assertGreaterEqual(len([e for e in edges if e.relation == 'DERIVED_FROM']), 2)

    def test_ems_taxonomy_is_complete_and_labelled_provisional(self):
        pack = read_pack_file('healthcare')
        stages = [a for a in pack['functional_areas'] if a['id'].startswith('EMS.STAGE')]
        self.assertEqual(len(stages), 8)
        self.assertTrue(all(a['provisional'] for a in stages))
        self.assertEqual({u['id'] for u in pack['use_cases'] if u['id'].startswith('EMS.UC')}, {'EMS.UC1', 'EMS.UC2', 'EMS.UC3'})
        self.assertEqual({c['id'] for c in pack['controls'] if c['id'].startswith('EMS-')}, {f'EMS-0{i}' for i in range(1, 9)})
        self.assertIn('provisional_note_th', pack)

    def test_api_and_filter_index(self):
        client = self.client_for(self.owner)
        data = client.get('/api/taxonomy/healthcare').get_json()
        self.assertIn('EMS-01', data['control_index'])
        self.assertEqual(data['control_index']['EMS-01']['use_cases'], ['EMS.UC1'])
        self.assertIn('TS04', data['control_index']['EMS-02']['suites'])
        self.assertEqual(client.get('/api/taxonomy/nope').status_code, 404)
        results = client.get('/search?q=EMS-01').get_data(as_text=True)
        self.assertIn('EMS-01', results)


class ApplicabilityTests(Base):
    def config(self, slug='healthcare', profile=None, decisions=None):
        return build_configuration(slug, profile or PROFILE_TRIAGE, decisions)

    def by_id(self, config):
        return {c['id']: c for c in config['controls']}

    def test_use_case_changes_controls_with_reasons(self):
        triage = self.by_id(self.config())
        forecast = self.by_id(self.config(profile={**PROFILE_TRIAGE, 'use_case': 'EMS.UC3', 'functional_area': 'EMS.STAGE.4', 'data_categories': ['HLT.DATA.OPS']}))
        self.assertEqual(triage['EMS-01']['final_status'], 'applicable')
        self.assertEqual(forecast['EMS-01']['final_status'], 'not_applicable')
        self.assertIn('AI Use Case', forecast['EMS-01']['reason_th'])
        self.assertEqual(forecast['EMS-08']['final_status'], 'applicable')
        self.assertEqual(triage['EMS-08']['final_status'], 'not_applicable')

    def test_unknown_answers_are_conditional_not_assumed(self):
        controls = self.by_id(self.config())
        self.assertEqual(controls['HLT-05']['final_status'], 'conditional')
        controls = self.by_id(self.config(profile={**PROFILE_TRIAGE, 'flags': {'medical_device_scope': False}}))
        self.assertEqual(controls['HLT-05']['final_status'], 'not_applicable')
        references = {r['source_id']: r for r in self.config(profile={**PROFILE_TRIAGE, 'flags': {'medical_device_scope': False}})['references']}
        self.assertEqual(references['ISO-14971']['status'], 'not_applicable')

    def test_unverified_rules_are_not_binding(self):
        references = {r['source_id']: r for r in self.config()['references']}
        self.assertEqual(references['TH-EMS-2551']['status'], 'pending_verification')
        self.assertFalse(references['TH-EMS-2551']['is_binding'])
        self.assertFalse(any(r['is_binding'] for r in references.values()))
        self.assertFalse(references['ISO-42001']['is_binding'])

    def test_voluntary_standard_never_binding_even_when_verified(self):
        result = resolve_reference({'normative_class': 'voluntary_standard', 'verification_status': 'expert_verified'}, build_context({}, []))
        self.assertEqual(result['status'], 'applicable')
        self.assertFalse(result['is_binding'])

    def test_non_applicable_rule_is_excluded(self):
        references = {r['source_id']: r for r in self.config()['references']}
        self.assertEqual(references['TH-SANATORIUM-2541']['status'], 'not_applicable')

    def test_risk_floor_cannot_be_lowered(self):
        use_case = next(u for u in read_pack_file('healthcare')['use_cases'] if u['id'] == 'EMS.UC1')
        self.assertEqual(derive_risk({'decision_impact': 'information'}, use_case, 'public')['level'], 'critical')

    def test_critical_depends_on_context(self):
        control = next(c for c in read_pack_file('justice')['controls'] if c['id'] == 'JUS-02')
        self.assertTrue(resolve_critical(control, build_context({'use_case': 'JUS.UC.RESEARCH'}, [])))
        self.assertFalse(resolve_critical(control, build_context({'use_case': 'JUS.UC.CLASSIFY'}, [])))

    def test_override_requires_reviewer_and_reason_and_is_logged(self):
        assessment = self.assessment(frozen=False)
        url = f'/assessments/{assessment.id}/controls/EMS-08/override'
        self.assertEqual(self.client_for(self.owner).post(url, data={'status': 'applicable', 'reason': 'owner attempt'}).status_code, 403)
        admin = self.client_for(self.admin)
        admin.post(url, data={'status': 'applicable', 'reason': 'x'})
        self.assertIsNone(ApplicabilityDecision.query.filter_by(assessment_id=assessment.id).first())
        admin.post(url, data={'status': 'applicable', 'reason': 'เหตุผลการปรับขอบเขต'})
        self.assertEqual(ApplicabilityDecision.query.filter_by(target_id='EMS-08').first().override_status, 'applicable')
        self.assertEqual(AuditLog.query.filter_by(action='applicability_control_override').count(), 1)
        self.assertEqual(self.by_id(current_config(assessment))['EMS-08']['final_status'], 'applicable')

    def test_binding_confirmation_requires_expert_verified_source(self):
        assessment = self.assessment(frozen=False)
        admin = self.client_for(self.admin)
        url = f'/assessments/{assessment.id}/regulations/TH-EMS-2551/decision'
        admin.post(url, data={'action': 'confirm', 'reason': 'ยืนยันขอบเขตของงาน'})
        self.assertIsNone(ApplicabilityDecision.query.filter_by(target_id='TH-EMS-2551').first())
        self.assertEqual(self.client_for(self.owner).post('/regulations/TH-EMS-2551/verify', data={'action': 'verify', 'note': 'ตรวจกับตัวบทแล้ว'}).status_code, 302)
        self.assertEqual(db.session.get(RegulatoryReference, 'TH-EMS-2551').verification_status, 'pending_verification')
        admin.post('/regulations/TH-EMS-2551/verify', data={'action': 'verify', 'note': 'ตรวจกับตัวบทแล้ว'})
        admin.post(url, data={'action': 'confirm', 'reason': 'ยืนยันขอบเขตของงาน'})
        references = {r['source_id']: r for r in current_config(assessment)['references']}
        self.assertTrue(references['TH-EMS-2551']['is_binding'] and references['TH-EMS-2551']['confirmed'])
        sync_catalog(db.session)
        db.session.commit()
        self.assertEqual(db.session.get(RegulatoryReference, 'TH-EMS-2551').verification_status, 'expert_verified')


class SuiteIntegrationTests(Base):
    def test_all_eight_suites_always_present(self):
        for slug in DOMAIN_SLUGS:
            pack = read_pack_file(slug)
            profile = {'org_type': pack['organization_types'][0]['id'], 'data_categories': [pack['data_categories'][0]['id']], 'decision_impact': 'information', 'flags': {}}
            suites = build_configuration(slug, profile)['suites']
            self.assertEqual([s['code'] for s in suites], [c for c, _ in CORE_SUITES])
            self.assertTrue(all(s['active_count'] >= 1 for s in suites), slug)

    def test_same_suite_gives_different_controls_per_domain(self):
        seen = {}
        for slug, profile in (('justice', {'org_type': 'JUS.ORG.COURT_JUSTICE', 'use_case': 'JUS.UC.SUMMARY', 'data_categories': ['JUS.DATA.CASE'], 'decision_impact': 'significant', 'flags': {}}),
                              ('education', {'org_type': 'EDU.ORG.SCHOOL', 'use_case': 'EDU.UC.TUTOR', 'data_categories': ['EDU.DATA.MINOR'], 'decision_impact': 'assistive', 'flags': {'involves_minors': True}}),
                              ('healthcare', PROFILE_TRIAGE),
                              ('local_government', {'org_type': 'LGOV.ORG.SAO', 'use_case': 'LGOV.UC.CHATBOT', 'data_categories': ['LGOV.DATA.CITIZEN'], 'decision_impact': 'assistive', 'flags': {}})):
            config = build_configuration(slug, profile)
            suite = next(s for s in config['suites'] if s['code'] == 'TS04')
            status = {c['id']: c['final_status'] for c in config['controls']}
            seen[slug] = {c for c in suite['control_ids'] if status[c] != 'not_applicable' and not c.startswith('GEN-')}
        self.assertIn('JUS-03', seen['justice'])
        self.assertIn('EDU-05', seen['education'])
        self.assertIn('EMS-02', seen['healthcare'])
        self.assertIn('LGOV-02', seen['local_government'])
        self.assertEqual(len({frozenset(v) for v in seen.values()}), 4)

    def test_general_is_a_fallback_and_does_not_get_domain_controls(self):
        config = build_configuration('general', {'org_type': 'GEN.ORG.PRIVATE', 'data_categories': ['GEN.DATA.INTERNAL'], 'decision_impact': 'assistive', 'flags': {}})
        self.assertTrue(all(c['id'].startswith('GEN-') for c in config['controls']))

    def test_existing_assessments_remain_accessible_and_unchanged(self):
        check = DocumentCheck.query.first()
        before = (check.compliance_score, check.compliance_results_json, check.domain_slug)
        client = self.client_for(self.admin)
        self.assertEqual(client.get(f'/check/{check.id}').status_code, 200)
        self.assertIn(check.original_filename, client.get('/assessments').get_data(as_text=True))
        sync_catalog(db.session)
        db.session.commit()
        db.session.refresh(check)
        self.assertEqual(before, (check.compliance_score, check.compliance_results_json, check.domain_slug))


class EvidenceTests(Base):
    def test_invalid_upload_rejected_and_duplicates_skipped(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        client.post(f'/assessments/{assessment.id}/evidence', data={'pdf_files': (io.BytesIO(b'not a pdf'), 'fake.pdf')}, content_type='multipart/form-data')
        client.post(f'/assessments/{assessment.id}/evidence', data={'pdf_files': (io.BytesIO(b'%PDF-broken'), 'broken.pdf')}, content_type='multipart/form-data')
        self.assertEqual(DocumentFile.query.filter_by(check_id=assessment.check_id).count(), 0)
        self.assertEqual(os.listdir(self.uploads), [])
        content = make_pdf('triage guideline').getvalue()
        for name in ('one.pdf', 'same-content.pdf'):
            client.post(f'/assessments/{assessment.id}/evidence', data={'pdf_files': (io.BytesIO(content), name)}, content_type='multipart/form-data')
        self.assertEqual(DocumentFile.query.filter_by(check_id=assessment.check_id).count(), 1)

    def test_requirement_mapping_is_correct_with_page_provenance(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, 'nothing relevant here', 'Triage guideline for undertriage review')
        self.assertEqual(client.get(f'/assessments/{assessment.id}/step/5').status_code, 200)
        row = EvidenceMapping.query.filter_by(assessment_id=assessment.id, requirement_id='EV.EMS.TRIAGE').first()
        self.assertEqual(row.page, 2)
        self.assertIsNone(EvidenceMapping.query.filter_by(assessment_id=assessment.id, requirement_id='EV.EMS.ALLOCATION').first())

    def test_cross_user_access_is_denied(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, 'triage guideline')
        attacker = self.client_for(self.other)
        for path in (f'/assessments/{assessment.id}/step/5', f'/assessments/{assessment.id}/report.json', f'/assessments/{assessment.id}/kg.json', f'/assessments/{assessment.id}/report.csv'):
            self.assertEqual(attacker.get(path).status_code, 403, path)
        self.assertEqual(attacker.post(f'/assessments/{assessment.id}/run').status_code, 403)
        self.assertNotIn('evidence.pdf', attacker.get('/evidence').get_data(as_text=True))
        own = self.assessment_for_other()
        source = DocumentFile.query.filter_by(check_id=assessment.check_id).first()
        self.assertEqual(attacker.post(f'/assessments/{own.id}/evidence/reuse', data={'file_id': source.id}).status_code, 403)

    def assessment_for_other(self):
        row = DomainAssessment(user_id=self.other.id, domain_slug='healthcare', name='B', organization_name='Org', profile_json=json_dumps(PROFILE_TRIAGE), status='draft', current_step=5, data_classification='confidential')
        db.session.add(row)
        db.session.commit()
        return row

    def test_sensitive_data_cannot_be_set_to_open(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        client.post(f'/assessments/{assessment.id}/classification', data={'data_classification': 'open', 'acknowledged': 'open'})
        db.session.refresh(assessment)
        self.assertEqual(assessment.data_classification, 'confidential')

    def test_confidential_evidence_cannot_be_reused_in_open_assessment(self):
        source = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, source, 'triage guideline')
        profile = {'org_type': 'GEN.ORG.PRIVATE', 'data_categories': ['GEN.DATA.INTERNAL'], 'decision_impact': 'assistive', 'flags': {}}
        target = self.assessment('general', profile, classification='open')
        file_row = DocumentFile.query.filter_by(check_id=source.check_id).first()
        client.post(f'/assessments/{target.id}/evidence/reuse', data={'file_id': file_row.id})
        self.assertEqual(DocumentFile.query.filter_by(check_id=target.check_id).count(), 0)


class ScoringTests(Base):
    RUBRIC = {'id': 'R', 'version': '1', 'gate_min_level': 2, 'coverage_caps': [[0.34, 1], [0.67, 2], [1.01, 3]], 'human_review': 'critical_or_high_risk'}

    def control(self, **extra):
        return {'id': 'C-1', 'evidence': ['E1', 'E2'], 'final_status': 'applicable', 'is_critical': False, **extra}

    def test_rubric_is_deterministic_and_evidence_caps_model(self):
        control = self.control()
        one = score_finding(control, {'E1': [{}]}, {'score': 3, 'reason': 'r'}, self.RUBRIC, 'low')
        two = score_finding(control, {'E1': [{}]}, {'score': 3, 'reason': 'r'}, self.RUBRIC, 'low')
        self.assertEqual(one, two)
        self.assertEqual(one['level'], 2)
        self.assertEqual(one['state'], 'scored')
        self.assertEqual(coverage_cap(1.0, [[0.5, 1], [1.0, 2], [1.01, 3]]), 3)
        self.assertEqual(coverage_cap(0.67, [[0.5, 1], [1.0, 2], [1.01, 3]]), 2)

    def test_insufficient_evidence_never_invents_a_score(self):
        result = score_finding(self.control(), {}, {'score': 3, 'reason': 'hallucinated'}, self.RUBRIC, 'low')
        self.assertEqual((result['state'], result['level'], result['confidence']), ('insufficient_evidence', 0, 'low'))
        self.assertNotIn('hallucinated', result['reason'])

    def test_no_model_result_requires_human_review(self):
        result = score_finding(self.control(), {'E1': [{}], 'E2': [{}]}, None, self.RUBRIC, 'low')
        self.assertEqual((result['state'], result['level']), ('pending_human_review', 1))

    def test_not_applicable_is_not_scored(self):
        result = score_finding(self.control(final_status='not_applicable'), {'E1': [{}]}, {'score': 3}, self.RUBRIC, 'low')
        self.assertEqual((result['state'], result['level']), ('not_applicable', None))

    def config(self):
        return {'rubric': self.RUBRIC, 'risk': {'level': 'low'}, 'controls': [{'id': f'C-{i}', 'evidence': ['E']} for i in range(1, 6)],
                'suites': [{'code': 'TS01', 'name': 'x', 'control_ids': [f'C-{i}' for i in range(1, 6)]}]}

    def test_high_average_does_not_hide_critical_gap(self):
        rows = [{'control_id': f'C-{i}', 'state': 'human_reviewed', 'level': 3, 'critical': False, 'confidence': 'high', 'missing_requirements': []} for i in range(1, 5)]
        rows.append({'control_id': 'C-5', 'state': 'human_reviewed', 'level': 1, 'critical': True, 'confidence': 'high', 'missing_requirements': []})
        summary = summarize(rows, self.config())
        self.assertGreaterEqual(summary['maturity_percent'], 80)
        self.assertEqual(summary['critical_gate']['status'], 'blocked')
        self.assertEqual(summary['critical_gate']['open'], ['C-5'])
        self.assertEqual(summary['risk']['status'], 'critical_gap')
        self.assertEqual(summary, summarize(list(reversed(rows)), self.config()))

    def test_results_keep_measures_separate(self):
        rows = [{'control_id': 'C-1', 'state': 'pending_human_review', 'level': 2, 'critical': True, 'confidence': 'low', 'missing_requirements': ['E']}]
        summary = summarize(rows, self.config())
        for key in ('compliance', 'maturity_percent', 'evidence_coverage_percent', 'risk', 'confidence_overall'):
            self.assertIn(key, summary)
        self.assertNotIn('overall_score', summary)
        self.assertEqual(summary['critical_gate']['status'], 'pending_review')


class OrchestrationTests(Base):
    TEXT = ('Triage guideline with undertriage review. Human override log kept by staff. Training records for staff. '
            'Escalation to medical director. Call center 1669 protocol. Risk assessment for patient safety. Access log with role-based audit log.')

    def model(self, items):
        return {'used': True, 'items': [{'item_code': i['item_code'], 'score': 3, 'reason': 'เหตุผล', 'gap': '', 'recommendation': ''} for i in items]}

    def run_with_model(self, assessment, client):
        with patch('services.domain_orchestrator.local_model_enabled', return_value=True), patch('services.domain_orchestrator.score_with_local_model', side_effect=lambda text, items, evidence_map=None, instruction=None: self.model(items)) as local, patch('services.domain_orchestrator.score_with_gemini') as gemini:
            self.assertEqual(client.post(f'/assessments/{assessment.id}/run').status_code, 302)
        return local, gemini

    def test_confidential_uses_local_only_and_only_sends_controls_with_evidence(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, self.TEXT)
        local, gemini = self.run_with_model(assessment, client)
        gemini.assert_not_called()
        local.assert_called_once()
        sent = {i['item_code'] for i in local.call_args.args[1]}
        self.assertIn('EMS-01', sent)
        self.assertNotIn('EMS-08', sent)
        self.assertIn('rubric levels 0 to 3', local.call_args.kwargs['instruction'])

    def test_open_routes_to_gemini_and_never_falls_back(self):
        profile = {'org_type': 'GEN.ORG.PRIVATE', 'use_case': 'GEN.UC.ASSISTANT', 'data_categories': ['GEN.DATA.INTERNAL'], 'decision_impact': 'assistive', 'flags': {}}
        assessment = self.assessment('general', profile, classification='open')
        client = self.client_for(self.owner)
        self.upload(client, assessment, 'AI policy governance and risk assessment')
        with patch('services.domain_orchestrator.gemini_enabled', return_value=True), patch('services.domain_orchestrator.score_with_gemini', return_value={'used': False, 'error': 'down', 'items': []}) as gemini, patch('services.domain_orchestrator.score_with_local_model') as local:
            client.post(f'/assessments/{assessment.id}/run')
        gemini.assert_called_once()
        local.assert_not_called()
        db.session.refresh(assessment)
        self.assertIn('down', assessment.run_note)
        self.assertTrue(DomainFinding.query.filter_by(assessment_id=assessment.id, method='evidence_only').first())

    def test_invented_control_from_model_is_ignored(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, self.TEXT)
        with patch('services.domain_orchestrator.local_model_enabled', return_value=True), patch('services.domain_orchestrator.score_with_local_model', return_value={'used': True, 'items': [{'item_code': 'EMS-08', 'score': 3, 'reason': 'invented'}, {'item_code': 'FAKE-1', 'score': 3}]}):
            client.post(f'/assessments/{assessment.id}/run')
        self.assertIsNone(DomainFinding.query.filter_by(control_id='FAKE-1').first())
        self.assertEqual(DomainFinding.query.filter_by(assessment_id=assessment.id, control_id='EMS-08').first().state, 'not_applicable')

    def test_rerun_on_frozen_config_is_consistent_and_keeps_human_review(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, self.TEXT)
        self.run_with_model(assessment, client)
        db.session.refresh(assessment)
        first = json_loads(assessment.summary_json)
        hash_before = assessment.snapshot_hash
        self.run_with_model(assessment, client)
        db.session.refresh(assessment)
        self.assertEqual(first, json_loads(assessment.summary_json))
        admin = self.client_for(self.admin)
        finding = DomainFinding.query.filter_by(assessment_id=assessment.id, control_id='EMS-01').first()
        admin.post(f'/assessments/{assessment.id}/findings/{finding.id}/review', data={'level': '0', 'note': 'ไม่พบบันทึกการแก้ไขจริง', 'stance': 'contradicted'})
        self.run_with_model(assessment, client)
        db.session.refresh(finding)
        db.session.refresh(assessment)
        self.assertEqual((finding.state, finding.level, finding.human_level), ('human_reviewed', 0, 0))
        self.assertEqual(assessment.snapshot_hash, hash_before)
        self.assertIn('EMS-01', json_loads(assessment.summary_json)['critical_gate']['open'])

    def test_frozen_snapshot_ignores_later_pack_changes(self):
        assessment = self.assessment()
        snapshot = assessment.config_snapshot_json
        from models import DomainProfile
        profile = db.session.get(DomainProfile, 'healthcare')
        pack = json_loads(profile.payload_json)
        pack['controls'][0]['title_th'] = 'เปลี่ยนภายหลัง'
        profile.payload_json = json_dumps(pack)
        db.session.commit()
        self.assertEqual(current_config(assessment)['controls'][0]['title_th'], json_loads(snapshot)['controls'][0]['title_th'])
        self.assertNotEqual(current_config(assessment)['controls'][0]['title_th'], 'เปลี่ยนภายหลัง')

    def test_owner_cannot_certify_own_finding_and_committee_needs_assignment(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, self.TEXT)
        self.run_with_model(assessment, client)
        finding = DomainFinding.query.filter_by(assessment_id=assessment.id, control_id='EMS-01').first()
        url = f'/assessments/{assessment.id}/findings/{finding.id}/review'
        self.assertEqual(client.post(url, data={'level': '3', 'stance': 'supported'}).status_code, 403)
        committee = self.client_for(self.committee)
        self.assertEqual(committee.post(url, data={'level': '3', 'stance': 'supported'}).status_code, 403)
        db.session.add(CommitteeAssignment(check_id=assessment.check_id, committee_user_id=self.committee.id, is_active=True))
        db.session.commit()
        self.assertEqual(committee.post(url, data={'level': '3', 'stance': 'supported'}).status_code, 302)
        db.session.refresh(finding)
        self.assertEqual(finding.reviewed_by, self.committee.id)
        self.assertEqual(AuditLog.query.filter_by(action='domain_finding_review').count(), 1)

    def test_trace_reaches_regulation_and_source_page(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, 'irrelevant', self.TEXT)
        self.run_with_model(assessment, client)
        graph = client.get(f'/assessments/{assessment.id}/kg.json').get_json()
        types = {n['type'] for n in graph['nodes']}
        self.assertTrue({'Domain', 'Organization', 'OrganizationType', 'AIUseCase', 'Regulation', 'Requirement', 'GovernanceControl', 'Evidence', 'AssessmentFinding'} <= types)
        relations = {e['relation'] for e in graph['edges']}
        self.assertTrue({'IN_DOMAIN', 'OPERATES', 'APPLIES_TO', 'DERIVED_FROM', 'REQUIRES_EVIDENCE', 'SUPPORTED_BY', 'ASSESSED_USING'} <= relations)
        self.assertTrue(all(e['provenance'] for e in graph['edges']))
        from services.domain_kg import finding_trace
        trace = finding_trace(graph, 'EMS-01', assessment.id)
        self.assertTrue(trace['regulations'])
        self.assertEqual(trace['evidence'][0]['page'], 2)


class WizardAndUiTests(Base):
    def test_guided_flow_with_save_and_resume(self):
        client = self.client_for(self.owner)
        response = client.post('/assessments/new', data={'name': 'งานทดสอบ', 'organization_name': 'Org', 'domain_slug': 'healthcare', 'org_type': 'HLT.ORG.EMS'})
        assessment = DomainAssessment.query.filter_by(name='งานทดสอบ').first()
        self.assertTrue(response.location.endswith(f'/assessments/{assessment.id}/step/2'))
        self.assertTrue(client.get(f'/assessments/{assessment.id}').location.endswith('/step/2'))
        self.assertEqual(client.get(f'/assessments/{assessment.id}/step/5').status_code, 302)
        client.post(f'/assessments/{assessment.id}/step/2', data={'use_case': 'EMS.UC1', 'functional_area': 'EMS.STAGE.3', 'data_categories': ['HLT.DATA.HEALTH'], 'decision_impact': 'assistive', 'flag_is_public_agency': 'yes'})
        db.session.refresh(assessment)
        self.assertEqual(assessment.current_step, 3)
        self.assertIn('EMS UC1', client.get(f'/assessments/{assessment.id}/step/2').get_data(as_text=True))
        page = client.get(f'/assessments/{assessment.id}/step/3').get_data(as_text=True)
        self.assertIn('พระราชบัญญัติการแพทย์ฉุกเฉิน', page)
        page = client.get(f'/assessments/{assessment.id}/step/4').get_data(as_text=True)
        for code, _ in CORE_SUITES:
            self.assertIn(code, page)
        client.post(f'/assessments/{assessment.id}/freeze')
        self.assertEqual(client.get(f'/assessments/{assessment.id}/step/5').status_code, 200)
        client.post(f'/assessments/{assessment.id}/classification', data={'data_classification': 'confidential', 'acknowledged': 'confidential'})
        self.assertEqual(client.get(f'/assessments/{assessment.id}/step/6').status_code, 200)
        with patch('services.domain_orchestrator.local_model_enabled', return_value=False):
            client.post(f'/assessments/{assessment.id}/run')
        db.session.refresh(assessment)
        for path in ('results', 'report', 'report.csv', 'report.json'):
            self.assertEqual(client.get(f'/assessments/{assessment.id}/{path}').status_code, 200, path)
        self.assertIn('หลักฐานไม่พอ', client.get(f'/assessments/{assessment.id}/results').get_data(as_text=True))
        self.assertEqual(client.post(f'/assessments/{assessment.id}/unfreeze').status_code, 302)
        db.session.refresh(assessment)
        self.assertIsNotNone(assessment.config_snapshot_json)

    def test_validation_rejects_tampered_values(self):
        client = self.client_for(self.owner)
        client.post('/assessments/new', data={'name': 'x', 'organization_name': 'y', 'domain_slug': '../etc', 'org_type': 'z'})
        client.post('/assessments/new', data={'name': 'x', 'organization_name': 'y', 'domain_slug': 'justice', 'org_type': 'HLT.ORG.EMS'})
        self.assertEqual(DomainAssessment.query.count(), 0)
        assessment = self.assessment(frozen=False)
        client.post(f'/assessments/{assessment.id}/step/2', data={'use_case': 'JUS.UC.RESEARCH', 'data_categories': ['NOPE'], 'decision_impact': 'x'})
        db.session.refresh(assessment)
        self.assertEqual(assessment.current_step, 4)
        self.assertNotIn('NOPE', json_loads(assessment.profile_json)['data_categories'])

    def test_every_new_page_renders_for_each_role(self):
        paths = ['/overview', '/domains', '/taxonomy', '/assessments', '/evidence', '/regulations', '/reports', '/search?q=ศาล']
        paths += [f'/domains/{s}' for s in DOMAIN_SLUGS] + [f'/domains/{s}/taxonomy' for s in DOMAIN_SLUGS]
        for user in (self.owner, self.admin, self.committee):
            client = self.client_for(user)
            for path in paths:
                response = client.get(path, follow_redirects=True)
                self.assertEqual(response.status_code, 200, (user.role, path))
        for user in (self.owner, self.admin):
            for path in ('/test-suites/explorer', '/test-suites/tree'):
                self.assertEqual(self.client_for(user).get(path).status_code, 200, (user.role, path))

    def test_portal_counts_come_from_database(self):
        client = self.client_for(self.owner)
        page = client.get('/overview').get_data(as_text=True)
        self.assertIn('EI-GDA Governance Intelligence Platform', page)
        self.assertIn('13 control เฉพาะด้าน + 8 แกนกลาง', page)
        self.assessment(frozen=False)
        self.assertIn('ฉบับร่าง', client.get('/overview').get_data(as_text=True))

    def test_mobile_styles_and_responsive_rules_exist(self):
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        self.assertIn('@media(max-width:575px)', css)
        self.assertIn('viewport', open(os.path.join(self.app.template_folder, 'base.html'), encoding='utf-8').read())


class SecurityTests(Base):
    def test_csrf_blocks_post_without_token_when_enforced(self):
        self.app.config['CSRF_ENFORCE_IN_TESTS'] = True
        client = self.client_for(self.owner)
        self.assertEqual(client.post('/assessments/new', data={'name': 'x'}).status_code, 400)
        page = client.get('/assessments/new').get_data(as_text=True)
        self.assertIn('name="_csrf_token"', page)
        self.assertNotIn('__CSRF_TOKEN__', page)
        token = page.split('name="_csrf_token" value="')[1].split('"')[0]
        self.assertEqual(client.post('/assessments/new', data={'_csrf_token': token, 'name': ''}).status_code, 302)
        self.assertEqual(client.post('/assessments/new', headers={'X-CSRF-Token': token}, data={}).status_code, 302)

    def test_anonymous_is_redirected_everywhere(self):
        client = self.app.test_client()
        for path in ('/overview', '/assessments', '/api/taxonomy/justice', '/evidence', '/regulations', '/reports', '/search?q=xx'):
            self.assertEqual(client.get(path).status_code, 302, path)

    def test_admin_only_registry_verification(self):
        response = self.client_for(self.committee).post('/regulations/TH-PDPA-2562/verify', data={'action': 'verify', 'note': 'พยายามยืนยัน'})
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(db.session.get(RegulatoryReference, 'TH-PDPA-2562').verification_status, 'expert_verified')

    def test_output_is_escaped(self):
        payload = '<script>alert(1)</script>'
        row = DomainAssessment(user_id=self.owner.id, domain_slug='general', name=payload, organization_name=payload, profile_json='{}', status='draft', current_step=2)
        db.session.add(row)
        db.session.commit()
        client = self.client_for(self.owner)
        for path in ('/overview', '/assessments', f'/assessments/{row.id}/step/2', '/search?q=' + payload):
            self.assertNotIn(payload, client.get(path).get_data(as_text=True), path)

    def test_plaintext_password_is_not_shown_to_admin(self):
        self.owner.password_plain = 'super-secret-value'
        db.session.commit()
        self.assertNotIn('super-secret-value', self.client_for(self.admin).get('/admin/users').get_data(as_text=True))

    def test_admin_alias_is_off_unless_configured(self):
        from werkzeug.security import generate_password_hash
        self.admin.password_hash = generate_password_hash('correct horse battery')
        db.session.commit()
        client = self.app.test_client()
        data = {'username_or_email': 'adminbuu', 'password': 'correct horse battery'}
        self.app.config['ADMIN_LOGIN_ALIAS'] = ''
        self.assertEqual(client.post('/login', data=data).status_code, 200)
        self.app.config['ADMIN_LOGIN_ALIAS'] = 'adminbuu'
        self.assertEqual(client.post('/login', data=data).status_code, 302)

    def test_weak_registration_password_rejected(self):
        client = self.app.test_client()
        client.post('/register', data={'full_name': 'N', 'email': 'new@example.invalid', 'password': 'short'})
        self.assertIsNone(User.query.filter_by(email='new@example.invalid').first())

    def test_reload_does_not_resend_documents_to_model(self):
        check = DocumentCheck.query.first()
        client = self.client_for(db.session.get(User, check.user_id))
        with patch('app.score_with_gemini') as gemini, patch('app.score_with_local_model') as local:
            self.assertEqual(client.get(f'/check/{check.id}/run-compliance').status_code, 302)
        gemini.assert_not_called()
        local.assert_not_called()

    def test_insecure_secret_refused(self):
        with patch.object(Config, 'SECRET_KEY', 'change-me-in-production'):
            with self.assertRaises(RuntimeError):
                assert_safe_runtime()

    def test_csv_export_neutralizes_formulas(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        with patch('services.domain_orchestrator.local_model_enabled', return_value=False):
            client.post(f'/assessments/{assessment.id}/run')
        finding = DomainFinding.query.filter_by(assessment_id=assessment.id).first()
        finding.reason = '=HYPERLINK("http://evil")'
        db.session.commit()
        self.assertNotIn(',=HYPERLINK', client.get(f'/assessments/{assessment.id}/report.csv').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()


class ModelClientAndReportTests(unittest.TestCase):
    """Local model batching and PDF text, without a server or database."""

    def _response(self, content, finish='stop'):
        class Fake:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}
        return Fake()

    def test_empty_answer_splits_the_batch_instead_of_failing(self):
        from services import local_model_service as service
        items = [{'item_code': f'C{i}', 'title': 't', 'keywords': []} for i in range(4)]

        def fake_post(url, headers, json, timeout, verify):
            sent = __import__('json').loads(json['messages'][0]['content'])['items']
            if len(sent) > 1:
                return self._response(None, 'length')
            return self._response(__import__('json').dumps({'items': [{'item_code': sent[0]['item_code'], 'score': 2}]}))

        with patch.object(service, 'resolve_local_model_name', return_value='m'), patch.object(service.Config, 'LOCAL_MODEL_API_URL', 'http://x/v1/chat/completions'), patch.object(service.Config, 'LOCAL_MODEL_BATCH_SIZE', 4), patch.object(service.requests, 'post', side_effect=fake_post):
            result = service.score_with_local_model('', items)
        self.assertTrue(result['used'])
        self.assertEqual(sorted(i['item_code'] for i in result['items']), ['C0', 'C1', 'C2', 'C3'])

    def test_single_item_exhausting_budget_reports_clear_error(self):
        from services import local_model_service as service
        with patch.object(service, 'resolve_local_model_name', return_value='m'), patch.object(service.Config, 'LOCAL_MODEL_API_URL', 'http://x/v1/chat/completions'), patch.object(service.requests, 'post', return_value=self._response('', 'length')):
            result = service.score_with_local_model('', [{'item_code': 'C', 'title': 't'}])
        self.assertFalse(result['used'])
        self.assertIn('finish_reason=length', result['error'])

    def test_pdf_report_keeps_thai_text(self):
        from services.report_service import generate_system_report
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, 'r.pdf')
            generate_system_report(path, {'filename': 'นโยบายข้อมูล.pdf', 'template_name': 'ทดสอบ', 'standard_summary': [], 'compliance_items': []})
            with fitz.open(path) as doc:
                self.assertIn('นโยบาย', doc[0].get_text())
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class SchemaAdditionTests(unittest.TestCase):
    def test_columns_are_added_once_to_an_old_schema(self):
        from sqlalchemy import create_engine, inspect, text
        from services.schema_additions import ensure_additive_columns
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE templates (id INTEGER PRIMARY KEY, name TEXT)'))
            connection.execute(text('CREATE TABLE document_files (id INTEGER PRIMARY KEY)'))
            connection.execute(text("INSERT INTO templates (name) VALUES ('kept')"))
        # 2 original columns + 2 indexes, plus 5 pilot document-protection columns on document_files.
        self.assertEqual(len(ensure_additive_columns(engine)), 9)
        self.assertEqual(ensure_additive_columns(engine), [])
        self.assertIn('suite_code', {c['name'] for c in inspect(engine).get_columns('templates')})
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT name FROM templates')).scalar(), 'kept')
