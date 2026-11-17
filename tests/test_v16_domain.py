"""V16 domain-adaptive behaviour. Runs on in-memory SQLite with synthetic PDFs only."""
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import fitz

import test_international_catalog as fixtures
from config import Config, assert_safe_runtime
from extensions import db
from models import (ApplicabilityDecision, AuditLog, CommitteeAssignment, DocumentCheck, DocumentFile, DomainAssessment, DomainFinding, EvidenceMapping,
                    RegulatoryReference, SubmissionRevision, TaxonomyEdge, TaxonomyNode, Template, User)
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

    def test_evidence_page_leads_with_what_is_missing(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, 'nothing relevant here', 'Triage guideline for undertriage review')
        html = client.get(f'/assessments/{assessment.id}/step/5').get_data(as_text=True)
        self.assertIn('ev-summary', html)
        self.assertIn('id="evTabs"', html)
        self.assertIn('data-start="missing"', html)
        self.assertLess(html.index('data-ev="missing"'), html.index('data-ev="found"'))  # missing requirements are listed first
        self.assertIn('ระดับเอกสาร', html)
        self.assertIn('class="acc ev-class"', html)  # already classified, so the form is folded away
        self.assertNotIn('aria-disabled="true"', html)

    def test_evidence_page_asks_for_classification_before_moving_on(self):
        assessment = self.assessment(classification=None)
        html = self.client_for(self.owner).get(f'/assessments/{assessment.id}/step/5').get_data(as_text=True)
        self.assertIn('เลือกระดับเอกสารก่อนไปต่อ', html)
        self.assertIn('aria-disabled="true"', html)
        self.assertNotIn('class="acc ev-class"', html)  # the classification form stays open until it is chosen
        self.assertLess(html.index('บันทึกระดับเอกสาร'), html.index('id="pdf_files"'))  # and comes before the upload box

    def test_evidence_library_page_lists_files_and_keeps_the_search(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        self.upload(client, assessment, 'triage guideline', name='triage-manual.pdf')
        page = client.get('/evidence').get_data(as_text=True)
        self.assertIn('triage-manual.pdf', page)
        self.assertNotIn('ล้างคำค้น', page)
        found = client.get('/evidence?q=triage').get_data(as_text=True)
        self.assertIn('triage-manual.pdf', found)
        self.assertIn('ล้างคำค้น', found)
        self.assertIn('ไม่พบไฟล์ที่ตรงกับคำค้น', client.get('/evidence?q=nothing-here').get_data(as_text=True))
        payload = '<img src=x onerror=alert(1)>'
        self.assertNotIn(payload, client.get('/evidence', query_string={'q': payload}).get_data(as_text=True))

    def uploaded_file(self, assessment, client, name='stored-only.pdf', *pages):
        self.upload(client, assessment, *(pages or ('Triage guideline for undertriage review',)), name=name)
        return DocumentFile.query.filter_by(check_id=assessment.check_id, original_filename=name).first()

    def delete_file(self, client, row, **form):
        return client.post(f'/evidence/{row.id}/delete', data=form)

    def test_file_that_was_only_uploaded_can_be_deleted(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        row = self.uploaded_file(assessment, client)
        file_id = row.id
        client.get(f'/assessments/{assessment.id}/step/5')  # the page links the file to requirements it matches
        self.assertTrue(EvidenceMapping.query.filter_by(document_file_id=file_id).count())
        self.assertTrue(os.listdir(self.uploads))
        self.assertEqual(self.delete_file(client, row, back='step').status_code, 302)
        db.session.expire_all()
        self.assertIsNone(db.session.get(DocumentFile, file_id))
        self.assertEqual(EvidenceMapping.query.filter_by(document_file_id=file_id).count(), 0)
        self.assertEqual(os.listdir(self.uploads), [])  # the stored PDF goes with the last row that uses it
        self.assertTrue(AuditLog.query.filter_by(action='domain_evidence_delete').first())

    def test_file_that_an_evaluation_used_cannot_be_deleted(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        row = self.uploaded_file(assessment, client)
        assessment.last_run_at = datetime.utcnow() + timedelta(minutes=1)
        assessment.summary_json = '{}'
        db.session.commit()
        self.delete_file(client, row)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(DocumentFile, row.id))
        self.assertTrue(os.listdir(self.uploads))
        for path in ('/evidence', f'/assessments/{assessment.id}/step/5'):
            page = client.get(path).get_data(as_text=True)
            self.assertIn('ใช้ในการประเมินแล้ว', page, path)
            self.assertNotIn(f'/evidence/{row.id}/delete', page, path)

    def test_file_uploaded_after_the_last_run_is_still_deletable(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        assessment.last_run_at = datetime.utcnow() - timedelta(hours=1)
        assessment.summary_json = '{}'
        db.session.commit()
        row = self.uploaded_file(assessment, client)
        self.assertIn(f'/evidence/{row.id}/delete', client.get('/evidence').get_data(as_text=True))
        self.delete_file(client, row)
        db.session.expire_all()
        self.assertIsNone(db.session.get(DocumentFile, row.id))

    def test_file_that_went_out_in_a_submission_cannot_be_deleted(self):
        assessment = self.assessment()
        client = self.client_for(self.owner)
        row = self.uploaded_file(assessment, client)
        db.session.add(SubmissionRevision(assessment_id=assessment.id, revision_no=1, submitted_by=self.owner.id, files_json=json.dumps([{'file_id': row.id}])))
        db.session.commit()
        self.delete_file(client, row)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(DocumentFile, row.id))
        self.assertIn('ส่งตรวจแล้ว', client.get('/evidence').get_data(as_text=True))

    def test_only_the_owner_can_delete_a_file(self):
        assessment = self.assessment()
        row = self.uploaded_file(assessment, self.client_for(self.owner))
        self.assertEqual(self.delete_file(self.client_for(self.other), row).status_code, 403)
        self.assertEqual(self.delete_file(self.client_for(self.admin), row).status_code, 302)  # not a user role: sent away, nothing deleted
        self.assertEqual(self.delete_file(self.app.test_client(), row).status_code, 302)  # anonymous goes to sign in
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(DocumentFile, row.id))
        self.assertEqual(self.client_for(self.owner).post('/evidence/999999/delete').status_code, 404)

    def test_stored_pdf_stays_while_another_assessment_still_uses_it(self):
        client = self.client_for(self.owner)
        first, second = self.assessment(), self.assessment()
        content = make_pdf('same bytes in both assessments').getvalue()
        for target in (first, second):
            client.post(f'/assessments/{target.id}/evidence', data={'pdf_files': (io.BytesIO(content), 'shared.pdf')}, content_type='multipart/form-data')
        a = DocumentFile.query.filter_by(check_id=first.check_id).first()
        b = DocumentFile.query.filter_by(check_id=second.check_id).first()
        self.assertEqual(a.stored_filename, b.stored_filename)
        self.delete_file(client, a)
        self.assertEqual(len(os.listdir(self.uploads)), 1)
        self.delete_file(client, b)
        self.assertEqual(os.listdir(self.uploads), [])

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
    def test_domain_and_organization_type_carried_from_the_card(self):
        client = self.client_for(self.owner)
        page = client.get('/assessments/new?domain=justice&org_type=JUS.ORG.COURT_CONST').get_data(as_text=True)
        self.assertIn('name="domain_slug" value="justice"', page)
        self.assertIn('name="org_type" value="JUS.ORG.COURT_CONST"', page)  # carried, so it is not asked again
        self.assertNotIn('id="org_type"', page)
        # coming from the sidebar there is nothing to carry: the person chooses here
        page = client.get('/assessments/new').get_data(as_text=True)
        self.assertIn('id="org_type"', page)
        self.assertNotIn('type="hidden" name="domain_slug"', page)
        # a type that belongs to another Domain, or has its own pack, is ignored and the chooser stays
        for wanted in ('EDU.ORG.SCHOOL', 'JUS.ORG.COURT_ADMIN', 'nope'):
            page = client.get('/assessments/new?domain=justice&org_type=' + wanted).get_data(as_text=True)
            self.assertIn('id="org_type"', page, wanted)
            self.assertNotIn('type="hidden" name="org_type"', page, wanted)

    def test_new_assessment_refuses_an_organization_type_that_has_its_own_pack(self):
        client = self.client_for(self.owner)
        before = DomainAssessment.query.count()
        response = client.post('/assessments/new', data={'name': 'ศาล', 'organization_name': 'Org', 'domain_slug': 'justice', 'org_type': 'JUS.ORG.COURT_ADMIN'})
        self.assertEqual(DomainAssessment.query.count(), before)
        self.assertTrue(response.location.endswith('/assessments/new?domain=justice'))
        response = client.post('/assessments/new', data={'name': 'ศาล', 'organization_name': 'Org', 'domain_slug': 'justice', 'org_type': 'JUS.ORG.COURT_JUSTICE'})
        self.assertEqual(DomainAssessment.query.count(), before + 1)

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
        # laws/standards and Test Suites are one page: each suite shows where it comes from
        page = client.get(f'/assessments/{assessment.id}/step/3').get_data(as_text=True)
        self.assertIn('พระราชบัญญัติการแพทย์ฉุกเฉิน', page)
        self.assertIn('Test Suite นี้มาจาก', page)
        for code, _ in CORE_SUITES:
            self.assertIn(code, page)
        self.assertTrue(client.get(f'/assessments/{assessment.id}/step/4').location.endswith(f'/assessments/{assessment.id}/step/3'))  # old address still works
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
        self.assertNotIn('domain-card', page)  # the Domain cards live on /domains, not on the overview
        self.assertNotIn('Domain Explorer', page)
        self.assertRegex(page, r'class="ov-n">0</span><span class="ov-l">ฉบับร่าง')
        self.assessment(frozen=False)
        self.assertRegex(client.get('/overview').get_data(as_text=True), r'class="ov-n">1</span><span class="ov-l">ฉบับร่าง')

    def test_mobile_styles_and_responsive_rules_exist(self):
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        self.assertIn('@media(max-width:575px)', css)
        self.assertIn('viewport', open(os.path.join(self.app.template_folder, 'base.html'), encoding='utf-8').read())


class DomainChooserTests(Base):
    TILES = ('justice', 'education', 'health', 'public_administration', 'other')

    def page(self, user, path='/domains'):
        response = self.client_for(user).get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_data(as_text=True)

    def view(self, page, step, key=None):
        import re
        attribute = {'2': 'data-group', '3': 'data-domain'}.get(str(step))
        pattern = r'<section class="dc-view" data-step="%s"[^>]*%s.*?</section>' % (step, ('%s="%s"' % (attribute, key)) if key else '')
        found = re.search(pattern, page, re.S)
        self.assertIsNotNone(found, (step, key))
        return found.group(0)

    def test_every_pack_is_in_exactly_one_group_and_bad_files_are_refused(self):
        import copy
        from services.domain_catalog import read_groups_file, validate_groups
        good = read_groups_file()
        validate_groups(good)
        members = [slug for g in good['groups'] for slug in g['subdomains']]
        self.assertEqual(sorted(members), sorted(DOMAIN_SLUGS))
        cases = {}
        missing = copy.deepcopy(good)
        missing['groups'][1]['subdomains'].remove('ops_mhesi')
        cases['not in any group'] = missing
        twice = copy.deepcopy(good)
        twice['groups'][0]['subdomains'].append('education')
        cases['both'] = twice
        unknown = copy.deepcopy(good)
        unknown['groups'][0]['subdomains'].append('nope')
        cases['unknown pack'] = unknown
        bad_id = copy.deepcopy(good)
        bad_id['groups'][0]['id'] = 'Justice Sector'
        cases['must be lowercase'] = bad_id
        no_accent = copy.deepcopy(good)
        del no_accent['groups'][0]['accent']
        cases['needs an accent'] = no_accent
        unknown_org = copy.deepcopy(good)
        unknown_org['groups'][0]['covered_org_types']['justice']['JUS.ORG.NOPE'] = 'administrative_court'
        cases['unknown org type'] = unknown_org
        same_pack = copy.deepcopy(good)
        same_pack['groups'][0]['covered_org_types']['justice']['JUS.ORG.COURT_ADMIN'] = 'justice'
        cases['not another pack'] = same_pack
        label = copy.deepcopy(good)
        label['groups'][0]['labels_th'] = {'general': 'x'}
        cases['labels_th'] = label
        for fragment, data in cases.items():
            with self.assertRaises(ValueError, msg=fragment) as ctx:
                validate_groups(data)
            self.assertIn(fragment, str(ctx.exception))

    def test_step_one_shows_five_tiles_and_only_step_one_is_visible_at_first(self):
        for user in (self.owner, self.admin, self.committee):
            page = self.page(user)
            for group in self.TILES:
                self.assertIn('data-group="%s"' % group, page, (user.role, group))
            self.assertEqual(page.count('<button type="button" class="dc-tile'), 5)
            self.assertIn('class="dc-tiles" style="--n:5"', page)  # tiles share the width of the page evenly
            self.assertNotIn('<section class="dc-view" data-step="1" aria-labelledby="dcq1" hidden', page)
            for step in (2, 3):
                for chunk in page.split('<section class="dc-view" data-step="%d"' % step)[1:]:
                    self.assertIn(' hidden', chunk.split('>', 1)[0])  # every later step starts hidden

    def test_step_two_exists_only_for_groups_with_several_packs(self):
        page = self.page(self.owner)
        self.assertEqual(page.count('data-step="2"'), 2)
        justice = self.view(page, 2, 'justice')
        self.assertIn('data-domain="justice"', justice)
        self.assertIn('data-domain="administrative_court"', justice)
        education = self.view(page, 2, 'education')
        for slug in ('education', 'higher_education', 'ops_mhesi'):
            self.assertIn('data-domain="%s"' % slug, education)
        self.assertIn('ต่อยอดจากการศึกษา', education)  # from the pack's own "extends"
        self.assertIn('ศาลยุติธรรม · ศาลรัฐธรรมนูญ', justice)  # titles only, and not the court that the other card already covers
        self.assertNotIn("'jump'", page)  # org types are dicts: none of them may reach the page as raw text
        for group in ('health', 'public_administration', 'other'):
            self.assertNotIn('data-step="2" data-group="%s"' % group, page)
            self.assertIn('data-only=', page.split('data-group="%s"' % group, 1)[1].split('>', 1)[0])  # the tile goes straight to step 3

    def test_every_pack_has_a_check_card_with_real_numbers(self):
        page = self.page(self.owner)
        self.assertEqual(page.count('data-step="3"'), len(DOMAIN_SLUGS))
        healthcare = self.view(page, 3, 'healthcare')
        self.assertIn('<span class="dc-n">17 รายการ</span>', healthcare)
        self.assertIn('<span class="dc-n">13 ประเด็น</span>', healthcare)
        self.assertIn('ประเด็นเฉพาะ', healthcare)
        self.assertIn('(สำคัญมาก 6)', healthcare)
        self.assertIn('ฉบับร่างนำร่อง', healthcare)
        self.assertIn('ชุดนี้เป็นฉบับร่างนำร่อง เกณฑ์ยังรอผู้เชี่ยวชาญทบทวน', healthcare)
        self.assertNotIn('ฉบับร่างนำร่อง', self.view(page, 3, 'education'))
        self.assertIn('องค์กรทั่วไป', self.view(page, 3, 'general'))  # label from the groups file
        self.assertNotIn('Pack)', page.split('id="dc"', 1)[1])

    def test_check_card_has_three_closed_panels_with_the_real_details(self):
        import re
        from models import RegulatoryReference
        page = self.page(self.owner)
        justice = self.view(page, 3, 'justice')
        for kind in ('ev', 'ctl', 'reg'):
            self.assertIn('aria-controls="p-justice-%s"' % kind, justice)
            opening = re.search(r'<div class="dc-panel" id="p-justice-%s"[^>]*>' % kind, justice).group(0)
            self.assertIn(' hidden', opening)  # shown only after the button is pressed
        self.assertEqual(justice.count('class="dc-pbtn is-'), 3)
        self.assertEqual(justice.count('aria-expanded="false"'), 3)
        # evidence, controls (with the critical mark) and the core controls come from the pack
        self.assertIn('ระเบียบหรือนโยบายการใช้ AI ของศาล', justice)
        self.assertIn('การคงอำนาจวินิจฉัยและการกำกับโดยตุลาการ', justice)
        self.assertIn('badge-s s-bad">สำคัญมาก', justice)
        self.assertIn('ประเด็นแกนกลางที่ทุกกลุ่มใช้ร่วมกัน (8 ข้อ)', justice)
        self.assertIn('GEN-01', justice)
        self.assertNotIn('ประเด็นแกนกลางที่ทุกกลุ่มใช้ร่วมกัน', self.view(page, 3, 'general'))  # the core itself has no further core
        # the numbers on the buttons match the data
        references = [r for r in RegulatoryReference.query.filter_by(is_active=True).all() if 'justice' in json_loads(r.domains_json, default=[])]
        counts = {kind: int(re.search(r'aria-controls="p-justice-%s">.*?<span class="dc-n">(\d+) ' % kind, justice, re.S).group(1)) for kind in ('ev', 'ctl', 'reg')}
        self.assertEqual(counts, {'ev': 7, 'ctl': 6, 'reg': len(references)})
        self.assertGreater(len(references), 0)
        self.assertIn('กฎหมายและข้อกำหนด (', justice)
        # unverified states stay unshown, as everywhere else in the product
        for label in ('รอตรวจสอบ', 'พบจากการค้นหา ยังไม่เปิดอ่าน', 'พบแหล่งทางการ', 'ร่าง ไม่พบแหล่ง'):
            self.assertNotIn(label, page)

    def test_panel_script_closes_others_and_resets_when_a_card_is_hidden(self):
        js = open(os.path.join(self.app.static_folder, 'js', 'domain-chooser.js'), encoding='utf-8').read()
        for needle in ('function togglePanel', 'function closePanels', 'closePanels(v)', "'aria-expanded'", 'is-open'):
            self.assertIn(needle, js)

    def test_org_type_covered_by_another_pack_is_a_grey_chip_that_jumps_there(self):
        import re
        page = self.page(self.owner)
        justice = self.view(page, 3, 'justice')
        self.assertIn('data-org="JUS.ORG.COURT_JUSTICE"', justice)  # a type this pack keeps is a choice the person can pick
        self.assertIn('ศาลรัฐธรรมนูญ</button>', justice)
        self.assertNotIn('data-org="JUS.ORG.COURT_ADMIN"', justice)
        chip = re.search(r'<button type="button" class="dc-chip is-other" data-jump="administrative_court"[^>]*>.*?</button>', justice, re.S)
        self.assertIsNotNone(chip)  # the court the other pack covers is shown, but as a link to that pack
        self.assertIn('ศาลปกครอง', chip.group(0))
        self.assertIn('สีเทา = หน่วยงานที่มีชุดประเมินของตัวเอง', justice)
        administrative = self.view(page, 3, 'administrative_court')
        self.assertNotIn('data-jump', administrative)
        self.assertNotIn('สีเทา =', administrative)  # the note appears only when a grey chip does
        self.assertIn('ศาลปกครองสูงสุด', administrative)

    def test_card_top_row_shows_the_group_the_draft_mark_and_the_version_to_staff_only(self):
        import re
        owner = self.page(self.owner)
        self.assertNotIn('class="dc-ver"', owner)  # the people who assess do not need the pack version
        for user in (self.admin, self.committee):
            staff = self.page(user)
            self.assertEqual(staff.count('class="dc-ver"'), len(DOMAIN_SLUGS), user.role)
            self.assertRegex(staff, r'class="dc-ver"[^>]*>v\d')
        justice = self.view(owner, 3, 'justice')
        self.assertIn('ด้านยุติธรรม · Justice', justice)
        self.assertEqual(justice.count('class="dc-draft"'), 0)
        self.assertEqual(self.view(owner, 3, 'healthcare').count('class="dc-draft"'), 1)
        general = self.view(owner, 3, 'general')
        self.assertNotIn('ด้านด้าน', general)  # the "other" group already reads as a phrase, so it gets no "ด้าน" in front
        self.assertIn('ด้านอื่น ๆ หรือยังไม่แน่ใจ', general)
        self.assertEqual(re.findall(r'<h3 class="dc-name">', justice).__len__(), 1)

    def test_card_has_example_work_and_audience_boxes_without_divider_lines(self):
        owner = self.page(self.owner)
        justice = self.view(owner, 3, 'justice')
        self.assertIn('ตัวอย่างงานที่ประเมินได้', justice)
        self.assertIn('เลือกประเภทองค์กรของคุณ', justice)  # people who assess pick their organization type on the card
        self.assertIn('เหมาะสำหรับ', self.view(self.page(self.committee), 3, 'justice'))  # everyone else just sees who it suits
        self.assertIn('ประเภทงาน</span>', justice)
        self.assertIn('data-jump=', owner)
        js = open(os.path.join(self.app.static_folder, 'js', 'domain-chooser.js'), encoding='utf-8').read()
        self.assertIn('[data-jump]', js)
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        card = css.split('.dc-card{', 1)[1].split('.dc-panel{', 1)[0]
        self.assertNotIn('border-top', card)  # the card is divided by space and tint, not by rules
        self.assertNotIn('border-bottom', card)

    def test_start_button_by_role_and_no_detail_button_in_the_card(self):
        owner = self.page(self.owner)
        self.assertEqual(owner.count('href="/assessments/new?domain='), len(DOMAIN_SLUGS))
        self.assertNotIn('data-notice=', owner)
        # the card has the start button and the three panels only; the pack pages stay reachable by address and in the no-script list
        self.assertNotIn('ดูรายละเอียดทั้งหมด', owner)
        frame = owner.split('class="dc-frame"', 1)[1].split('<noscript>', 1)[0]
        self.assertNotIn('href="/domains/', frame)
        for slug in DOMAIN_SLUGS:
            self.assertIn('href="/domains/%s"' % slug, owner.split('<noscript>', 1)[1])
        for user in (self.admin, self.committee):
            page = self.page(user)
            self.assertNotIn('/assessments/new?domain=', page, user.role)
            self.assertEqual(page.count('data-notice="notice-'), len(DOMAIN_SLUGS))
            self.assertIn('การเริ่มประเมินทำได้เฉพาะบัญชีผู้ใช้งานที่ประเมินระบบ AI', page)

    def test_disabled_pack_leaves_its_choice_and_a_single_pack_group_skips_step_two(self):
        with patch.dict(os.environ, {'EIGDA_DISABLED_DOMAINS': 'administrative_court'}):
            sync_catalog(db.session)
            db.session.commit()
            page = self.page(self.owner)
            self.assertNotIn('administrative_court', page)
            self.assertNotIn('data-step="2" data-group="justice"', page)
            self.assertIn('data-only="justice"', page.split('data-group="justice"', 1)[1].split('>', 1)[0])
        sync_catalog(db.session)
        db.session.commit()
        self.assertIn('data-domain="administrative_court"', self.page(self.owner))

    def test_unfinished_work_is_offered_to_its_owner_only(self):
        draft = self.assessment(slug='healthcare', frozen=False)
        page = self.page(self.owner)
        self.assertIn('มีงานค้างอยู่', page)
        self.assertIn('href="/assessments/%d"' % draft.id, page)
        self.assertIn('สุขภาพและการแพทย์ฉุกเฉิน', page.split('มีงานค้างอยู่', 1)[1].split('</div>', 1)[0])
        self.assertIn('ขั้นที่ 3 จาก 6', page)  # stored step 4 is shown as 3: laws and Test Suites are one step
        self.assertNotIn('มีงานค้างอยู่', self.page(self.other))
        self.assertNotIn('มีงานค้างอยู่', self.page(self.committee))

    def test_script_noscript_fallback_and_no_step_bar(self):
        page = self.page(self.owner)
        self.assertIn('src="/static/js/domain-chooser.js"', page)
        self.assertIn('<noscript>', page)
        for gone in ('dc-steps', 'dc-step ', 'dc-bar', 'data-back'):
            self.assertNotIn(gone, page)  # the choice happens on one page, there is no step bar and no back buttons
        js = open(os.path.join(self.app.static_folder, 'js', 'domain-chooser.js'), encoding='utf-8').read()
        for needle in ('history.pushState', "'popstate'", 'location.hash', 'aria-pressed', 'is-selected'):
            self.assertIn(needle, js)
        self.assertIn('!groups[g] && packs[g]', js)  # justice and education are both a group id and a pack slug: the group wins

    def test_choices_are_toggle_buttons_that_start_unselected(self):
        page = self.page(self.owner)
        self.assertEqual(page.count('class="dc-tile"'), 5)
        self.assertEqual(page.count('class="dc-opt"'), 5)  # justice 2 + education 3
        self.assertEqual(page.count('aria-pressed="false"'), 10 + page.count('data-org="'))  # plus the organization type chips
        self.assertNotIn('aria-pressed="true"', page)
        self.assertEqual(page.count('class="dc-check"'), 10)
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        selected = css.split('.dc-tile.is-selected,.dc-opt.is-selected{', 1)[1].split('}', 1)[0]
        self.assertIn('border-color:var(--accent)', selected)
        self.assertIn('box-shadow:0 0 0 2px var(--accent)', selected)  # a ring in the group colour marks the choice
        self.assertIn('.is-selected>.dc-check{display:grid}', css)

    def test_content_sits_in_one_frame_with_header_step_band_and_body(self):
        page = self.page(self.owner)
        positions = [page.index(marker) for marker in ('class="dc-frame"', 'class="dc-head"', 'class="dc-stage"')]
        self.assertEqual(positions, sorted(positions))
        frame = page.split('class="dc-frame"', 1)[1]
        for part in ('class="dc-tiles"', 'data-step="2"', 'data-step="3"'):
            self.assertIn(part, frame)  # every part of the choice is inside the frame, not on the page background
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        rule = css.split('.dc-frame{', 1)[1].split('}', 1)[0]
        for declaration in ('border:var(--bw) solid var(--rule)', 'border-radius:var(--r)', 'background:var(--sheet)', 'overflow:hidden'):
            self.assertIn(declaration, rule)
        # the frame and its body never use the page colour (--paper); the cards inside use it, so they stand out from the white frame
        self.assertNotIn('background:var(--paper)', rule)
        self.assertNotIn('background:var(--paper)', css.split('.dc-stage{', 1)[1].split('}', 1)[0])
        tile = css.split('.dc-tile{', 1)[1].split('}', 1)[0]
        self.assertIn('color-mix(in srgb,var(--accent) 6%,#fff)', tile)  # a faint tint of the group colour, not the page colour
        self.assertNotIn('background:var(--paper)', tile)
        for gone in ('.dc-bar{', '.dc-steps{', '.dc-step{', '.dc-back{'):
            self.assertNotIn(gone, css)

    def test_page_has_no_fixed_maximum_width_so_zooming_out_leaves_no_side_bands(self):
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        rule = css.split('.dc{', 1)[1].split('}', 1)[0]
        self.assertNotIn('max-width', rule)
        # the wrapper's own cap (1360px, for the other pages) is lifted for the pages that carry fluid-page: the chooser and the pack page
        lifted = css.split('.page-content:has(> .fluid-page){', 1)[1].split('}', 1)[0]
        self.assertIn('max-width:none', lifted)
        self.assertIn('class="gov dc fluid-page ov-canvas dc-solo"', self.page(self.owner))
        self.assertIn('class="gov fluid-page"', self.page(self.owner, '/domains/justice'))
        for path in ('/overview', '/assessments', '/evidence', '/regulations', '/reports', '/test-suites/tree', '/test-suites/graph'):  # the pages restyled like the chooser share its full width
            self.assertIn('class="gov dc fluid-page ov', self.page(self.owner, path), path)  # extra modifier classes may follow
        self.assertNotIn('fluid-page', self.page(self.owner, '/dashboard'))  # other pages keep the standard maximum width
        self.assertIn('max-width:72ch', css.split('.dc-desc p{', 1)[1].split('}', 1)[0])  # the text line length stays limited

    def test_group_accents_are_readable_and_distinct(self):
        import colorsys

        def rgb(h):
            return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]

        def luminance(h):
            r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb(h)]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def contrast(a, b):
            hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
            return (hi + 0.05) / (lo + 0.05)

        def hue(h):
            return colorsys.rgb_to_hsv(*rgb(h))[0] * 360

        def gap(a, b):
            d = abs(hue(a) - hue(b)) % 360
            return min(d, 360 - d)

        from services.domain_catalog import read_groups_file
        accents = {g['id']: g['accent'] for g in read_groups_file()['groups']}
        for group, accent in accents.items():
            self.assertGreaterEqual(contrast(accent, '#ffffff'), 4.5, group)
            # the field chip on the check card writes the accent on a 6% tint of itself
            tint = '#%02x%02x%02x' % tuple(round(c * 255 * 0.06 + 255 * 0.94) for c in rgb(accent))
            self.assertGreaterEqual(contrast(accent, tint), 4.5, group + ' on its tint')
        coloured = [g for g in accents if g != 'other']  # the last group is a neutral slate on purpose
        for i, a in enumerate(coloured):
            for b in coloured[i + 1:]:
                self.assertGreaterEqual(gap(accents[a], accents[b]), 40, (a, b))
            for meaning, colour in {'primary action': '#0b6357', 'draft': '#7a4a00', 'critical': '#9e1b14'}.items():
                self.assertGreaterEqual(gap(accents[a], colour), 30, (a, meaning))


