"""MHESI pilot acceptance tests. SQLite in a temp folder, synthetic DEMO data only, no model calls.

Each test class maps to one pass criterion in docs/PILOT_HANDOFF.md.
"""
import io
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from config import Config

ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = {}


def _build_template():
    """Seed the DEMO once into a template database; each test copies it (seeding takes seconds)."""
    if _TEMPLATE:
        return _TEMPLATE
    work = tempfile.mkdtemp(prefix='pilot-template-')
    with patch.multiple(Config, SQLALCHEMY_DATABASE_URI=f'sqlite:///{work}/demo.db', SQLALCHEMY_ENGINE_OPTIONS={}, THAID_ENABLED=False,
                        GEMINI_API_KEY='', LOCAL_MODEL_API_URL='', UPLOAD_FOLDER=f'{work}/uploads', REPORT_FOLDER=f'{work}/reports', DEMO_MODE=True):
        from app import create_app
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY='pilot-test-only')
        from migrate_mhesi_pilot import run
        run(app)
        from services.pilot_demo import seed
        _TEMPLATE.update(seed(app, 'Demo-Pilot-2569'), work=work)
        from extensions import db
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    return _TEMPLATE


class PilotBase(unittest.TestCase):
    def setUp(self):
        template = _build_template()
        self.work = tempfile.mkdtemp(prefix='pilot-test-')
        shutil.copy(f"{template['work']}/demo.db", f'{self.work}/demo.db')
        shutil.copytree(f"{template['work']}/uploads", f'{self.work}/uploads')
        self.patcher = patch.multiple(Config, SQLALCHEMY_DATABASE_URI=f'sqlite:///{self.work}/demo.db', SQLALCHEMY_ENGINE_OPTIONS={},
                                      THAID_ENABLED=False, GEMINI_API_KEY='', LOCAL_MODEL_API_URL='', UPLOAD_FOLDER=f'{self.work}/uploads',
                                      REPORT_FOLDER=f'{self.work}/reports', DEMO_MODE=True)
        self.patcher.start()
        from app import create_app
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='pilot-test-only', UPLOAD_FOLDER=f'{self.work}/uploads')
        self.ctx = self.app.app_context()
        self.ctx.push()
        from extensions import db
        self.db = db
        self.case_a, self.case_b = template['case_a'], template['case_b']

    def tearDown(self):
        self.db.session.remove()
        self.db.engine.dispose()
        self.ctx.pop()
        self.patcher.stop()
        shutil.rmtree(self.work, ignore_errors=True)

    def user(self, key):
        from models import User
        return User.query.filter_by(email=f'{key}@demo.invalid').first()

    def client(self, key):
        from services import access_policy as ap
        user = self.user(key)
        client = self.app.test_client()
        from models import OrganizationMembership
        rows = OrganizationMembership.query.filter_by(user_id=user.id, is_active=True).all()
        with client.session_transaction() as s:
            s.update(user_id=user.id, role=user.role, email=user.email, full_name=user.full_name, org_id=rows[0].organization_id if rows else None)
        return client

    def assessment(self, aid):
        from models import DomainAssessment
        self.db.session.expire_all()
        return self.db.session.get(DomainAssessment, aid)

    def b_file(self):
        from models import DocumentFile
        return DocumentFile.query.filter_by(check_id=self.assessment(self.case_b).check_id).first()

    def post(self, client, path, **data):
        return client.post(path, data=data)

    # Case B through the real routes, as the browser would do it.
    def submit_b(self):
        a = self.assessment(self.case_b)
        r = self.post(self.client('buu.staff'), f'/assessments/{a.id}/workflow/submit', version=a.workflow_version, note='ส่งงาน')
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])

    def assign_b(self, committee='committee1'):
        a = self.assessment(self.case_b)
        r = self.post(self.client('ops.coordinator'), f'/assessments/{a.id}/workflow/assign', version=a.workflow_version, committee_user_id=self.user(committee).id)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])

    def start_b(self, committee='committee1'):
        a = self.assessment(self.case_b)
        self.assertEqual(self.post(self.client(committee), f'/assessments/{a.id}/workflow/start-review', version=a.workflow_version).status_code, 302)


