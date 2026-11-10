"""Submission, review and revision workflow for organization-scoped assessments.

Workflow status (assessment) and issue status (RevisionRequest) are separate on purpose:

    draft -> submitted -> assigned -> in_review -> changes_requested -> resubmitted -> re_review -> confirmed
                                          \\______________________________________________________/^

Every transition runs one conditional UPDATE guarded by (status, workflow_version). Two screens that
act on the same version cannot both succeed; the loser gets WorkflowConflict and nothing is written.
"""
import hashlib
from datetime import date, datetime

from flask import session
from sqlalchemy import update

from extensions import db
from services import access_policy as ap
from utils import json_dumps, json_loads

STATUS_LABELS = {None: 'ยังไม่เข้าวงจรส่งงาน', 'draft': 'ฉบับร่าง', 'submitted': 'ส่งครั้งแรกแล้ว', 'assigned': 'มอบหมายกรรมการแล้ว',
                 'in_review': 'อยู่ระหว่างทบทวน', 'changes_requested': 'ขอหลักฐานเพิ่ม', 'resubmitted': 'ส่งฉบับแก้ไขแล้ว',
                 're_review': 'ทบทวนซ้ำ', 'confirmed': 'ยืนยันผลแล้ว'}
ISSUE_LABELS = {'open': 'เปิดอยู่', 'responded': 'ตอบกลับแล้ว รอผู้ตรวจ', 'closed': 'ปิดแล้ว'}
SEVERITY_LABELS = {'critical': 'สำคัญมาก', 'major': 'สำคัญ', 'minor': 'เล็กน้อย'}
JUDGEMENTS = {'sufficient': 'หลักฐานเพียงพอ', 'more_evidence': 'ขอหลักฐานเพิ่ม', 'not_met': 'ไม่เข้าเงื่อนไข'}
EVENT_LABELS = {'submit': 'ส่งงานครั้งแรก', 'assign': 'มอบหมายกรรมการ', 'revoke_reviewer': 'ถอนสิทธิ์กรรมการ', 'start_review': 'เริ่มทบทวน',
                'request_changes': 'ขอหลักฐานเพิ่ม', 'resubmit': 'ส่งฉบับแก้ไข', 'close_issue': 'ปิดประเด็น', 'reopen_issue': 'เปิดประเด็นอีกครั้ง',
                'confirm': 'ยืนยันผล'}
EDITABLE_STATES = (None, 'draft', 'changes_requested')
REVIEWING_STATES = ('in_review', 're_review')
BLOCKING_SEVERITIES = ('critical',)
MIN_REASON = 8


class WorkflowError(Exception):
    status_code = 400


class WorkflowForbidden(WorkflowError):
    status_code = 403


class WorkflowConflict(WorkflowError):
    status_code = 409


def _uid():
    return session.get('user_id')


def _need(assessment, action):
    if action not in ap.assessment_permissions(assessment):
        raise WorkflowForbidden('ไม่มีสิทธิ์ดำเนินการนี้')


def in_workflow(assessment):
    return assessment.organization_id is not None or assessment.workflow_status is not None


def org_can_modify(assessment):
    """Evidence and wizard edits are allowed only while the organization holds the work."""
    return assessment.workflow_status in EDITABLE_STATES


def _audit(action, assessment_id, detail):
    from models import AuditLog
    db.session.add(AuditLog(user_id=_uid(), actor_email=session.get('email'), action=action, target_type='domain_assessment',
                            target_id=str(assessment_id), detail=(detail or '')[:15000]))


def _event(assessment, action, from_status, to_status, reason=None, revision_no=None):
    from models import WorkflowEvent
    db.session.add(WorkflowEvent(assessment_id=assessment.id, action=action, from_status=from_status, to_status=to_status, actor_id=_uid(),
                                 actor_email=session.get('email'), reason=(reason or '')[:4000] or None, revision_no=revision_no))
    _audit('workflow_' + action, assessment.id, f'{from_status} -> {to_status}' + (f'; {reason}' if reason else ''))