class SidebarFoldTests(Base):
    def test_header_has_no_search_box_or_domain_dropdown(self):
        page = self.client_for(self.owner).get('/overview').get_data(as_text=True)
        header = page.split('<header class="app-topbar">', 1)[1].split('</header>', 1)[0]
        for gone in ('role="search"', 'globalSearch', 'topbar-search', 'bi-layers'):
            self.assertNotIn(gone, header)
        for kept in ('sidebar-toggle', 'topbar-title', 'notice-menu', 'user-chip'):
            self.assertIn(kept, header)

    def test_toggle_is_an_accessible_button_wired_to_the_sidebar(self):
        page = self.client_for(self.owner).get('/overview').get_data(as_text=True)
        self.assertIn('id="appSidebar"', page)
        toggle = page.split('class="icon-btn sidebar-toggle"', 1)[1].split('>', 1)[0]
        for attribute in ('aria-controls="appSidebar"', 'aria-expanded="true"', 'aria-label="ย่อเมนู"'):
            self.assertIn(attribute, toggle)
        # the remembered state is applied from the head, before first paint
        head = page.split('</head>', 1)[0]
        self.assertIn("localStorage.getItem('eigda.sidebar')", head)
        self.assertIn('sidebar-collapsed', head)

    def test_collapsed_rail_keeps_labels_for_screen_readers_and_only_applies_on_wide_screens(self):
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        block = css.split('sidebar can fold to an icon rail', 1)[1].split('/* name tooltip for the folded rail', 1)[0]
        self.assertIn('@media(min-width:992px)', block)
        self.assertIn('html.sidebar-collapsed{--sidebar:72px}', block)
        rail = block.split('@media(min-width:992px)', 1)[1]
        self.assertNotIn('display:none', rail)
        self.assertNotIn('position:absolute', rail)  # labels are faded and clipped, never taken out of the layout
        self.assertIn('opacity:0', rail)
        self.assertNotIn('justify-content', rail)  # icons keep their alignment, so they cannot jump sideways
        self.assertNotIn('padding-right', rail)
        self.assertNotIn('.side-nav a{', rail)  # no change to the link box itself between the two states
        js = open(os.path.join(self.app.static_folder, 'js', 'app.js'), encoding='utf-8').read()
        self.assertIn("localStorage.setItem('eigda.sidebar'", js)
        self.assertIn("matchMedia('(min-width: 992px)')", js)
        self.assertIn("'ขยายเมนู'", js)
        self.assertIn('eigda:layout-start', js)
        self.assertIn("className = 'rail-tip'", js)  # an instant name tooltip for the folded rail
        self.assertNotIn('a.title =', js)  # the slow native tooltip is not used any more
        css = open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()
        rule = css.split('.rail-tip{', 1)[1].split('}', 1)[0]
        for declaration in ('position:fixed', 'pointer-events:none', 'color:#fff', 'background:var(--navy)'):
            self.assertIn(declaration, rule)
        self.assertIn('eigda:layout-end', js)