class CrossOrganizationIsolation(PilotBase):
    """University A cannot open, view, search or export university B's evidence, even with direct links."""

    def test_other_university_is_blocked_on_every_path(self):
        a = self.assessment(self.case_b)
        f = self.b_file()
        rpu = self.client('rpu.coordinator')
        for path in (f'/assessments/{a.id}/results', f'/assessments/{a.id}/step/5', f'/assessments/{a.id}/report', f'/assessments/{a.id}/report.csv', f'/assessments/{a.id}/report.pdf',
                     f'/assessments/{a.id}/report.json', f'/assessments/{a.id}/kg.json', f'/assessments/{a.id}', f'/assessments/{a.id}/workflow'):
            self.assertEqual(rpu.get(path).status_code, 403, path)
        for path in (f'/check/{a.check_id}', f'/check/{a.check_id}/source/{f.id}', f'/check/{a.check_id}/report', f'/check/{a.check_id}/comparison',
                     f'/check/{a.check_id}/domain-review'):
            response = rpu.get(path)
            self.assertIn(response.status_code, (302, 403), path)
            self.assertNotIn(b'%PDF', response.data, path)
        self.assertNotIn(f.original_filename, rpu.get('/evidence').get_data(as_text=True))
        self.assertNotIn(a.name, rpu.get('/search?q=' + a.name[:6]).get_data(as_text=True))
        self.assertNotIn(a.name, rpu.get('/assessments').get_data(as_text=True))
        self.assertEqual(rpu.post(f'/assessments/{a.id}/workflow/submit', data={'version': a.workflow_version}).status_code, 403)
        from models import AuditLog
        self.assertGreater(AuditLog.query.filter_by(action='access_denied').count(), 5)

    def test_reuse_of_another_organizations_file_is_refused(self):
        from models import DomainAssessment
        rpu_user = self.user('rpu.coordinator')
        mine = DomainAssessment(user_id=rpu_user.id, domain_slug='higher_education', name='RPU', organization_name='RPU', profile_json='{}', status='draft',
                                current_step=5)
        from models import OrganizationMembership
        mine.organization_id = OrganizationMembership.query.filter_by(user_id=rpu_user.id).first().organization_id
        mine.workflow_status, mine.data_classification, mine.config_snapshot_json = 'draft', 'open', '{}'
        self.db.session.add(mine)
        self.db.session.commit()
        response = self.client('rpu.coordinator').post(f'/assessments/{mine.id}/evidence/reuse', data={'file_id': self.b_file().id})
        self.assertEqual(response.status_code, 403)

    def test_owner_university_still_works(self):
        a = self.assessment(self.case_b)
        staff = self.client('buu.staff')
        self.assertEqual(staff.get(f'/assessments/{a.id}/results').status_code, 200)
        response = staff.get(f'/check/{a.check_id}/source/{self.b_file().id}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b'%PDF'))
        from models import AuditLog
        row = AuditLog.query.filter_by(action='file_open').order_by(AuditLog.id.desc()).first()
        self.assertEqual(row.target_id, str(self.b_file().id))
        self.assertNotIn('ร่างนโยบาย', row.detail or '')

    def test_membership_ends_access_and_name_match_grants_nothing(self):
        from models import OrganizationMembership, User
        a = self.assessment(self.case_b)
        outsider = User(full_name='Outsider', email='outsider@demo.invalid', password_hash='x', role='user', organization=a.organization_name)
        self.db.session.add(outsider)
        self.db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as s:
            s.update(user_id=outsider.id, role='user', email=outsider.email)
        self.assertEqual(client.get(f'/assessments/{a.id}/results').status_code, 403)
        staff = self.user('buu.staff')
        OrganizationMembership.query.filter_by(user_id=staff.id).update({'is_active': False})
        self.db.session.commit()
        self.assertEqual(self.client('buu.staff').get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertIn(self.client('buu.staff').get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, (302, 403))


class CommitteeScope(PilotBase):
    """Committee members review only assigned work, and the right ends when revoked."""

    def test_unassigned_committee_is_blocked_and_revocation_ends_access(self):
        a = self.assessment(self.case_b)
        self.submit_b()
        c2 = self.client('committee2')
        self.assertEqual(c2.get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertIn(c2.get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, (302, 403))
        self.assign_b('committee2')
        self.assertEqual(c2.get(f'/assessments/{a.id}/results').status_code, 200)
        self.assertEqual(c2.get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, 200)
        r = self.post(self.client('ops.coordinator'), f'/assessments/{a.id}/workflow/revoke', committee_user_id=self.user('committee2').id, note='เปลี่ยนตัวกรรมการ')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c2.get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertIn(c2.get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, (302, 403))
        self.assertEqual(self.post(c2, f'/assessments/{a.id}/workflow/start-review', version=self.assessment(a.id).workflow_version).status_code, 403)
        from models import AuditLog
        self.assertEqual(AuditLog.query.filter_by(action='permission_review_revoke').count(), 1)
        self.assertIn('สิทธิ์ที่สิ้นสุดแล้ว', c2.get('/review-queue').get_data(as_text=True))

    def test_owner_cannot_review_own_work(self):
        a = self.assessment(self.case_b)
        self.submit_b()
        self.assign_b()
        self.assertEqual(self.post(self.client('buu.staff'), f'/assessments/{a.id}/workflow/start-review', version=self.assessment(a.id).workflow_version).status_code, 403)


class OversightScope(PilotBase):
    """Round coordinators and executives see what their scope allows; originals need a separate grant."""

    def test_coordinator_sees_status_not_originals_until_granted(self):
        a = self.assessment(self.case_b)
        coord = self.client('ops.coordinator')
        rnd = a.round_id
        self.assertEqual(coord.get(f'/rounds/{rnd}/dashboard').status_code, 200)
        self.assertEqual(coord.get(f'/assessments/{a.id}/workflow').status_code, 200)
        self.assertEqual(coord.get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertIn(coord.get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, (302, 403))
        from models import OrganizationMembership
        OrganizationMembership.query.filter_by(user_id=self.user('ops.coordinator').id, role='round_coordinator').update({'can_read_source': True})
        self.db.session.commit()
        self.assertEqual(self.client('ops.coordinator').get(f'/assessments/{a.id}/results').status_code, 200)

    def test_executive_gets_summary_only(self):
        a = self.assessment(self.case_b)
        execu = self.client('mhesi.executive')
        page = execu.get(f'/rounds/{a.round_id}/dashboard')
        self.assertEqual(page.status_code, 200)
        self.assertIn('ไม่รวมรายละเอียดประเด็น', page.get_data(as_text=True))
        csv_text = execu.get(f'/rounds/{a.round_id}/dashboard.csv').get_data(as_text=True)
        self.assertNotIn('open_controls', csv_text)
        self.assertEqual(execu.get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertEqual(execu.get(f'/assessments/{a.id}/report.csv').status_code, 403)
        self.assertEqual(execu.get(f'/rounds/{a.round_id}/export/dsv.json').status_code, 403)
        self.assertIn(execu.get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, (302, 403))
        status_page = execu.get(f'/assessments/{a.id}/workflow').get_data(as_text=True)
        self.assertNotIn('ผลเบื้องต้นของระบบ และผลที่กรรมการยืนยัน', status_page)

    def test_admin_manages_accounts_but_does_not_read_org_evidence(self):
        a = self.assessment(self.case_b)
        admin = self.client('admin')
        self.assertEqual(admin.get('/admin/organizations').status_code, 200)
        self.assertEqual(admin.get(f'/assessments/{a.id}/results').status_code, 403)
        self.assertIn(admin.get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, (302, 403))
        self.assertNotIn(self.b_file().original_filename, admin.get('/evidence').get_data(as_text=True))


class FullLoopAndRevisions(PilotBase):
    """Case B end to end through the routes, keeping every revision and the evidence that closed the issue."""

    def test_case_b_loop_through_routes(self):
        from models import DocumentFile, RevisionRequest, SubmissionRevision, WorkflowEvent
        from services.pilot_demo import TEXT_B2, make_pdf
        a = self.assessment(self.case_b)
        self.submit_b()
        self.assign_b()
        self.start_b()
        committee = self.client('committee1')
        staff_id = self.user('buu.staff').id
        r = self.post(committee, f'/assessments/{a.id}/workflow/raise-issue', control_id='HED-03', severity='critical', reason='ยังไม่พบช่องทางขอทบทวนผล',
                      evidence_required='ประกาศช่องทางขอทบทวนและบันทึกคำร้อง', responsible_user_id=staff_id, due_on=str(date.today() + timedelta(days=7)))
        self.assertEqual(r.status_code, 302)
        issue = RevisionRequest.query.filter_by(assessment_id=a.id).one()
        a = self.assessment(a.id)
        self.assertEqual(self.post(committee, f'/assessments/{a.id}/workflow/confirm', version=a.workflow_version).status_code, 400)  # critical issue open
        self.assertEqual(self.post(committee, f'/assessments/{a.id}/workflow/request-changes', version=a.workflow_version).status_code, 302)
        staff = self.client('buu.staff')
        self.assertIn('ขอหลักฐานเพิ่ม', staff.get('/notifications').get_data(as_text=True))
        upload = staff.post(f'/assessments/{a.id}/evidence', content_type='multipart/form-data',
                            data={'pdf_files': (io.BytesIO(make_pdf(TEXT_B2)), 'appeal_channel.pdf'), 'disclosure_class': 'public', 'personal_data': 'none'})
        self.assertEqual(upload.status_code, 302)
        a = self.assessment(a.id)
        self.assertEqual(self.post(staff, f'/assessments/{a.id}/workflow/resubmit', version=a.workflow_version).status_code, 400)  # response missing
        self.assertEqual(self.post(staff, f'/assessments/{a.id}/issues/{issue.id}/respond', note='แนบประกาศช่องทางขอทบทวนแล้ว').status_code, 302)
        self.assertEqual(self.post(staff, f'/assessments/{a.id}/workflow/resubmit', version=a.workflow_version, note='ฉบับแก้ไข').status_code, 302)
        self.assertIn('ฉบับแก้ไขใหม่', committee.get('/notifications').get_data(as_text=True))
        self.assertIn('หลักฐานใหม่', committee.get('/review-queue').get_data(as_text=True))
        self.start_b()
        new_file = DocumentFile.query.filter_by(check_id=a.check_id, original_filename='appeal_channel.pdf').one()
        issue = self.db.session.get(RevisionRequest, issue.id)
        other = self.client('committee2')
        self.assertEqual(self.post(other, f'/assessments/{a.id}/issues/{issue.id}/close', version=issue.version, note='ปิดโดยคนอื่น', evidence=str(new_file.id)).status_code, 403)
        r = self.post(committee, f'/assessments/{a.id}/issues/{issue.id}/close', version=issue.version, note='มีช่องทางขอทบทวนและบันทึกคำร้องจริง', evidence=str(new_file.id), page='1')
        self.assertEqual(r.status_code, 302)
        a = self.assessment(a.id)
        from models import DomainFinding
        for finding in DomainFinding.query.filter_by(assessment_id=a.id).all():
            if finding.state != 'not_applicable' and (finding.critical or finding.control_id == 'HED-03'):
                self.assertEqual(self.post(committee, f'/assessments/{a.id}/findings/{finding.id}/judge', judgement='sufficient', reason='กรรมการตรวจหลักฐานแล้ว').status_code, 302)
        a = self.assessment(a.id)
        self.assertEqual(self.post(committee, f'/assessments/{a.id}/workflow/confirm', version=a.workflow_version, note='ยืนยัน').status_code, 302)
        a = self.assessment(a.id)
        self.assertEqual(a.workflow_status, 'confirmed')
        revisions = SubmissionRevision.query.filter_by(assessment_id=a.id).order_by(SubmissionRevision.revision_no).all()
        self.assertEqual([r.revision_no for r in revisions], [1, 2])
        import json
        self.assertEqual(len(json.loads(revisions[0].files_json)), 1)
        self.assertEqual([f['filename'] for f in json.loads(revisions[1].diff_json)['added']], ['appeal_channel.pdf'])
        issue = self.db.session.get(RevisionRequest, issue.id)
        closing = json.loads(issue.closing_evidence_json)
        self.assertEqual((closing[0]['file_id'], closing[0]['page']), (new_file.id, 1))
        self.assertEqual(closing[0]['content_hash'], new_file.content_hash)
        actions = [e.action for e in WorkflowEvent.query.filter_by(assessment_id=a.id).order_by(WorkflowEvent.id).all()]
        self.assertEqual(actions, ['submit', 'assign', 'start_review', 'request_changes', 'resubmit', 'start_review', 'close_issue', 'confirm'])
        dash = self.client('ops.coordinator').get(f'/rounds/{a.round_id}/dashboard').get_data(as_text=True)
        self.assertIn('ยืนยันผลแล้ว', dash)
        # Both revisions' files remain readable to the owner after confirmation.
        for f in json.loads(revisions[1].files_json):
            self.assertEqual(self.client('buu.staff').get(f"/check/{a.check_id}/source/{f['file_id']}").status_code, 200)
        # System result and committee result are stored separately.
        hed = DomainFinding.query.filter_by(assessment_id=a.id, control_id='HED-03').one()
        self.assertIsNotNone(hed.proposed_level)
        self.assertEqual(hed.judgement, 'sufficient')

    def test_evidence_is_locked_while_in_review(self):
        from services.pilot_demo import TEXT_B2, make_pdf
        a = self.assessment(self.case_b)
        self.submit_b()
        staff = self.client('buu.staff')
        r = staff.post(f'/assessments/{a.id}/evidence', content_type='multipart/form-data',
                       data={'pdf_files': (io.BytesIO(make_pdf(TEXT_B2)), 'late.pdf'), 'disclosure_class': 'public', 'personal_data': 'none'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/workflow', r.headers['Location'])
        from models import DocumentFile
        self.assertIsNone(DocumentFile.query.filter_by(original_filename='late.pdf').first())


class CriteriaVersionPinning(PilotBase):
    """Changing the criteria later does not change submitted work: it keeps its version and evidence."""

    def test_live_pack_change_does_not_alter_pinned_assessment(self):
        import json
        from models import CriteriaSet, DomainProfile
        a = self.assessment(self.case_b)
        self.submit_b()
        before = json.loads(a.config_snapshot_json)
        profile = self.db.session.get(DomainProfile, 'higher_education')
        pack = json.loads(profile.payload_json)
        pack['controls'] = [c for c in pack['controls'] if c['id'] != 'HED-03']
        pack['pack_version'] = '99.0.0'
        profile.payload_json, profile.pack_version = json.dumps(pack, ensure_ascii=False), '99.0.0'
        self.db.session.add(CriteriaSet(code='MHESI-HED-PILOT', version='2569.2', title='ฉบับใหม่', domain_slug='higher_education', status='published', snapshot_json='{}'))
        self.db.session.commit()
        a = self.assessment(a.id)
        page = self.client('buu.staff').get(f'/assessments/{a.id}/results').get_data(as_text=True)
        self.assertIn('HED-03', page)
        self.assertIn('2569.1', self.client('buu.staff').get(f'/assessments/{a.id}/workflow').get_data(as_text=True))
        self.assertEqual(json.loads(a.config_snapshot_json)['pack_version'], before['pack_version'])
        self.assertEqual(a.criteria_version, '2569.1')
        self.assertEqual(self.client('buu.staff').get(f'/check/{a.check_id}/source/{self.b_file().id}').status_code, 200)

    def test_round_needs_published_criteria_and_demo_approval_is_labelled(self):
        from models import CriteriaSet, Organization
        draft = CriteriaSet(code='X', version='1', title='ร่าง', domain_slug='higher_education', status='draft', snapshot_json='{}', is_demo=True)
        self.db.session.add(draft)
        self.db.session.commit()
        ops = Organization.query.filter_by(code='DEMO-OPS').one()
        coord = self.client('ops.coordinator')
        coord.post('/rounds/new', data={'owner_org_id': ops.id, 'criteria_set_id': draft.id, 'code': 'R-X', 'title': 'x'})
        from models import AssessmentRound
        self.assertIsNone(AssessmentRound.query.filter_by(code='R-X').first())
        page = self.client('criteria.approver').get('/criteria').get_data(as_text=True)
        self.assertIn('DEMO', page)
        self.assertIn('ไม่ใช่การรับรองจาก อว. หรือ สป.อว.', page)

    def test_criteria_approval_needs_a_second_person(self):
        from models import CriteriaSet, OrganizationMembership
        admin = self.client('admin')
        admin.post('/criteria/new', data={'domain_slug': 'ops_mhesi', 'code': 'NEW', 'version': '1', 'title': 'ทดลอง'})
        row = CriteriaSet.query.filter_by(code='NEW').one()
        self.assertTrue(row.snapshot_json and 'common_aidg' in row.snapshot_json)
        admin.post(f'/criteria/{row.id}/submit')
        approver = self.user('criteria.approver')
        # An approver who submitted the set cannot approve it.
        row.submitted_by = approver.id
        self.db.session.commit()
        self.assertEqual(self.client('criteria.approver').post(f'/criteria/{row.id}/approve', data={'note': 'อนุมัติชุดเกณฑ์'}).status_code, 403)
        row.submitted_by = self.user('admin').id
        self.db.session.commit()
        self.assertEqual(self.client('criteria.approver').post(f'/criteria/{row.id}/approve', data={'note': 'อนุมัติชุดเกณฑ์'}).status_code, 302)
        self.assertEqual(self.client('criteria.approver').post(f'/criteria/{row.id}/publish').status_code, 302)
        self.db.session.expire_all()
        self.assertEqual(self.db.session.get(CriteriaSet, row.id).status, 'published')


class ModelGate(PilotBase):
    """Documents without a processing right are blocked on the domain path, the legacy path and every retry."""

    def _restricted_assessment(self):
        from models import DocumentFile
        a = self.assessment(self.case_b)
        f = self.b_file()
        f.disclosure_class, f.personal_data, f.is_redacted = 'restricted', 'unknown', False
        self.db.session.commit()
        return a

    def test_domain_legacy_and_retry_paths_do_not_call_any_model(self):
        a = self._restricted_assessment()
        staff = self.client('buu.staff')
        with patch('services.domain_orchestrator.gemini_enabled', return_value=True), patch('services.domain_orchestrator.local_model_enabled', return_value=True), \
                patch('services.domain_orchestrator.score_with_gemini') as gemini, patch('services.domain_orchestrator.score_with_local_model') as local, \
                patch('app.gemini_enabled', return_value=True), patch('app.local_model_enabled', return_value=True), \
                patch('app.score_with_gemini') as legacy_gemini, patch('app.score_with_local_model') as legacy_local:
            for _ in range(2):  # first run and retry
                self.assertEqual(staff.post(f'/assessments/{a.id}/run', data={'include_core': '1'}).status_code, 302)
                self.assertEqual(staff.post(f'/check/{a.check_id}/run-compliance').status_code, 302)
            gemini.assert_not_called(); local.assert_not_called(); legacy_gemini.assert_not_called(); legacy_local.assert_not_called()
        from models import AuditLog, DocumentCheck
        self.assertGreaterEqual(AuditLog.query.filter_by(action='model_gate_blocked').count(), 4)
        blocked = AuditLog.query.filter_by(action='model_gate_blocked').first()
        self.assertNotIn('Draft AI', blocked.detail)
        self.assertIn('ไม่ส่งเอกสารให้โมเดล', self.assessment(a.id).run_note)

    def test_allowed_public_document_still_reaches_the_configured_provider_only(self):
        a = self.assessment(self.case_b)
        staff = self.client('buu.staff')
        with patch('services.domain_orchestrator.gemini_enabled', return_value=True), patch('services.domain_orchestrator.local_model_enabled', return_value=True), \
                patch('services.domain_orchestrator.score_with_gemini', return_value={'used': True, 'items': []}) as gemini, \
                patch('services.domain_orchestrator.score_with_local_model') as local:
            staff.post(f'/assessments/{a.id}/run')
            gemini.assert_called_once()
            local.assert_not_called()

    def test_round_scope_blocks_unredacted_internal_files_even_for_local_model(self):
        a = self.assessment(self.case_b)
        a.data_classification = 'confidential'
        f = self.b_file()
        f.disclosure_class, f.personal_data, f.is_redacted = 'internal', 'none', False
        self.db.session.commit()
        with patch('services.domain_orchestrator.local_model_enabled', return_value=True), patch('services.domain_orchestrator.score_with_local_model') as local:
            self.client('buu.staff').post(f'/assessments/{a.id}/run')
            local.assert_not_called()

    def test_disabled_rule_means_deny(self):
        from models import ModelProcessingRule
        ModelProcessingRule.query.filter_by(provider='gemini').update({'is_active': False})
        self.db.session.commit()
        a = self.assessment(self.case_b)
        with patch('services.domain_orchestrator.gemini_enabled', return_value=True), patch('services.domain_orchestrator.score_with_gemini') as gemini:
            self.client('buu.staff').post(f'/assessments/{a.id}/run')
            gemini.assert_not_called()

    def test_secret_and_unsafe_files_are_not_stored(self):
        from models import DocumentFile
        from services.pilot_demo import TEXT_B2, make_pdf
        a = self.assessment(self.case_b)
        staff = self.client('buu.staff')
        staff.post(f'/assessments/{a.id}/evidence', content_type='multipart/form-data',
                   data={'pdf_files': (io.BytesIO(make_pdf(TEXT_B2)), 'secret.pdf'), 'disclosure_class': 'secret', 'personal_data': 'none'})
        bad = make_pdf(TEXT_B2).replace(b'%%EOF', b'/JavaScript (app.alert(1))\n%%EOF')
        staff.post(f'/assessments/{a.id}/evidence', content_type='multipart/form-data',
                   data={'pdf_files': (io.BytesIO(bad), 'script.pdf'), 'disclosure_class': 'public', 'personal_data': 'none'})
        staff.post(f'/assessments/{a.id}/evidence', content_type='multipart/form-data',
                   data={'pdf_files': (io.BytesIO(make_pdf(TEXT_B2)), 'unlabelled.pdf')})
        for name in ('secret.pdf', 'script.pdf', 'unlabelled.pdf'):
            self.assertIsNone(DocumentFile.query.filter_by(original_filename=name).first(), name)


class ConcurrentTransitions(PilotBase):
    """Double submits and parallel status changes leave one consistent record and one audit trail."""

    def test_stale_version_is_rejected(self):
        from models import SubmissionRevision, WorkflowEvent
        a = self.assessment(self.case_b)
        version = a.workflow_version
        staff1, staff2 = self.client('buu.staff'), self.client('buu.staff')
        self.assertEqual(self.post(staff1, f'/assessments/{a.id}/workflow/submit', version=version).status_code, 302)
        self.assertEqual(self.post(staff2, f'/assessments/{a.id}/workflow/submit', version=version).status_code, 409)
        self.assertEqual(SubmissionRevision.query.filter_by(assessment_id=a.id).count(), 1)
        self.assertEqual(WorkflowEvent.query.filter_by(assessment_id=a.id, action='submit').count(), 1)

    def test_parallel_threads_produce_one_transition(self):
        from models import DomainAssessment, WorkflowEvent
        self.submit_b()
        self.assign_b()
        a = self.assessment(self.case_b)
        version = a.workflow_version
        results = []
        clients = [self.client('committee1') for _ in range(4)]

        def attempt(client):
            results.append(client.post(f'/assessments/{a.id}/workflow/start-review', data={'version': version}).status_code)
        threads = [threading.Thread(target=attempt, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results).count(302), 1, results)
        self.assertEqual(WorkflowEvent.query.filter_by(assessment_id=a.id, action='start_review').count(), 1)
        self.assertEqual(self.assessment(a.id).workflow_version, version + 1)


class LegacyCompatibility(PilotBase):
    """Work without organization_id keeps the original access rule."""

    def test_legacy_assessment_and_check_keep_old_rules(self):
        from models import DocumentCheck, DocumentFile, DomainAssessment, Template, User
        owner = User(full_name='Legacy', email='legacy@demo.invalid', password_hash='x', role='user', organization=self.assessment(self.case_b).organization_name)
        other = User(full_name='Other', email='other@demo.invalid', password_hash='x', role='user')
        self.db.session.add_all([owner, other])
        self.db.session.flush()
        check = DocumentCheck(user_id=owner.id, template_id=Template.query.first().id, original_filename='old.pdf', stored_filename='old.pdf',
                              selected_standard_ids_json='[]', compliance_results_json='[]')
        self.db.session.add(check)
        self.db.session.flush()
        shutil.copy(next(Path(self.work, 'uploads').glob('*.pdf')), Path(self.work, 'uploads', 'old.pdf'))
        doc = DocumentFile(check_id=check.id, original_filename='old.pdf', stored_filename='old.pdf', page_count=1)
        legacy = DomainAssessment(user_id=owner.id, domain_slug='general', name='Legacy work', organization_name=owner.organization, profile_json='{}', status='draft', current_step=1)
        self.db.session.add_all([doc, legacy])
        self.db.session.commit()
        self.assertIsNone(legacy.organization_id)
        def as_(user):
            c = self.app.test_client()
            with c.session_transaction() as s:
                s.update(user_id=user.id, role=user.role, email=user.email)
            return c
        self.assertEqual(as_(owner).get(f'/assessments/{legacy.id}/step/1').status_code, 200)
        self.assertEqual(as_(owner).get(f'/check/{check.id}/source/{doc.id}').status_code, 200)
        self.assertEqual(as_(other).get(f'/assessments/{legacy.id}/step/1').status_code, 403)
        self.assertEqual(as_(other).get(f'/check/{check.id}/source/{doc.id}').status_code, 302)
        self.assertEqual(self.client('admin').get(f'/check/{check.id}/source/{doc.id}').status_code, 200)
        # Organization members with the same organization name gain nothing.
        self.assertEqual(self.client('buu.staff').get(f'/assessments/{legacy.id}/step/1').status_code, 403)


class Migration(unittest.TestCase):
    """The migration works on a fresh database and on a copy of a pre-pilot database, and can run twice."""

    def _app(self, url):
        with patch.multiple(Config, SQLALCHEMY_DATABASE_URI=url, SQLALCHEMY_ENGINE_OPTIONS={}, THAID_ENABLED=False):
            from app import create_app
            app = create_app()
        app.config.update(TESTING=True, SECRET_KEY='pilot-test-only')
        return app

    def test_existing_database_copy(self):
        from migrate_mhesi_pilot import run
        work = tempfile.mkdtemp()
        path = f'{work}/legacy.db'
        con = sqlite3.connect(path)
        con.executescript((ROOT / 'tests' / 'fixtures' / 'legacy_v16_schema.sql').read_text())
        con.executescript("""
            INSERT INTO users (id, full_name, email, organization, password_hash, role, is_active, auth_provider) VALUES (1,'Old owner','old@example.invalid','มหาวิทยาลัยบูรพา','x','user',1,'local');
            INSERT INTO templates (id, display_order, name, prompt_structure, sections_json, pass_threshold, is_enabled) VALUES (1,1,'AI Governance & Management','','[]',70,1);
            INSERT INTO document_checks (id, user_id, template_id, original_filename, stored_filename, selected_standard_ids_json, data_classification, processing_provider, domain_slug, compliance_score)
                VALUES (1,1,1,'old.pdf','old.pdf','[]','open','gemini','general',55);
            INSERT INTO document_files (id, check_id, original_filename, stored_filename, page_count) VALUES (1,1,'old.pdf','old.pdf',2);
            INSERT INTO domain_assessments (id, user_id, domain_slug, name, organization_name, status, current_step, check_id) VALUES (1,1,'general','Old work','มหาวิทยาลัยบูรพา','completed',7,1);
        """)
        con.commit()
        con.close()
        app = self._app(f'sqlite:///{path}')
        first = run(app)
        self.assertIn('domain_assessments.organization_id', first['columns_added'])
        self.assertIn('document_files.disclosure_class', first['columns_added'])
        self.assertEqual(first['before'], {k: v for k, v in first['after'].items() if k in first['before']})
        self.assertEqual(first['org_scoped_assessments'], 0)
        second = run(app)
        self.assertEqual(second['columns_added'], [])
        con = sqlite3.connect(path)
        self.assertEqual(con.execute('SELECT organization_id, workflow_status, workflow_version FROM domain_assessments').fetchone(), (None, None, 0))
        self.assertEqual(con.execute('SELECT organization_id FROM document_checks').fetchone(), (None,))
        self.assertEqual(con.execute('SELECT disclosure_class FROM document_files').fetchone(), (None,))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM organizations').fetchone(), (0,))
        self.assertGreater(con.execute('SELECT COUNT(*) FROM model_processing_rules').fetchone()[0], 0)
        con.close()
        client = app.test_client()
        with client.session_transaction() as s:
            s.update(user_id=1, role='user', email='old@example.invalid')
        with app.app_context():
            self.assertEqual(client.get('/assessments/1').status_code, 302)  # old owner still reaches the work
            self.assertEqual(client.get('/assessments').status_code, 200)
        shutil.rmtree(work, ignore_errors=True)

    def test_fresh_database(self):
        from migrate_mhesi_pilot import run
        work = tempfile.mkdtemp()
        report = run(self._app(f'sqlite:///{work}/fresh.db'))
        self.assertEqual(report['catalog']['domains'], 8)
        self.assertGreater(report['catalog']['model_rules_added'], 0)
        shutil.rmtree(work, ignore_errors=True)


class CatalogRules(PilotBase):
    def test_curriculum_notice_is_never_basis_for_applicant_screening(self):
        import json
        from services.domain_catalog import read_registry_file, validate_pack_references
        config = json.loads(self.assessment(self.case_b).config_snapshot_json)
        refs = {r['source_id']: r for r in config['references']}
        for source in ('MHESI-AI-CURRICULUM-2568', 'MHESI-SKILLS-2569'):
            if source in refs:
                self.assertEqual(refs[source]['status'], 'not_applicable')
                self.assertIn('คัดกรองผู้สมัคร', refs[source]['reason_th'])
        hed03 = next(c for c in config['controls'] if c['id'] == 'HED-03')
        self.assertFalse({'MHESI-AI-CURRICULUM-2568', 'MHESI-SKILLS-2569'} & set(hed03['references']))
        bad = {'slug': 'x', 'use_cases': [{'id': 'HED.UC.ADMISSION_SCREEN'}], 'controls': [{'id': 'X-1', 'references': ['MHESI-AI-CURRICULUM-2568']}]}
        with self.assertRaises(ValueError):
            validate_pack_references(bad, read_registry_file()['references'])

    def test_new_controls_cover_pilot_topics_without_id_collisions(self):
        from services.domain_catalog import DOMAIN_SLUGS, LAYER_SLUGS, read_pack_file, read_registry_file
        ids = [c['id'] for s in DOMAIN_SLUGS + LAYER_SLUGS for c in read_pack_file(s)['controls']]
        self.assertEqual(len(ids), len(set(ids)))
        registry = {r['source_id']: r for r in read_registry_file()['references']}
        for slug in ('common_aidg', 'ops_mhesi', 'higher_education'):
            for control in read_pack_file(slug)['controls']:
                for key in ('scope_th', 'requirement_type', 'reference_clauses', 'evidence_policy', 'evidence_practice', 'decision_method_th', 'version'):
                    self.assertTrue(control.get(key), (control['id'], key))
                for ref in control['references']:
                    self.assertIn(ref, registry, (control['id'], ref))
        new_refs = [r for r in registry.values() if r['source_id'].startswith(('MHESI-', 'OPS-MHESI-', 'TH-HED-', 'TH-OFFICIAL-SECRET', 'ETDA-GENAI'))]
        self.assertGreaterEqual(len(new_refs), 12)
        self.assertTrue(all(r['verification_status'] == 'pending_verification' for r in new_refs))
        self.assertEqual(registry['MHESI-GOVERNANCE-2569']['supersedes'], ['MHESI-GOVERNANCE-PREV'])
        self.assertTrue(registry['MHESI-GOVERNANCE-PREV']['historical_only'])
        self.assertTrue(registry['MHESI-DISCLOSURE-2565']['enforcement_hold'])


class PagesRender(PilotBase):
    def test_pilot_pages_render_for_every_demo_role(self):
        a = self.assessment(self.case_b)
        pages = ['/rounds', '/notifications', '/ai-registry', f'/assessments/{a.id}/workflow', '/review-queue', '/overview', '/assessments', '/evidence', '/regulations']
        expected = {'buu.staff': {}, 'rpu.coordinator': {f'/assessments/{a.id}/workflow': 403}, 'ops.coordinator': {}, 'mhesi.executive': {},
                    'committee1': {f'/assessments/{a.id}/workflow': 403}, 'admin': {}, 'criteria.approver': {f'/assessments/{a.id}/workflow': 403}}
        for key, exceptions in expected.items():
            client = self.client(key)
            for path in pages:
                status = client.get(path).status_code
                self.assertEqual(status, exceptions.get(path, 200), (key, path))
        for key in ('ops.coordinator', 'mhesi.executive'):
            self.assertEqual(self.client(key).get(f'/rounds/{a.round_id}/dashboard').status_code, 200)
        self.assertEqual(self.client('ops.coordinator').get(f'/rounds/{a.round_id}').status_code, 200)
        self.assertEqual(self.client('admin').get('/integrations').status_code, 200)
        self.assertEqual(self.client('criteria.approver').get('/criteria').status_code, 200)
        self.assertIn('DEMO', self.client('buu.staff').get('/rounds').get_data(as_text=True))
        for step in (2, 3, 4, 5, 6):
            self.assertEqual(self.client('buu.staff').get(f'/assessments/{a.id}/step/{step}').status_code, 200, step)

    def test_dsv_export_is_prepared_not_sent_and_unsigned(self):
        a = self.assessment(self.case_b)
        data = self.client('ops.coordinator').get(f'/rounds/{a.round_id}/export/dsv.json').get_json()
        self.assertEqual(data['delivery'], 'not_sent')
        self.assertEqual(data['integration_status'], 'prepared')
        self.assertTrue(all(i['report_signature'] == 'unsigned' and i['institution_ref_verified'] is False for i in data['items']))

    def test_round_cannot_close_complete_with_open_work(self):
        a = self.assessment(self.case_b)
        coord = self.client('ops.coordinator')
        self.assertEqual(coord.post(f'/rounds/{a.round_id}/close', data={'mode': 'complete'}).status_code, 400)
        self.assertEqual(coord.post(f'/rounds/{a.round_id}/close', data={'mode': 'incomplete', 'reason': 'ปิดรอบสาธิตก่อนกำหนด'}).status_code, 302)


if __name__ == '__main__':
    unittest.main()