def notify(user_ids, kind, title, link):
    from models import Notification
    for user_id in sorted({u for u in user_ids if u}):
        db.session.add(Notification(user_id=user_id, kind=kind, title=title[:255], link=link))


def _move(assessment, expected_version, allowed_from, to_status, extra=None):
    """Atomic compare-and-set on (status, version). Raises WorkflowConflict if another screen won."""
    from models import DomainAssessment
    current = assessment.workflow_status or 'draft'
    if expected_version is None or int(expected_version) != (assessment.workflow_version or 0):
        raise WorkflowConflict('ข้อมูลถูกเปลี่ยนจากหน้าจออื่นแล้ว กรุณาโหลดหน้าใหม่ก่อนดำเนินการ')
    if current not in allowed_from:
        raise WorkflowError(f'ทำรายการนี้ไม่ได้ในสถานะ "{STATUS_LABELS.get(current, current)}"')
    values = {'workflow_status': to_status, 'workflow_version': DomainAssessment.workflow_version + 1, 'updated_at': datetime.utcnow()}
    values.update(extra or {})
    status_clause = DomainAssessment.workflow_status.is_(None) if assessment.workflow_status is None else DomainAssessment.workflow_status == assessment.workflow_status
    result = db.session.execute(update(DomainAssessment).where(DomainAssessment.id == assessment.id, status_clause,
                                                                 DomainAssessment.workflow_version == int(expected_version)).values(**values)
                                .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.session.rollback()
        raise WorkflowConflict('ข้อมูลถูกเปลี่ยนจากหน้าจออื่นแล้ว กรุณาโหลดหน้าใหม่ก่อนดำเนินการ')
    db.session.expire(assessment, ['workflow_status', 'workflow_version', 'updated_at'] + list((extra or {}).keys()))
    return current


def _file_snapshot(assessment):
    from models import DocumentFile
    if not assessment.check_id:
        return []
    return [{'file_id': f.id, 'filename': f.original_filename, 'content_hash': f.content_hash, 'page_count': f.page_count,
             'stored_filename': f.stored_filename, 'disclosure_class': f.disclosure_class, 'is_redacted': bool(f.is_redacted)}
            for f in DocumentFile.query.filter_by(check_id=assessment.check_id).order_by(DocumentFile.id).all()]


def _diff(previous, current):
    key = lambda f: f.get('content_hash') or f"id:{f['file_id']}"
    before, after = {key(f): f for f in previous}, {key(f): f for f in current}
    return {'added': [after[k] for k in after if k not in before], 'removed': [before[k] for k in before if k not in after],
            'unchanged': [after[k] for k in after if k in before]}


def revisions(assessment):
    from models import SubmissionRevision
    return SubmissionRevision.query.filter_by(assessment_id=assessment.id).order_by(SubmissionRevision.revision_no).all()


def _new_revision(assessment, note, responses=None):
    from models import SubmissionRevision
    previous = revisions(assessment)
    files = _file_snapshot(assessment)
    if not files:
        raise WorkflowError('ต้องแนบหลักฐานอย่างน้อย 1 ไฟล์ก่อนส่ง')
    number = (previous[-1].revision_no if previous else 0) + 1
    diff = _diff(json_loads(previous[-1].files_json, default=[]) if previous else [], files)
    if previous and not diff['added'] and not diff['removed'] and not responses:
        raise WorkflowError('ฉบับแก้ไขต้องมีหลักฐานใหม่หรือคำชี้แจงต่อประเด็นที่ขอ')
    row = SubmissionRevision(assessment_id=assessment.id, revision_no=number, submitted_by=_uid(), criteria_set_id=assessment.criteria_set_id,
                             criteria_version=assessment.criteria_version, snapshot_hash=assessment.snapshot_hash, files_json=json_dumps(files),
                             diff_json=json_dumps(diff), responses_json=json_dumps(responses or {}), system_summary_json=assessment.summary_json, note=(note or '')[:4000])
    db.session.add(row)
    return row


def _refresh_system_result(assessment):
    """Re-score from the frozen configuration so the system result matches the evidence being submitted."""
    from services.domain_orchestrator import run_assessment
    run_assessment(assessment)


def _round_coordinators(assessment):
    from models import AssessmentRound, OrganizationMembership
    if not assessment.round_id:
        return []
    rnd = db.session.get(AssessmentRound, assessment.round_id)
    if rnd is None:
        return []
    return [m.user_id for m in OrganizationMembership.query.filter_by(organization_id=rnd.owner_org_id, role='round_coordinator', is_active=True).all()]


def _org_editors(assessment):
    from models import OrganizationMembership
    if not assessment.organization_id:
        return [assessment.user_id]
    return [m.user_id for m in OrganizationMembership.query.filter(OrganizationMembership.organization_id == assessment.organization_id,
                                                                   OrganizationMembership.role.in_(ap.EDITOR_ROLES), OrganizationMembership.is_active.is_(True)).all()]


def _active_reviewers(assessment):
    from models import CommitteeAssignment
    if not assessment.check_id:
        return []
    return [a.committee_user_id for a in CommitteeAssignment.query.filter_by(check_id=assessment.check_id, is_active=True).all()]


def _link(assessment):
    return f'/assessments/{assessment.id}/workflow'


# ---------------------------------------------------------------- transitions
def submit(assessment, expected_version, note=''):
    _need(assessment, ap.EDIT)
    if not assessment.config_snapshot_json:
        raise WorkflowError('ต้องยืนยันขอบเขต Control ก่อนส่ง')
    if not assessment.data_classification:
        raise WorkflowError('ต้องเลือกระดับเอกสารก่อนส่ง')
    _move(assessment, expected_version, ('draft',), 'submitted', {'submitted_at': datetime.utcnow()})
    _refresh_system_result(assessment)
    row = _new_revision(assessment, note)
    _event(assessment, 'submit', 'draft', 'submitted', note, row.revision_no)
    notify(_round_coordinators(assessment), 'submitted', f'มีงานส่งใหม่: {assessment.name}', _link(assessment))
    db.session.commit()
    return row


def assign_reviewer(assessment, committee_user_id, expected_version=None):
    from models import CommitteeAssignment, User
    _need(assessment, ap.ASSIGN)
    reviewer = db.session.get(User, committee_user_id or 0)
    if reviewer is None or reviewer.role != 'committee' or not reviewer.is_active:
        raise WorkflowError('ผู้ใช้นี้ไม่ใช่กรรมการที่ใช้งานอยู่')
    if not assessment.check_id:
        raise WorkflowError('งานนี้ยังไม่มีชุดหลักฐาน')
    status = assessment.workflow_status
    if status in (None, 'draft', 'confirmed'):
        raise WorkflowError('มอบหมายกรรมการได้หลังส่งงานและก่อนยืนยันผลเท่านั้น')
    row = CommitteeAssignment.query.filter_by(check_id=assessment.check_id, committee_user_id=reviewer.id).first()
    if row is None:
        row = CommitteeAssignment(check_id=assessment.check_id, committee_user_id=reviewer.id)
        db.session.add(row)
    row.is_active, row.assigned_by, row.revoked_at, row.revoked_by, row.revoke_reason = True, _uid(), None, None, None
    if status == 'submitted':
        _move(assessment, expected_version if expected_version is not None else assessment.workflow_version, ('submitted',), 'assigned')
        _event(assessment, 'assign', 'submitted', 'assigned', f'กรรมการ {reviewer.email}')
    else:
        _event(assessment, 'assign', status, status, f'กรรมการ {reviewer.email}')
    _audit('permission_review_grant', assessment.id, f'committee={reviewer.email}')
    notify([reviewer.id], 'assigned', f'ได้รับมอบหมายให้ทบทวน: {assessment.name}', _link(assessment))
    db.session.commit()
    return row


def revoke_reviewer(assessment, committee_user_id, reason):
    from models import CommitteeAssignment
    _need(assessment, ap.ASSIGN)
    if len((reason or '').strip()) < MIN_REASON:
        raise WorkflowError('กรุณาระบุเหตุผลการถอนสิทธิ์อย่างน้อย 8 ตัวอักษร')
    row = CommitteeAssignment.query.filter_by(check_id=assessment.check_id, committee_user_id=committee_user_id, is_active=True).first()
    if row is None:
        raise WorkflowError('ไม่พบการมอบหมายที่ใช้งานอยู่')
    row.is_active, row.revoked_by, row.revoked_at, row.revoke_reason = False, _uid(), datetime.utcnow(), reason.strip()[:500]
    _event(assessment, 'revoke_reviewer', assessment.workflow_status, assessment.workflow_status, reason)
    _audit('permission_review_revoke', assessment.id, f'committee_user={committee_user_id}; {reason}')
    notify([committee_user_id], 'revoked', f'สิ้นสุดสิทธิ์ทบทวน: {assessment.name}', '/review-queue')
    db.session.commit()


def start_review(assessment, expected_version):
    _need(assessment, ap.REVIEW)
    current = assessment.workflow_status
    target = 're_review' if current == 'resubmitted' else 'in_review'
    _move(assessment, expected_version, ('assigned', 'resubmitted'), target)
    _event(assessment, 'start_review', current, target)
    db.session.commit()


def raise_issue(assessment, control_id, severity, reason, evidence_required, responsible_user_id, due_on):
    from models import RevisionRequest
    from services.domain_orchestrator import current_config
    _need(assessment, ap.REVIEW)
    if assessment.workflow_status not in REVIEWING_STATES:
        raise WorkflowError('เปิดประเด็นได้ระหว่างการทบทวนเท่านั้น')
    controls = {c['id'] for c in current_config(assessment)['controls'] if c['final_status'] != 'not_applicable'}
    if control_id not in controls:
        raise WorkflowError('Control ไม่อยู่ในขอบเขตของงานนี้')
    if severity not in SEVERITY_LABELS:
        raise WorkflowError('ระดับความสำคัญไม่ถูกต้อง')
    if len((reason or '').strip()) < MIN_REASON or len((evidence_required or '').strip()) < MIN_REASON:
        raise WorkflowError('กรุณาระบุเหตุผลและหลักฐานที่ต้องการ อย่างน้อย 8 ตัวอักษร')
    if responsible_user_id not in _org_editors(assessment):
        raise WorkflowError('ผู้รับผิดชอบต้องเป็นเจ้าหน้าที่ของหน่วยงานเจ้าของงาน')
    last = revisions(assessment)
    row = RevisionRequest(assessment_id=assessment.id, control_id=control_id, severity=severity, reason=reason.strip()[:4000],
                          evidence_required=evidence_required.strip()[:4000], responsible_user_id=responsible_user_id, due_on=due_on,
                          raised_by=_uid(), verifier_user_id=_uid(), status='open', raised_in_revision=last[-1].revision_no if last else None)
    db.session.add(row)
    db.session.flush()
    _audit('issue_raise', assessment.id, f'issue={row.id}; control={control_id}; severity={severity}')
    db.session.commit()
    return row


def request_changes(assessment, expected_version, note=''):
    from models import RevisionRequest
    _need(assessment, ap.REVIEW)
    open_rows = RevisionRequest.query.filter_by(assessment_id=assessment.id, status='open').all()
    if not open_rows:
        raise WorkflowError('ต้องเปิดประเด็นที่ขอแก้ไขอย่างน้อย 1 รายการก่อนส่งกลับ')
    current = assessment.workflow_status
    _move(assessment, expected_version, REVIEWING_STATES, 'changes_requested')
    _event(assessment, 'request_changes', current, 'changes_requested', note or f'{len(open_rows)} ประเด็น')
    notify({r.responsible_user_id for r in open_rows} | set(_org_editors(assessment)), 'changes_requested', f'มีคำขอหลักฐานเพิ่ม: {assessment.name}', _link(assessment))
    db.session.commit()


def save_response(assessment, issue, note):
    _need(assessment, ap.EDIT)
    if assessment.workflow_status != 'changes_requested' or issue.assessment_id != assessment.id or issue.status != 'open':
        raise WorkflowError('ตอบประเด็นได้เมื่องานถูกส่งกลับและประเด็นยังเปิดอยู่')
    if len((note or '').strip()) < MIN_REASON:
        raise WorkflowError('คำชี้แจงต้องมีอย่างน้อย 8 ตัวอักษร')
    issue.response_note, issue.responded_by = note.strip()[:4000], _uid()
    db.session.commit()


def resubmit(assessment, expected_version, note=''):
    from models import RevisionRequest
    _need(assessment, ap.EDIT)
    open_rows = RevisionRequest.query.filter_by(assessment_id=assessment.id, status='open').all()
    missing = [r.control_id for r in open_rows if not (r.response_note or '').strip()]
    if missing:
        raise WorkflowError('กรุณาชี้แจงทุกประเด็นที่เปิดอยู่ก่อนส่งฉบับแก้ไข: ' + ', '.join(missing))
    _move(assessment, expected_version, ('changes_requested',), 'resubmitted')
    _refresh_system_result(assessment)
    row = _new_revision(assessment, note, {str(r.id): r.response_note for r in open_rows})
    for issue in open_rows:
        issue.status, issue.responded_in_revision, issue.version = 'responded', row.revision_no, (issue.version or 0) + 1
    _event(assessment, 'resubmit', 'changes_requested', 'resubmitted', note, row.revision_no)
    notify(_active_reviewers(assessment), 'resubmitted', f'มีฉบับแก้ไขใหม่: {assessment.name} (ฉบับที่ {row.revision_no})', _link(assessment))
    db.session.commit()
    return row


def close_issue(assessment, issue, expected_issue_version, note, evidence_refs):
    """Only the named verifier, while still holding an active review right, may close an issue."""
    from models import DocumentFile, RevisionRequest
    _need(assessment, ap.REVIEW)
    if issue.assessment_id != assessment.id or issue.verifier_user_id != _uid():
        raise WorkflowForbidden('เฉพาะผู้ตรวจที่ระบุไว้ในประเด็นนี้เท่านั้นที่ปิดประเด็นได้')
    if assessment.workflow_status not in REVIEWING_STATES:
        raise WorkflowError('ปิดประเด็นได้ระหว่างการทบทวนเท่านั้น')
    if issue.status != 'responded':
        raise WorkflowError('ปิดได้เฉพาะประเด็นที่หน่วยงานตอบกลับแล้ว')
    if len((note or '').strip()) < MIN_REASON:
        raise WorkflowError('กรุณาระบุเหตุผลการปิดประเด็นอย่างน้อย 8 ตัวอักษร')
    refs = []
    for file_id, page in evidence_refs:
        row = db.session.get(DocumentFile, file_id or 0)
        if row is None or row.check_id != assessment.check_id:
            raise WorkflowError('หลักฐานที่ใช้ปิดประเด็นต้องเป็นไฟล์ของงานนี้')
        if page is not None and not 1 <= page <= max(row.page_count or 1, 1):
            raise WorkflowError('เลขหน้าไม่อยู่ในไฟล์')
        refs.append({'file_id': row.id, 'filename': row.original_filename, 'page': page, 'content_hash': row.content_hash})
    if not refs:
        raise WorkflowError('ต้องระบุหลักฐานที่ใช้ปิดประเด็นอย่างน้อย 1 รายการ')
    values = {'status': 'closed', 'closed_by': _uid(), 'closed_at': datetime.utcnow(), 'close_note': note.strip()[:4000],
              'closing_evidence_json': json_dumps(refs), 'version': RevisionRequest.version + 1, 'updated_at': datetime.utcnow()}
    result = db.session.execute(update(RevisionRequest).where(RevisionRequest.id == issue.id, RevisionRequest.status == 'responded',
                                                              RevisionRequest.version == int(expected_issue_version)).values(**values)
                                .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.session.rollback()
        raise WorkflowConflict('ประเด็นนี้ถูกเปลี่ยนจากหน้าจออื่นแล้ว กรุณาโหลดหน้าใหม่')
    db.session.expire(issue)
    _event(assessment, 'close_issue', assessment.workflow_status, assessment.workflow_status, f'issue {issue.id}: {note.strip()}')
    notify(set(_org_editors(assessment)), 'issue_closed', f'ปิดประเด็น {issue.control_id} แล้ว: {assessment.name}', _link(assessment))
    db.session.commit()


def reopen_issue(assessment, issue, expected_issue_version, note):
    from models import RevisionRequest
    _need(assessment, ap.REVIEW)
    if issue.verifier_user_id != _uid() or issue.status != 'responded':
        raise WorkflowForbidden('เฉพาะผู้ตรวจที่ระบุไว้ และเฉพาะประเด็นที่ตอบกลับแล้ว')
    if len((note or '').strip()) < MIN_REASON:
        raise WorkflowError('กรุณาระบุเหตุผลอย่างน้อย 8 ตัวอักษร')
    result = db.session.execute(update(RevisionRequest).where(RevisionRequest.id == issue.id, RevisionRequest.version == int(expected_issue_version))
                                .values(status='open', response_note=None, close_note=note.strip()[:4000], version=RevisionRequest.version + 1)
                                .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.session.rollback()
        raise WorkflowConflict('ประเด็นนี้ถูกเปลี่ยนจากหน้าจออื่นแล้ว กรุณาโหลดหน้าใหม่')
    db.session.expire(issue)
    _event(assessment, 'reopen_issue', assessment.workflow_status, assessment.workflow_status, f'issue {issue.id}: {note.strip()}')
    db.session.commit()


def judge_control(assessment, finding, judgement, reason, level=None):
    """Committee result for one control, stored beside (not over) the system's preliminary level."""
    from services.domain_orchestrator import recalculate
    from services.domain_rubric import REVIEWED, clamp_level
    _need(assessment, ap.REVIEW)
    if assessment.workflow_status not in REVIEWING_STATES:
        raise WorkflowError('บันทึกผลรายข้อได้ระหว่างการทบทวนเท่านั้น')
    if finding.assessment_id != assessment.id or finding.state == 'not_applicable':
        raise WorkflowError('Control นี้ไม่อยู่ในขอบเขต')
    if judgement not in JUDGEMENTS or len((reason or '').strip()) < MIN_REASON:
        raise WorkflowError('เลือกผลและระบุเหตุผลอย่างน้อย 8 ตัวอักษร')
    finding.judgement, finding.judgement_reason, finding.judged_by, finding.judged_at = judgement, reason.strip()[:4000], _uid(), datetime.utcnow()
    chosen = clamp_level(level) if level not in (None, '') else None
    if chosen is None:
        chosen = (finding.proposed_level or 0) if judgement == 'sufficient' else min(finding.proposed_level or 0, 1)
    finding.human_level, finding.level, finding.human_note = chosen, chosen, reason.strip()[:4000]
    finding.human_stance = 'supported' if judgement == 'sufficient' else 'contradicted'
    finding.state, finding.confidence = REVIEWED, 'high'
    finding.reviewed_by, finding.reviewed_by_email, finding.reviewed_at = _uid(), session.get('email'), datetime.utcnow()
    db.session.flush()
    recalculate(assessment)
    _audit('control_judgement', assessment.id, f'{finding.control_id}: {judgement}; level={chosen}')
    db.session.commit()


def confirm(assessment, expected_version, note=''):
    from models import DomainFinding, RevisionRequest
    _need(assessment, ap.REVIEW)
    blocking = RevisionRequest.query.filter(RevisionRequest.assessment_id == assessment.id, RevisionRequest.status != 'closed',
                                            RevisionRequest.severity.in_(BLOCKING_SEVERITIES)).all()
    if blocking:
        raise WorkflowError('ยังมีประเด็นสำคัญมากที่ยังไม่ปิด: ' + ', '.join(r.control_id for r in blocking))
    findings = DomainFinding.query.filter_by(assessment_id=assessment.id).all()
    issue_controls = {r.control_id for r in RevisionRequest.query.filter_by(assessment_id=assessment.id).all()}
    unjudged = sorted(f.control_id for f in findings if f.state != 'not_applicable' and (f.critical or f.control_id in issue_controls) and not f.judgement)
    if unjudged:
        raise WorkflowError('กรรมการต้องบันทึกผลรายข้อของ Control วิกฤตและ Control ที่มีประเด็นก่อนยืนยัน: ' + ', '.join(unjudged))
    current = assessment.workflow_status
    _move(assessment, expected_version, REVIEWING_STATES, 'confirmed', {'confirmed_at': datetime.utcnow()})
    _event(assessment, 'confirm', current, 'confirmed', note)
    notify(set(_org_editors(assessment)) | set(_round_coordinators(assessment)), 'confirmed', f'ยืนยันผลแล้ว: {assessment.name}', _link(assessment))
    db.session.commit()


# ---------------------------------------------------------------- rounds
def close_round(rnd, complete, reason=''):
    from models import DomainAssessment, RevisionRequest, RoundParticipation
    if rnd.owner_org_id not in ap.oversight_org_ids(role='round_coordinator'):
        raise WorkflowForbidden('เฉพาะผู้ประสานรอบของหน่วยงานเจ้าของรอบ')
    if rnd.status != 'open':
        raise WorkflowError('ปิดได้เฉพาะรอบที่เปิดอยู่')
    if complete:
        problems = []
        for part in RoundParticipation.query.filter_by(round_id=rnd.id, status='accepted').all():
            work = DomainAssessment.query.filter_by(round_id=rnd.id, organization_id=part.organization_id).all()
            if not work or any(a.workflow_status != 'confirmed' for a in work):
                problems.append(f'{part.organization.name}: ยังไม่ยืนยันผลครบ')
        ids = [a.id for a in DomainAssessment.query.filter_by(round_id=rnd.id).all()]
        open_critical = RevisionRequest.query.filter(RevisionRequest.assessment_id.in_(ids or [-1]), RevisionRequest.status != 'closed',
                                                     RevisionRequest.severity.in_(BLOCKING_SEVERITIES)).count()
        if open_critical:
            problems.append(f'ประเด็นสำคัญมากที่ยังเปิด {open_critical} รายการ')
        if problems:
            raise WorkflowError('ยังปิดรอบแบบสมบูรณ์ไม่ได้: ' + '; '.join(problems))
        rnd.status = 'closed_complete'
    else:
        if len((reason or '').strip()) < MIN_REASON:
            raise WorkflowError('การปิดรอบแบบยังไม่สมบูรณ์ต้องมีเหตุผลอย่างน้อย 8 ตัวอักษร')
        rnd.status, rnd.close_reason = 'closed_incomplete', reason.strip()[:4000]
    from models import AuditLog
    db.session.add(AuditLog(user_id=_uid(), actor_email=session.get('email'), action='round_close', target_type='assessment_round', target_id=str(rnd.id), detail=rnd.status + (f'; {reason}' if reason else '')))
    db.session.commit()


def is_overdue(due_on, status):
    return bool(due_on and due_on < date.today() and status not in ('confirmed',))


def content_digest(payload):
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
