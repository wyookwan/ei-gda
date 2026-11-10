"""Synthetic DEMO data for the MHESI pilot. Fictional documents and @demo.invalid accounts only.

Nothing here is an endorsement by MHESI or OPS-MHESI. Every organization, criteria set, round and AI
system created here carries is_demo=True, and pages show a DEMO label for them.

Case A  OPS-MHESI uses an AI assistant that answers questions from published documents (seeded as submitted).
Case B  A university submits a draft AI/Data Governance policy that covers AI-assisted applicant screening.
        Seeded ready to submit; run_case_b() walks the full review loop (used by tests and --complete-case-b).
"""
import io
import os
from datetime import date, timedelta
from pathlib import Path

import fitz
from flask import session
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from extensions import db
from utils import json_dumps

DEMO_DOMAIN = 'demo.invalid'
THAI_FONTS = [os.getenv('DEMO_THAI_FONT', ''), '/System/Library/Fonts/Supplemental/Ayuthaya.ttf', '/System/Library/Fonts/Supplemental/Sathu.ttf',
              '/usr/share/fonts/truetype/tlwg/Garuda.ttf', '/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf',
              '/usr/share/fonts/opentype/noto/NotoSansThai-Regular.ttf']

USERS = (  # key, full name, system role
    ('admin', 'ผู้ดูแลระบบ (สาธิต)', 'admin'),
    ('ops.coordinator', 'ผู้ประสานรอบ สป.อว. (สาธิต)', 'user'),
    ('ops.staff', 'เจ้าหน้าที่ สป.อว. (สาธิต)', 'user'),
    ('mhesi.executive', 'ผู้บริหาร อว. (สาธิต)', 'user'),
    ('criteria.approver', 'ผู้อนุมัติชุดเกณฑ์ (สาธิต)', 'user'),
    ('buu.coordinator', 'ผู้ประสานงาน ม.บูรพา (สาธิต)', 'user'),
    ('buu.staff', 'เจ้าหน้าที่ ม.บูรพา (สาธิต)', 'user'),
    ('rpu.coordinator', 'ผู้ประสานงาน ม.ราชพฤกษ์ (สมมติ)', 'user'),
    ('committee1', 'กรรมการ คนที่ 1 (สาธิต)', 'committee'),
    ('committee2', 'กรรมการ คนที่ 2 (สาธิต)', 'committee'),
)
MEMBERSHIPS = (  # user key, org code, role, can_read_source
    ('ops.coordinator', 'DEMO-OPS', 'round_coordinator', False),
    ('ops.staff', 'DEMO-OPS', 'org_coordinator', False),
    ('mhesi.executive', 'DEMO-MHESI', 'executive', False),
    ('criteria.approver', 'DEMO-OPS', 'criteria_approver', False),
    ('buu.coordinator', 'DEMO-BUU', 'org_coordinator', False),
    ('buu.staff', 'DEMO-BUU', 'org_staff', False),
    ('rpu.coordinator', 'DEMO-RPU', 'org_coordinator', False),
)

