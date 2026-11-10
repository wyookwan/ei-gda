"""Administrative Court domain: pack integrity, assessment, overlay scoring, isolation, SILA spec, regression.
In-memory SQLite, synthetic PDFs only, no model calls."""
import json
import os
import re
import unittest
from unittest.mock import patch

from test_v16_domain import Base, make_pdf  # noqa: F401  (reuses the V16 fixtures)

from extensions import db
from models import DomainAssessment, DomainFinding, RegulatoryReference, TaxonomyNode
from services.domain_catalog import DOMAIN_SLUGS, get_pack, read_pack_file, read_registry_file, read_sila_pack, sync_catalog
from services.domain_orchestrator import build_configuration
from services.domain_rubric import summarize

ADM = {'org_type': 'ADM.ORG.FIRST', 'functional_area': 'ADM.FA.RESEARCH', 'use_case': 'ADM.UC.RESEARCH',
       'data_categories': ['ADM.DATA.PUBLISHED', 'ADM.DATA.PARTY'], 'decision_impact': 'assistive',
       'flags': {'is_public_agency': True, 'public_facing': False, 'influences_decision': False, 'uses_external_vendor': False}}
EVIDENCE = ('Court AI usage policy and role and responsibility matrix (RACI). Approval log of the human review workflow. '
            'Source registry of published judgments. Citation verification log and evaluation report. Access control policy and data classification. '
            'Legal version registry with effective date metadata.')


class PackIntegrity(Base):
    def test_domain_suites_controls_and_references(self):
        pack = read_pack_file('administrative_court')
        self.assertIn('administrative_court', DOMAIN_SLUGS)
        self.assertEqual(pack['title_th'], 'ศาลปกครอง')
        self.assertEqual([s['id'] for s in pack['domain_suites']], [f'JUD-0{i}' for i in range(1, 9)])
        ids = {c['id'] for c in pack['controls']}
        self.assertTrue({f'JUD-CTRL-00{i}' for i in range(1, 6)} <= ids)
        self.assertTrue(all(c['control_status'] == 'proposed' for c in pack['controls']))
        critical = {c['id'] for c in pack['controls'] if c['critical']}
        self.assertEqual(critical, {'JUD-CTRL-001', 'JUD-CTRL-002', 'JUD-CTRL-003', 'JUD-CTRL-010'})
        for suite in pack['domain_suites']:
            self.assertTrue(suite['sections'] and all(sec['control_ids'] for sec in suite['sections']), suite['id'])
        registry = {r['source_id']: r for r in read_registry_file()['references']}
        for sid in ('TH-CONST-2560', 'TH-ADMIN-COURT-2542', 'TH-ADMIN-COURT-PROC-2543', 'TH-ADMIN-PROC-2539', 'TH-OFFICIAL-INFO-2540', 'TH-PDPA-2562',
                    'TH-CYBER-2562', 'TH-ETA-2544', 'TH-E-GOV-OPS-2565', 'ISO-42001', 'ISO-23894', 'ISO-27001', 'ISO-27701', 'ISO-38507', 'ISO-22989',
                    'ISO-5259', 'ISO-25059', 'ISO-5338', 'CEPEJ-CHARTER-2018', 'UNESCO-COURTS-2025', 'CEPEJ-GENAI-2025'):
            self.assertIn(sid, registry)
            self.assertIn('administrative_court', registry[sid]['domains'], sid)
            self.assertNotEqual(registry[sid]['verification_status'], 'expert_verified', sid)
        for control in pack['controls']:
            for clause in control['reference_clauses']:
                self.assertEqual(clause['status'], 'pending_verification')
                # No section numbers are invented for Thai law; they stay "to be specified".
                if clause['source_id'].startswith('TH-'):
                    self.assertIsNone(re.search(r'มาตรา\s*\d', clause['clause']), clause)

    def test_taxonomy_has_overlay_suites_and_sila_cases(self):
        nodes = {n.node_id: n for n in TaxonomyNode.query.filter_by(is_active=True).all()}
        self.assertEqual(nodes['DSUITE.JUD-04'].node_type, 'domain_suite')
        self.assertEqual(nodes['SILA.JUD-SILA-001'].node_type, 'test_case')
        data = self.client_for(self.owner).get('/api/taxonomy/administrative_court').get_json()
        rels = {(e['src'], e['dst'], e['rel']) for e in data['edges']}
        self.assertIn(('JUD-CTRL-002', 'SILA.JUD-SILA-001', 'VALIDATED_BY'), rels)
        self.assertIn(('DSUITE.JUD-02', 'JUD-CTRL-001', 'GROUPS'), rels)
        self.assertIn(('JUD-CTRL-002', 'REG.CEPEJ-GENAI-2025', 'DERIVED_FROM'), rels)

    def test_sila_pack_is_specification_without_results(self):
        sila = read_sila_pack('administrative_court_redteam')
        self.assertEqual(len(sila['test_cases']), 8)
        self.assertEqual({t['category'] for t in sila['test_cases']}, {c['id'] for c in sila['categories']})
        self.assertTrue(all(t['benchmark']['expert_verification'] == 'pending_expert_review' and t['benchmark']['reference_answer'] is None for t in sila['test_cases']))
        api = self.client_for(self.owner).get('/api/sila/test-packs/administrative_court').get_json()
        self.assertEqual((api['integration_status'], api['results']), ('not_connected', []))
        self.assertEqual(self.client_for(self.owner).get('/api/sila/test-packs/healthcare').status_code, 404)