class SpacingStandardTests(Base):
    """New UI uses the spacing, border and radius tokens from the top of v16.css instead of ad-hoc pixel values."""

    def css(self):
        return open(os.path.join(self.app.static_folder, 'css', 'v16.css'), encoding='utf-8').read()

    def test_tokens_are_a_four_pixel_scale(self):
        import re
        css = self.css()
        scale = [int(v) for v in re.findall(r'--sp-\d:(\d+)px', css.split('--bw:', 1)[0])]
        self.assertEqual(scale, [4, 8, 12, 16, 24, 32, 48])
        self.assertTrue(all(v % 4 == 0 for v in scale))
        for token in ('--bw:1px', '--r:12px', '--r-sm:8px', '--r-xs:4px', '--r-pill:999px', '--topbar-h:72px', '--touch:44px'):
            self.assertIn(token, css)

    def test_new_styles_use_tokens_for_space_and_radius(self):
        import re
        css = self.css()
        # the sidebar fold block, its tooltip and the domains chooser; older styles are not covered yet
        region = css[css.index('/* ---------- sidebar can fold'):css.index('/* ---------- top bar')] + css[css.index('/* domains chooser'):]
        violations = []
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', region):
            if '::before' in selector and 'rail-tip' in selector:  # tooltip arrow geometry
                continue
            for prop, value in re.findall(r'(?<![\w-])((?:padding|margin)(?:-[a-z]+)?|gap|row-gap|column-gap|border-radius):([^;]+)', body):
                raw = [m for m in re.findall(r'(?<![\w.-])(\d+(?:\.\d+)?)px', value) if m != '0']
                if raw:
                    violations.append((selector.strip(), prop, value.strip()))
        self.assertEqual(violations, [])

    def test_topbar_and_page_padding_line_up(self):
        css = self.css()
        self.assertIn('.app-topbar{height:var(--topbar-h);min-height:var(--topbar-h)', css)
        self.assertIn('padding:0 var(--sp-6)', css.split('.app-topbar{', 1)[1].split('}', 1)[0])  # same side padding as the page
        self.assertIn('.page-content{padding:var(--sp-5) var(--sp-6) var(--sp-7)', css)

    def test_rail_icons_sit_at_the_centre_of_the_rail(self):
        css = self.css()
        # 12px sidebar padding + 12px link padding + half of the 24px icon box = 36px = half of the 72px rail
        self.assertIn('padding:var(--sp-4) var(--sp-3) var(--sp-3)', css.split('.app-sidebar{', 1)[1].split('}', 1)[0])
        self.assertIn('padding:var(--sp-2) var(--sp-3)', css.split('.side-nav a,.logout-link{', 1)[1].split('}', 1)[0])
        self.assertIn('width:24px', css.split('.side-nav a i,.logout-link i{', 1)[1].split('}', 1)[0])
        self.assertIn('html.sidebar-collapsed{--sidebar:72px}', css)


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