TEXT_A = [
    ('คู่มือผู้ช่วยตอบคำถามจากเอกสารเผยแพร่ สำนักงานปลัดกระทรวง อว. (เอกสารสมมติสำหรับสาธิต)\n'
     'Source scope: the assistant answers from published documents only (เอกสารเผยแพร่) with citations to each source.\n'
     'Answer accuracy test: 200 test questions, citation check passed 96 percent before launch.'),
    ('Data classification: only public documents are indexed; model processing rule forbids classified information and official secret documents.\n'
     'Classified screening log: every file is checked before indexing. Pre-model screening and redaction log are kept for 1 year.\n'
     'Access log and audit trail are reviewed monthly. Incident response procedure applies.'),
    ('AI register entry: OPS public Q&A assistant, owner Digital Office. Risk assessment: low impact, information only.\n'
     'OPS data governance policy applies; data governance meeting minutes approve the source list. Cybersecurity framework 2569 controls apply.'),
]
TEXT_B1 = [
    ('ร่างนโยบายธรรมาภิบาล AI และข้อมูล มหาวิทยาลัย (เอกสารสมมติสำหรับสาธิต) / Draft AI and data governance policy.\n'
     'AI policy: the university council approves AI risk criteria. Data governance policy names a data steward and data owner for each dataset.\n'
     'Good governance, internal control and conflict of interest rules apply to every AI project.'),
    ('Admission criteria: the AI system performs applicant screening to rank documents. Final decisions are made by the admission committee.\n'
     'Human review procedure: staff check every AI ranking before results are released.\n'
     'Privacy notice and lawful basis for applicant data are published. Record of processing (RoPA) is maintained. Fairness testing across applicant groups is planned.'),
    ('Dataset register and data catalog list the applicant datasets. Data classification: only redacted application summaries are sent to the model.\n'
     'AI register and AI inventory include the screening system; risk assessment rated high impact.\n'
     'Access log and audit trail retained for two years. Corrective action procedure assigns owners and due dates.'),
]
TEXT_B2 = [
    ('ประกาศช่องทางขอทบทวนผลการคัดกรองผู้สมัคร (เอกสารสมมติสำหรับสาธิต) / Applicant appeal channel.\n'
     'Any applicant may request a review of the result within 15 days through the admissions office or the online form.\n'
     'Applicant appeal requests are reviewed by a committee that did not take part in the original screening.'),
    ('Appeal log 2569 (synthetic): 12 review request log entries, 3 results changed after human review.\n'
     'Review request log is reported to the university council every semester. Right to request review is stated in the admission notice.'),
]


def _font():
    return next((f for f in THAI_FONTS if f and Path(f).exists()), None)