class AssessmentAndScoring(Base):
    def run_assessment(self):
        a = self.assessment(slug='administrative_court', profile=ADM)
        a.name = 'ผู้ช่วยค้นคว้าคำพิพากษาทดสอบ'
        db.session.commit()
        client = self.client_for(self.owner)
        self.upload(client, a, EVIDENCE)
        with patch('services.domain_orchestrator.local_model_enabled', return_value=False):
            self.assertEqual(client.post(f'/assessments/{a.id}/run').status_code, 302)
        db.session.refresh(a)
        return a, client

    def test_create_select_and_assess_through_routes(self):
        page = self.client_for(self.owner).get('/assessments/new').get_data(as_text=True)
        self.assertIn('ศาลปกครอง', page)
        a, client = self.run_assessment()
        summary = json.loads(a.summary_json)
        self.assertEqual([s['id'] for s in summary['domain_suites']], [f'JUD-0{i}' for i in range(1, 9)])
        self.assertEqual(summary['deployment_gate']['policy_status'], 'proposed')
        self.assertEqual(summary['legal_reference_coverage']['expert_verified'], 0)
        ids = {f.control_id for f in DomainFinding.query.filter_by(assessment_id=a.id).all()}
        self.assertTrue({'JUD-CTRL-001', 'JUD-CTRL-002', 'JUD-CTRL-003'} <= ids)
        # Unverified references never produce a compliance conclusion.
        self.assertEqual({f.compliance_status for f in DomainFinding.query.filter_by(assessment_id=a.id).all()} - {'not_applicable'}, {'not_determined'})
        results = client.get(f'/assessments/{a.id}/results').get_data(as_text=True)
        self.assertIn('ชุดทดสอบเฉพาะ Domain', results)
        self.assertIn('Deployment Gate', results)
        csv_text = client.get(f'/assessments/{a.id}/report.csv').get_data(as_text=True)
        self.assertIn('domain_suites', csv_text.splitlines()[0])
        self.assertIn('JUD-02', csv_text)
        self.assertIn('domain_suites', client.get(f'/assessments/{a.id}/report.json').get_json()['summary'])
        mapped = client.get(f'/assessments/{a.id}/kg.json').get_json()
        self.assertTrue(mapped['nodes'])

    def test_critical_control_is_not_hidden_by_average(self):
        config = build_configuration('administrative_court', ADM)
        active = [c for c in config['controls'] if c['final_status'] != 'not_applicable']
        findings = [{'control_id': c['id'], 'state': 'human_reviewed', 'level': 0 if c['id'] == 'JUD-CTRL-001' else 3, 'critical': c['is_critical'],
                     'confidence': 'high', 'missing_requirements': [], 'compliance_status': 'not_determined'} for c in active]
        summary = summarize(findings, config)
        self.assertGreater(summary['maturity_percent'], 90)
        self.assertEqual(summary['critical_gate']['status'], 'blocked')
        self.assertEqual(summary['deployment_gate']['status'], 'blocked')
        self.assertIn('JUD-CTRL-001', [f['control_id'] for f in summary['critical_findings']])
        jud02 = next(s for s in summary['domain_suites'] if s['id'] == 'JUD-02')
        self.assertEqual((jud02['status'], jud02['critical_open']), ('critical_gap', ['JUD-CTRL-001']))

    def test_dashboard_empty_state_and_isolation(self):
        self.assertIn('ยังไม่มีผลการประเมินสำหรับศาลปกครอง', self.client_for(self.owner).get('/domains/administrative_court/dashboard').get_data(as_text=True))
        a, client = self.run_assessment()
        page = client.get('/domains/administrative_court/dashboard').get_data(as_text=True)
        self.assertIn(a.name, page)
        self.assertIn('ยังไม่เชื่อมต่อ', page)
        other = self.client_for(self.other).get('/domains/administrative_court/dashboard').get_data(as_text=True)
        self.assertIn('ยังไม่มีผลการประเมินสำหรับศาลปกครอง', other)
        self.assertEqual(self.client_for(self.other).get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertEqual(self.client_for(self.other).get(f'/assessments/{a.id}/report.csv').status_code, 403)
        listing = client.get('/assessments?domain=administrative_court').get_data(as_text=True)
        self.assertIn(a.name, listing)
        filtered = client.get('/assessments?domain=healthcare').get_data(as_text=True).split('<main', 1)[1]
        self.assertIn('ยังไม่มีงานตาม Domain', filtered)
        self.assertNotIn(f'/assessments/{a.id}"', filtered)

    def test_pdf_report_export(self):
        import fitz
        from models import AuditLog
        a, client = self.run_assessment()
        response = client.get(f'/assessments/{a.id}/report.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        doc = fitz.open(stream=response.data, filetype='pdf')
        text = ''.join(page.get_text() for page in doc)
        self.assertGreaterEqual(doc.page_count, 1)
        for expected in ('JUD-CTRL-001', 'JUD-02', 'ยังไม่ได้ลงนามดิจิทัล'):
            self.assertIn(expected, text.replace('\n', ' '))
        self.assertTrue(any(f['name'].endswith('Sarabun-Regular') or 'Sarabun' in f['name'] for page in doc for f in [{'name': x[3]} for x in page.get_fonts()]))
        self.assertEqual(AuditLog.query.filter_by(action='domain_report_export', detail='pdf').count(), 1)
        self.assertEqual(self.client_for(self.other).get(f'/assessments/{a.id}/report.pdf').status_code, 403)
        self.assertIn('report.pdf', client.get(f'/assessments/{a.id}/results').get_data(as_text=True))

    def test_unverified_status_labels_are_not_shown(self):
        page = self.client_for(self.owner).get('/regulations').get_data(as_text=True)
        for label in ('รอตรวจสอบ', 'พบจากการค้นหา ยังไม่เปิดอ่าน', 'พบแหล่งทางการ', 'ร่าง ไม่พบแหล่ง'):
            self.assertNotIn(label, page)
        self.assertNotIn('เกณฑ์ที่เสนอ รอตรวจ', self.client_for(self.owner).get('/domains').get_data(as_text=True))

    def test_anonymous_is_redirected(self):
        anon = self.app.test_client()
        for path in ('/domains/administrative_court/dashboard', '/api/sila/test-packs/administrative_court', '/assessments/1/report.pdf'):
            self.assertEqual(anon.get(path).status_code, 302, path)


class Regression(Base):
    BASELINE_KEYS = {'scoring_version', 'rubric', 'evidence_coverage_percent', 'requirements_required', 'requirements_located', 'maturity_percent',
                     'maturity_label', 'suites', 'compliance', 'states', 'confidence', 'confidence_overall', 'risk', 'critical_gate', 'pending_review'}

    def test_other_domains_keep_their_configuration_and_summary_shape(self):
        for slug in ('ops_mhesi', 'higher_education', 'education', 'justice', 'healthcare'):
            pack = get_pack(db.session, slug)
            profile = {'org_type': pack['organization_types'][0]['id'], 'data_categories': [pack['data_categories'][0]['id']], 'decision_impact': 'information', 'flags': {}}
            config = build_configuration(slug, profile)
            self.assertNotIn('domain_suites', config, slug)
            self.assertFalse(any(c['id'].startswith('JUD-') for c in config['controls']), slug)
            findings = [{'control_id': c['id'], 'state': 'scored', 'level': 2, 'critical': False, 'confidence': 'medium', 'missing_requirements': []}
                        for c in config['controls'] if c['final_status'] != 'not_applicable']
            self.assertEqual(set(summarize(findings, config)), self.BASELINE_KEYS, slug)

    def test_rollback_by_configuration_keeps_data(self):
        a = self.assessment(slug='administrative_court', profile=ADM)
        with patch.dict(os.environ, {'EIGDA_DISABLED_DOMAINS': 'administrative_court'}):
            sync_catalog(db.session)
            db.session.commit()
        self.assertIsNone(get_pack(db.session, 'administrative_court'))
        self.assertIsNotNone(db.session.get(DomainAssessment, a.id))
        self.assertNotIn('/domains/administrative_court"', self.client_for(self.owner).get('/domains').get_data(as_text=True))
        self.assertEqual(self.client_for(self.owner).get(f'/assessments/{a.id}/step/5').status_code, 200)  # frozen work still opens
        sync_catalog(db.session)
        db.session.commit()
        self.assertIsNotNone(get_pack(db.session, 'administrative_court'))


if __name__ == '__main__':
    unittest.main()