def make_pdf(pages):
    """Synthetic PDF. Thai text is embedded when a Thai font exists; otherwise the English lines still carry the keywords."""
    font = _font()
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        rect = fitz.Rect(48, 56, 548, 790)
        if font:
            page.insert_font(fontname='thai', fontfile=font)
            page.insert_textbox(rect, text, fontsize=11, fontname='thai')
        else:
            page.insert_textbox(rect, ''.join(ch if ord(ch) < 0x0E00 or ord(ch) > 0x0E7F else '' for ch in text), fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _as_user(user):
    session.clear()
    session.update(user_id=user.id, role=user.role, email=user.email, full_name=user.full_name)
    from services import access_policy as ap
    from flask import g
    g.pop('_memberships', None)
    rows = ap.memberships(user.id)
    session['org_id'] = rows[0].organization_id if rows else None


def seed(app, password, upload_folder=None):
    """Create the DEMO organizations, accounts, criteria, rounds, AI register and cases A and B. Returns a summary dict."""
    from models import (AISystem, AssessmentRound, CriteriaSet, Organization, OrganizationMembership, RoundParticipation, Standard,
                        StandardItem, Template, User)
    from seed_data import SEED_DATA
    from services.domain_catalog import CORE_SUITES, content_hash, sync_catalog
    with app.app_context():
        if Organization.query.filter_by(code='DEMO-OPS').first():
            return {'status': 'already_seeded'}
        if not Template.query.first():
            for index, (code, name) in enumerate(CORE_SUITES, 1):
                db.session.add(Template(name=name, suite_code=code, description='Core Test Suite', prompt_structure='', sections_json='[]',
                                        applicable_framework_codes_json='[]', display_order=index))
            for source in SEED_DATA['standards']:
                row = Standard(**{k: source[k] for k in ('code', 'name', 'description', 'source_type', 'jurisdiction', 'publisher', 'reference_url', 'published_year', 'status') if k in source})
                db.session.add(row)
                db.session.flush()
                for n, (code, category, title, keywords) in enumerate(source['items'], 1):
                    db.session.add(StandardItem(standard_id=row.id, item_code=code, category=category, title=title, keywords_json=json_dumps(keywords), order_index=n))
            db.session.commit()
            sync_catalog(db.session)
            db.session.commit()
        mhesi = Organization(code='DEMO-MHESI', name='กระทรวงการอุดมศึกษา วิทยาศาสตร์ วิจัยและนวัตกรรม (สาธิต)', org_type='ministry', is_demo=True)
        db.session.add(mhesi)
        db.session.flush()
        orgs = {'DEMO-MHESI': mhesi}
        for code, name, kind, ref in (('DEMO-OPS', 'สำนักงานปลัดกระทรวง อว. (สาธิต)', 'ministry_office', None),
                                      ('DEMO-BUU', 'มหาวิทยาลัยบูรพา (สถาบันตัวอย่าง ข้อมูลสมมติ)', 'university', 'DEMO-REF-BUU'),
                                      ('DEMO-RPU', 'มหาวิทยาลัยราชพฤกษ์ (สมมติ)', 'university', 'DEMO-REF-RPU')):
            orgs[code] = Organization(code=code, name=name, org_type=kind, parent_id=mhesi.id if kind == 'ministry_office' else None, external_ref=ref, is_demo=True)
            db.session.add(orgs[code])
        users = {}
        for key, name, role in USERS:
            users[key] = User(full_name=name, email=f'{key}@{DEMO_DOMAIN}', password_hash=generate_password_hash(password), role=role,
                              organization='DEMO', auth_provider='local', is_active=True)
            db.session.add(users[key])
        db.session.flush()
        for key, org, role, read_source in MEMBERSHIPS:
            db.session.add(OrganizationMembership(user_id=users[key].id, organization_id=orgs[org].id, role=role, can_read_source=read_source,
                                                  granted_by=users['admin'].id))
        from pilot_routes import _bundle
        criteria = {}
        for code, slug, title in (('MHESI-HED-PILOT', 'higher_education', 'ชุดเกณฑ์นำร่องสถาบันอุดมศึกษา'),
                                  ('OPS-MHESI-PILOT', 'ops_mhesi', 'ชุดเกณฑ์นำร่องงานภายใน สป.อว.')):
            bundle = _bundle(slug)
            criteria[slug] = CriteriaSet(code=code, version='2569.1', title=title, domain_slug=slug, status='published', is_demo=True,
                                         snapshot_json=json_dumps(bundle), content_hash=content_hash(bundle), created_by=users['admin'].id,
                                         submitted_by=users['admin'].id, approved_by=users['criteria.approver'].id, reviewed_by=users['criteria.approver'].id,
                                         published_by=users['criteria.approver'].id, note='[approve] อนุมัติในสภาพแวดล้อมสาธิต ไม่ใช่การรับรองจาก อว. หรือ สป.อว.')
            db.session.add(criteria[slug])
        db.session.flush()
        today = date.today()
        hed_round = AssessmentRound(code='DEMO-HED-2569-R1', title='รอบนำร่องธรรมาภิบาล AI สถาบันอุดมศึกษา 2569 (สาธิต)', owner_org_id=orgs['DEMO-OPS'].id,
                                    scope_th='นโยบาย AI และ Data Governance ระดับสถาบัน และกรณี AI ช่วยคัดกรองผู้สมัคร', opens_on=today - timedelta(days=7),
                                    closes_on=today + timedelta(days=45), criteria_set_id=criteria['higher_education'].id, status='open', is_demo=True,
                                    created_by=users['ops.coordinator'].id)
        ops_round = AssessmentRound(code='DEMO-OPS-2569-R1', title='รอบนำร่องงานภายใน สป.อว. 2569 (สาธิต)', owner_org_id=orgs['DEMO-OPS'].id,
                                    scope_th='ผู้ช่วยตอบคำถามจากเอกสารเผยแพร่', opens_on=today - timedelta(days=7), closes_on=today + timedelta(days=30),
                                    criteria_set_id=criteria['ops_mhesi'].id, status='open', is_demo=True, created_by=users['ops.coordinator'].id)
        db.session.add_all([hed_round, ops_round])
        db.session.flush()
        db.session.add_all([
            RoundParticipation(round_id=hed_round.id, organization_id=orgs['DEMO-BUU'].id, coordinator_user_id=users['buu.coordinator'].id, status='accepted', due_on=today + timedelta(days=30), invited_by=users['ops.coordinator'].id),
            RoundParticipation(round_id=hed_round.id, organization_id=orgs['DEMO-RPU'].id, coordinator_user_id=users['rpu.coordinator'].id, status='accepted', due_on=today - timedelta(days=2), invited_by=users['ops.coordinator'].id),
            RoundParticipation(round_id=ops_round.id, organization_id=orgs['DEMO-OPS'].id, coordinator_user_id=users['ops.staff'].id, status='accepted', due_on=today + timedelta(days=20), invited_by=users['ops.coordinator'].id)])
        db.session.add_all([
            AISystem(organization_id=orgs['DEMO-OPS'].id, name='ผู้ช่วยตอบคำถามจากเอกสารเผยแพร่', owner_name='ศูนย์เทคโนโลยีดิจิทัล สป.อว. (สาธิต)', purpose='ตอบคำถามประชาชนจากเอกสารที่เผยแพร่แล้ว พร้อมอ้างอิงแหล่งที่มา',
                     affected_persons='ประชาชนผู้สอบถาม', provider='Google (Gemini)', model_name='ตามที่ตั้งค่า', data_types='เอกสารเผยแพร่เท่านั้น', risk_level='low',
                     review_cycle_months=12, next_review_on=today + timedelta(days=180), is_demo=True, created_by=users['ops.staff'].id),
            AISystem(organization_id=orgs['DEMO-BUU'].id, name='ระบบช่วยคัดกรองใบสมัคร', owner_name='สำนักงานรับเข้าศึกษา (สาธิต)', purpose='จัดลำดับเอกสารผู้สมัครให้คณะกรรมการพิจารณา',
                     affected_persons='ผู้สมัครเข้าศึกษา', provider='ผู้ให้บริการภายนอก (สมมติ)', model_name='-', data_types='ข้อมูลผู้สมัครที่ปกปิดแล้ว', risk_level='high',
                     review_cycle_months=6, next_review_on=today + timedelta(days=60), is_demo=True, created_by=users['buu.staff'].id),
            AISystem(organization_id=orgs['DEMO-RPU'].id, name='AI ติวเตอร์รายวิชาพื้นฐาน', owner_name='สำนักวิชาการ (สมมติ)', purpose='ช่วยตอบคำถามบทเรียน',
                     affected_persons='นักศึกษา', provider='-', model_name='-', data_types='เนื้อหาการเรียนการสอน', risk_level='medium', review_cycle_months=12,
                     next_review_on=today - timedelta(days=5), is_demo=True, created_by=users['rpu.coordinator'].id)])
        db.session.commit()
        ids = {k: u.id for k, u in users.items()}
        round_ids = {'hed': hed_round.id, 'ops': ops_round.id}
    with app.test_request_context('/'):
        a_id = _prepare_case(app, ids['ops.staff'], round_ids['ops'], 'ops_mhesi', 'ผู้ช่วยตอบคำถามจากเอกสารเผยแพร่ สป.อว.',
                             {'org_type': 'OPS.ORG.OFFICE', 'functional_area': 'OPS.FA.PUBLIC_INFO', 'use_case': 'OPS.UC.PUBLIC_QA', 'data_categories': ['OPS.DATA.PUBLISHED'],
                              'decision_impact': 'information', 'purpose': 'ตอบคำถามจากเอกสารเผยแพร่', 'affected_persons': 'ประชาชน',
                              'flags': {'is_public_agency': True, 'shares_data_across_orgs': False, 'uses_external_vendor': True}},
                             [('ops_public_qa_manual_demo.pdf', TEXT_A)], submit=True)
        b_id = _prepare_case(app, ids['buu.staff'], round_ids['hed'], 'higher_education', 'นโยบาย AI/Data Governance และ AI ช่วยคัดกรองผู้สมัคร',
                             {'org_type': 'HED.ORG.PUBLIC', 'functional_area': 'HED.FA.ADMISSION', 'use_case': 'HED.UC.ADMISSION_SCREEN', 'data_categories': ['HED.DATA.APPLICANT'],
                              'decision_impact': 'significant', 'purpose': 'ช่วยจัดลำดับเอกสารผู้สมัครให้คณะกรรมการ', 'affected_persons': 'ผู้สมัครเข้าศึกษา',
                              'flags': {'is_public_agency': True, 'shares_data_across_orgs': False, 'uses_external_vendor': True, 'uses_tuc_esign': False}},
                             [('buu_ai_data_governance_policy_draft_demo.pdf', TEXT_B1)], submit=False)
    return {'status': 'seeded', 'case_a': a_id, 'case_b': b_id, 'users': [f'{k}@{DEMO_DOMAIN}' for k, _, _ in USERS], 'rounds': round_ids}


def attach(assessment, filename, pages, disclosure='public', personal='none', redacted=False):
    """Attach a synthetic PDF through the same code path as the upload route."""
    from governance_routes import _attach, _save_pdf, _sha256
    from services.domain_orchestrator import ensure_check
    storage = FileStorage(stream=io.BytesIO(make_pdf(pages)), filename=filename, content_type='application/pdf')
    stored, path, extracted = _save_pdf(storage)
    check = ensure_check(assessment)
    row = _attach(check, filename, stored, extracted, _sha256(path), {'disclosure_class': disclosure, 'personal_data': personal, 'is_redacted': redacted})
    db.session.flush()
    return row


def _prepare_case(app, user_id, round_id, slug, name, profile, files, submit):
    from models import AssessmentRound, DomainAssessment, User
    from services import workflow as wf
    from services.domain_orchestrator import freeze, run_assessment
    user = db.session.get(User, user_id)
    _as_user(user)
    rnd = db.session.get(AssessmentRound, round_id)
    a = DomainAssessment(user_id=user.id, domain_slug=slug, name=name, organization_name='', profile_json=json_dumps(profile),
                         status='draft', current_step=4, organization_id=session['org_id'], round_id=round_id, criteria_set_id=rnd.criteria_set_id,
                         criteria_version=rnd.criteria_set.version, created_by_id=user.id, responsible_user_id=user.id, workflow_status='draft',
                         data_classification='open')
    from models import Organization
    a.organization_name = db.session.get(Organization, session['org_id']).name
    db.session.add(a)
    db.session.flush()
    freeze(a)
    for filename, pages in files:
        attach(a, filename, pages)
    run_assessment(a)
    db.session.commit()
    if submit:
        wf.submit(a, a.workflow_version, 'ส่งงานสาธิต')
    return a.id


def run_case_b(app, assessment_id):
    """Walk case B through the full loop as each role would. Returns the issue id that the committee closed."""
    from models import DomainAssessment, DomainFinding, RevisionRequest, User
    from services import workflow as wf
    by_email = lambda key: User.query.filter_by(email=f'{key}@{DEMO_DOMAIN}').first()
    with app.test_request_context('/'):
        a = db.session.get(DomainAssessment, assessment_id)
        _as_user(by_email('buu.staff'))
        wf.submit(a, a.workflow_version, 'ส่งร่างนโยบาย')
        _as_user(by_email('ops.coordinator'))
        wf.assign_reviewer(a, by_email('committee1').id, a.workflow_version)
        committee = by_email('committee1')
        _as_user(committee)
        wf.start_review(a, a.workflow_version)
        issue = wf.raise_issue(a, 'HED-03', 'critical', 'ยังไม่พบช่องทางให้ผู้สมัครขอทบทวนผลการคัดกรอง',
                               'ประกาศช่องทางขอทบทวนผลและบันทึกการพิจารณาคำร้อง', by_email('buu.staff').id, date.today() + timedelta(days=14))
        wf.request_changes(a, a.workflow_version, 'ขอหลักฐานช่องทางขอทบทวน')
        _as_user(by_email('buu.staff'))
        new_file = attach(a, 'buu_applicant_review_channel_demo.pdf', TEXT_B2)
        db.session.commit()
        wf.save_response(a, issue, 'แนบประกาศช่องทางขอทบทวนผลและบันทึกคำร้องปี 2569 แล้ว')
        wf.resubmit(a, a.workflow_version, 'เพิ่มหลักฐานช่องทางขอทบทวน')
        _as_user(committee)
        wf.start_review(a, a.workflow_version)
        db.session.refresh(issue)
        wf.close_issue(a, issue, issue.version, 'ประกาศระบุช่องทางและกรอบเวลา และมีบันทึกคำร้องจริง', [(new_file.id, 1)])
        for finding in DomainFinding.query.filter_by(assessment_id=a.id).all():
            if finding.state != 'not_applicable' and (finding.critical or finding.control_id == 'HED-03'):
                wf.judge_control(a, finding, 'sufficient' if finding.control_id == 'HED-03' else 'more_evidence',
                                 'กรรมการตรวจหลักฐานสาธิตแล้ว' if finding.control_id == 'HED-03' else 'ใช้ได้ในรอบนำร่อง ควรเพิ่มหลักฐานการปฏิบัติในรอบถัดไป')
        wf.confirm(a, a.workflow_version, 'ยืนยันผลรอบนำร่อง (สาธิต)')
        return issue.id
