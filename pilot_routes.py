"""MHESI pilot pages: organization context, rounds, workflow, review queue, dashboard, AI register,
criteria sets, organizations and notifications. Authorization comes from services/access_policy.py."""
import csv
import io
from collections import Counter
from datetime import date, datetime

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models import (AISystem, AssessmentRound, AuditLog, CommitteeAssignment, CriteriaSet, DocumentFile, DomainAssessment, DomainFinding,
                    IntegrationEndpoint, MEMBERSHIP_ROLES, ModelProcessingRule, Notification, ORG_TYPES, Organization, OrganizationMembership,
                    RevisionRequest, RoundParticipation, SubmissionRevision, User, WorkflowEvent)
from services import access_policy as ap
from services import workflow as wf
from services.domain_catalog import content_hash, get_pack
from services.domain_orchestrator import current_config
from utils import json_dumps, json_loads, login_required

bp = Blueprint('pilot', __name__)
ROLE_LABELS = {'org_coordinator': 'ผู้ประสานงานสถาบัน', 'org_staff': 'เจ้าหน้าที่ที่ได้รับสิทธิ์', 'round_coordinator': 'ผู้ประสานรอบ',
               'executive': 'ผู้บริหาร (ดูสรุป)', 'criteria_approver': 'ผู้อนุมัติชุดเกณฑ์'}
ORG_TYPE_LABELS = {'ministry': 'กระทรวง', 'ministry_office': 'สำนักงานปลัดกระทรวง', 'university': 'สถาบันอุดมศึกษา', 'mhesi_agency': 'หน่วยงานในกำกับ อว.', 'other': 'อื่น ๆ'}
CRITERIA_LABELS = {'draft': 'ร่าง', 'in_review': 'รอตรวจ', 'approved': 'อนุมัติแล้ว', 'published': 'เผยแพร่แล้ว', 'retired': 'เลิกใช้'}
ROUND_LABELS = {'draft': 'ร่าง', 'open': 'เปิดรับงาน', 'closed_complete': 'ปิดรอบ (สมบูรณ์)', 'closed_incomplete': 'ปิดรอบ (ยังไม่สมบูรณ์)'}
PART_LABELS = {'invited': 'ได้รับเชิญ', 'accepted': 'เข้าร่วม', 'declined': 'ปฏิเสธ', 'withdrawn': 'ถอนตัว'}
MIN_NOTE = 8


def audit(action, target_type, target_id, detail=''):
    db.session.add(AuditLog(user_id=session.get('user_id'), actor_email=session.get('email'), action=action, target_type=target_type,
                            target_id=str(target_id) if target_id is not None else None, detail=(detail or '')[:15000]))


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _fail(error, back):
    db.session.rollback()
    return render_template('pilot/action_error.html', message=str(error), back=back), getattr(error, 'status_code', 400)


@bp.app_template_filter('fromjson')
def fromjson(value):
    return json_loads(value, default=None)


@bp.app_context_processor
def pilot_labels():
    return {'pilot_role_labels': ROLE_LABELS, 'wf_status_labels': wf.STATUS_LABELS, 'issue_labels': wf.ISSUE_LABELS,
            'severity_labels': wf.SEVERITY_LABELS, 'criteria_labels': CRITERIA_LABELS, 'round_labels': ROUND_LABELS, 'part_labels': PART_LABELS,
            'judgement_labels': wf.JUDGEMENTS, 'event_labels': wf.EVENT_LABELS, 'today': date.today()}


def _is_criteria_manager():
    return session.get('role') == 'admin' or any(m.role == 'criteria_approver' for m in ap.memberships())


def _coordinates(rnd):
    return rnd.owner_org_id in ap.oversight_org_ids(role='round_coordinator')


def _oversees(rnd):
    return rnd.owner_org_id in ap.oversight_org_ids()


# ---------------------------------------------------------------- organization context
@bp.route('/org-context', methods=['POST'])
@login_required()
def org_context():
    org_id = request.form.get('org_id', type=int)
    if org_id and any(m.organization_id == org_id for m in ap.memberships()):
        session['org_id'] = org_id
        org = db.session.get(Organization, org_id)
        flash(f'กำลังทำงานในนามของ {org.name}', 'success')
    else:
        session['org_id'] = None
    return redirect(request.form.get('next') or url_for('pilot.rounds'))


# ---------------------------------------------------------------- rounds
@bp.route('/rounds')
@login_required()
def rounds():
    my_orgs = ap.editor_org_ids()
    participations = RoundParticipation.query.filter(RoundParticipation.organization_id.in_(my_orgs or [-1])).order_by(RoundParticipation.id.desc()).all()
    work = {}
    for part in participations:
        rows = DomainAssessment.query.filter_by(round_id=part.round_id, organization_id=part.organization_id).order_by(DomainAssessment.id).all()
        work[part.id] = [{'a': a, 'open': RevisionRequest.query.filter(RevisionRequest.assessment_id == a.id, RevisionRequest.status != 'closed').count(),
                          'perms': ap.assessment_permissions(a)} for a in rows]
    owned = AssessmentRound.query.filter(AssessmentRound.owner_org_id.in_(ap.oversight_org_ids() or [-1])).order_by(AssessmentRound.id.desc()).all()
    coordinator_orgs = ap.oversight_org_ids(role='round_coordinator')
    can_create = bool(coordinator_orgs)
    published = CriteriaSet.query.filter_by(status='published').order_by(CriteriaSet.code, CriteriaSet.version).all() if can_create else []
    packs = {p.id: get_pack(db.session, p.round.criteria_set.domain_slug) for p in participations}
    return render_template('pilot/rounds.html', participations=participations, work=work, owned=owned, can_create=can_create,
                           coordinator_orgs=Organization.query.filter(Organization.id.in_(coordinator_orgs or [-1])).all(), published=published,
                           packs=packs, my_roles={(m.organization_id, m.role) for m in ap.memberships()}, active_org=ap.active_org_id(),
                           coordinated={r.id for r in owned if _coordinates(r)})


@bp.route('/rounds/new', methods=['POST'])
@login_required()
def round_new():
    owner = request.form.get('owner_org_id', type=int)
    if owner not in ap.oversight_org_ids(role='round_coordinator'):
        ap.deny('assessment_round', None, 'create')
        abort(403)
    criteria = db.session.get(CriteriaSet, request.form.get('criteria_set_id', type=int) or 0)
    code, title = request.form.get('code', '').strip()[:60], request.form.get('title', '').strip()[:255]
    if criteria is None or criteria.status != 'published':
        flash('รอบประเมินต้องอ้างอิงชุดเกณฑ์ที่เผยแพร่แล้ว', 'danger')
        return redirect(url_for('pilot.rounds'))
    if not code or not title or AssessmentRound.query.filter_by(code=code).first():
        flash('กรุณาระบุรหัสรอบที่ไม่ซ้ำและชื่อรอบ', 'warning')
        return redirect(url_for('pilot.rounds'))
    rnd = AssessmentRound(code=code, title=title, owner_org_id=owner, scope_th=request.form.get('scope_th', '').strip()[:4000],
                          opens_on=_date(request.form.get('opens_on')), closes_on=_date(request.form.get('closes_on')), criteria_set_id=criteria.id,
                          document_scope='public_or_redacted', status='open', is_demo=criteria.is_demo or current_app.config.get('DEMO_MODE', False),
                          created_by=session['user_id'])
    db.session.add(rnd)
    db.session.flush()
    audit('round_create', 'assessment_round', rnd.id, f'criteria={criteria.code}@{criteria.version}')
    db.session.commit()
    flash('เปิดรอบประเมินแล้ว', 'success')
    return redirect(url_for('pilot.round_detail', round_id=rnd.id))


def _round_or_403(round_id, coordinator=False):
    rnd = db.session.get(AssessmentRound, round_id)
    if rnd is None:
        abort(404)
    allowed = _coordinates(rnd) if coordinator else (_oversees(rnd) or RoundParticipation.query.filter(
        RoundParticipation.round_id == rnd.id, RoundParticipation.organization_id.in_(ap.editor_org_ids() or [-1])).first() is not None)
    if not allowed:
        ap.deny('assessment_round', round_id, 'coordinate' if coordinator else 'view')
        abort(403)
    return rnd


@bp.route('/rounds/<int:round_id>')
@login_required()
def round_detail(round_id):
    rnd = _round_or_403(round_id)
    if not _oversees(rnd):
        return redirect(url_for('pilot.rounds'))
    parts = RoundParticipation.query.filter_by(round_id=rnd.id).order_by(RoundParticipation.id).all()
    rows = DomainAssessment.query.filter_by(round_id=rnd.id).order_by(DomainAssessment.organization_id, DomainAssessment.id).all()
    committee = User.query.filter_by(role='committee', is_active=True).order_by(User.full_name).all() if _coordinates(rnd) else []
    assigned = {}
    for a in rows:
        if a.check_id:
            assigned[a.id] = CommitteeAssignment.query.filter_by(check_id=a.check_id).all()
    invitable = Organization.query.filter(Organization.is_active.is_(True), Organization.id != rnd.owner_org_id,
                                          Organization.id.notin_([p.organization_id for p in parts] or [-1])).order_by(Organization.name).all()
    coordinators = {o.id: [m.user for m in OrganizationMembership.query.filter_by(organization_id=o.id, role='org_coordinator', is_active=True).all()] for o in invitable}
    return render_template('pilot/round_detail.html', rnd=rnd, parts=parts, rows=rows, committee=committee, assigned=assigned,
                           invitable=invitable, coordinators=coordinators, coordinator=_coordinates(rnd))


@bp.route('/rounds/<int:round_id>/invite', methods=['POST'])
@login_required()
def round_invite(round_id):
    rnd = _round_or_403(round_id, coordinator=True)
    org = db.session.get(Organization, request.form.get('organization_id', type=int) or 0)
    contact = request.form.get('coordinator_user_id', type=int)
    if org is None or rnd.status != 'open':
        abort(400)
    if not OrganizationMembership.query.filter_by(organization_id=org.id, user_id=contact, role='org_coordinator', is_active=True).first():
        flash('ผู้ประสานต้องเป็นผู้ประสานงานสถาบันของหน่วยงานนั้น', 'warning')
        return redirect(url_for('pilot.round_detail', round_id=rnd.id))
    if RoundParticipation.query.filter_by(round_id=rnd.id, organization_id=org.id).first():
        flash('เชิญหน่วยงานนี้แล้ว', 'info')
        return redirect(url_for('pilot.round_detail', round_id=rnd.id))
    db.session.add(RoundParticipation(round_id=rnd.id, organization_id=org.id, coordinator_user_id=contact, status='invited',
                                      due_on=_date(request.form.get('due_on')) or rnd.closes_on, invited_by=session['user_id']))
    wf.notify([contact], 'invited', f'ได้รับเชิญเข้ารอบ: {rnd.title}', url_for('pilot.rounds'))
    audit('round_invite', 'assessment_round', rnd.id, f'org={org.code}')
    db.session.commit()
    flash(f'เชิญ {org.name} แล้ว', 'success')
    return redirect(url_for('pilot.round_detail', round_id=rnd.id))


@bp.route('/rounds/participation/<int:part_id>/respond', methods=['POST'])
@login_required()
def participation_respond(part_id):
    part = db.session.get(RoundParticipation, part_id)
    if part is None:
        abort(404)
    if 'org_coordinator' not in ap.org_roles(part.organization_id):
        ap.deny('round_participation', part_id, 'respond')
        abort(403)
    choice = request.form.get('choice')
    if part.status != 'invited' or choice not in ('accepted', 'declined'):
        abort(400)
    part.status, part.responded_at = choice, datetime.utcnow()
    audit('round_' + choice, 'round_participation', part.id, f'org={part.organization.code}')
    db.session.commit()
    flash('บันทึกการตอบรับแล้ว' if choice == 'accepted' else 'บันทึกการปฏิเสธแล้ว', 'success')
    return redirect(url_for('pilot.rounds'))


@bp.route('/rounds/participation/<int:part_id>/start', methods=['POST'])
@login_required(role='user')
def participation_start(part_id):
    part = db.session.get(RoundParticipation, part_id)
    if part is None:
        abort(404)
    if not set(ap.EDITOR_ROLES) & ap.org_roles(part.organization_id) or ap.active_org_id() != part.organization_id:
        ap.deny('round_participation', part_id, 'start')
        flash('เลือกบริบทหน่วยงานให้ตรงกับรอบนี้ก่อนเริ่มงาน', 'warning')
        return redirect(url_for('pilot.rounds'))
    rnd = part.round
    if part.status != 'accepted' or rnd.status != 'open':
        flash('เริ่มงานได้เมื่อหน่วยงานตอบรับและรอบยังเปิดอยู่', 'warning')
        return redirect(url_for('pilot.rounds'))
    criteria = rnd.criteria_set
    pack = (json_loads(criteria.snapshot_json, default={}).get('packs') or {}).get(criteria.domain_slug) or get_pack(db.session, criteria.domain_slug)
    org_type = request.form.get('org_type', '')
    name = request.form.get('name', '').strip()[:255]
    if org_type not in {o['id'] for o in pack['organization_types']} or not name:
        flash('กรุณาระบุชื่องานและประเภทหน่วยงาน', 'warning')
        return redirect(url_for('pilot.rounds'))
    a = DomainAssessment(user_id=session['user_id'], domain_slug=criteria.domain_slug, name=name, organization_name=part.organization.name,
                         profile_json=json_dumps({'org_type': org_type}), status='draft', current_step=2, organization_id=part.organization_id,
                         round_id=rnd.id, criteria_set_id=criteria.id, criteria_version=criteria.version, created_by_id=session['user_id'],
                         responsible_user_id=session['user_id'], workflow_status='draft', workflow_version=0)
    db.session.add(a)
    db.session.flush()
    audit('domain_assessment_create', 'domain_assessment', a.id, f'round={rnd.code}; criteria={criteria.code}@{criteria.version}')
    db.session.commit()
    return redirect(url_for('gov.step', assessment_id=a.id, number=2))


@bp.route('/rounds/<int:round_id>/close', methods=['POST'])
@login_required()
def round_close(round_id):
    rnd = _round_or_403(round_id, coordinator=True)
    try:
        wf.close_round(rnd, request.form.get('mode') == 'complete', request.form.get('reason', ''))
    except wf.WorkflowError as exc:
        return _fail(exc, url_for('pilot.round_detail', round_id=rnd.id))
    flash('ปิดรอบแล้ว', 'success')
    return redirect(url_for('pilot.round_detail', round_id=rnd.id))


# ---------------------------------------------------------------- dashboard
def _dashboard_rows(rnd, detail):
    parts = RoundParticipation.query.filter_by(round_id=rnd.id).order_by(RoundParticipation.id).all()
    rows, topics = [], Counter()
    for part in parts:
        work = DomainAssessment.query.filter_by(round_id=rnd.id, organization_id=part.organization_id).all()
        ids = [a.id for a in work] or [-1]
        issues = RevisionRequest.query.filter(RevisionRequest.assessment_id.in_(ids)).all()
        for issue in issues:
            topics[issue.control_id] += 1
        status = [a.workflow_status for a in work]
        rows.append({'org': part.organization, 'participation': part, 'assessments': len(work),
                     'submitted': sum(1 for s in status if s not in (None, 'draft')), 'confirmed': sum(1 for s in status if s == 'confirmed'),
                     'in_review': sum(1 for s in status if s in ('assigned', 'in_review', 're_review', 'resubmitted')),
                     'changes_requested': sum(1 for s in status if s == 'changes_requested'),
                     'overdue': bool(part.due_on and part.due_on < date.today() and (not status or any(s != 'confirmed' for s in status)) and part.status == 'accepted'),
                     'open_critical': sum(1 for i in issues if i.status != 'closed' and i.severity == 'critical'),
                     'open_issues': sum(1 for i in issues if i.status != 'closed'),
                     'open_controls': sorted({i.control_id for i in issues if i.status != 'closed'}) if detail else [],
                     'status_list': [wf.STATUS_LABELS.get(s, s) for s in status]})
    return parts, rows, topics


@bp.route('/rounds/<int:round_id>/dashboard')
@login_required()
def round_dashboard(round_id):
    rnd = _round_or_403(round_id)
    if not _oversees(rnd):
        ap.deny('assessment_round', round_id, 'dashboard')
        abort(403)
    detail = _coordinates(rnd)
    parts, rows, topics = _dashboard_rows(rnd, detail)
    accepted = [r for r in rows if r['participation'].status == 'accepted']
    totals = {'denominator': len(accepted), 'invited': len(rows), 'submitted': sum(1 for r in accepted if r['submitted']),
              'confirmed': sum(1 for r in accepted if r['assessments'] and r['confirmed'] == r['assessments']),
              'overdue': sum(1 for r in accepted if r['overdue']), 'open_critical': sum(r['open_critical'] for r in rows)}
    return render_template('pilot/dashboard.html', rnd=rnd, rows=rows, totals=totals, topics=topics.most_common(8), detail=detail,
                           criteria=rnd.criteria_set, integration=db.session.get(IntegrationEndpoint, 'DSV'))


@bp.route('/rounds/<int:round_id>/dashboard.csv')
@login_required()
def round_dashboard_csv(round_id):
    rnd = _round_or_403(round_id)
    if not _oversees(rnd):
        abort(403)
    detail = _coordinates(rnd)
    _, rows, _ = _dashboard_rows(rnd, detail)
    buffer = io.StringIO()
    fields = ['organization_code', 'organization', 'participation', 'assessments', 'submitted', 'in_review', 'changes_requested', 'confirmed', 'overdue',
              'open_critical', 'open_issues', 'criteria', 'criteria_version'] + (['open_controls'] if detail else [])
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        line = {'organization_code': r['org'].code, 'organization': r['org'].name, 'participation': r['participation'].status, 'assessments': r['assessments'],
                'submitted': r['submitted'], 'in_review': r['in_review'], 'changes_requested': r['changes_requested'], 'confirmed': r['confirmed'],
                'overdue': r['overdue'], 'open_critical': r['open_critical'], 'open_issues': r['open_issues'], 'criteria': rnd.criteria_set.code,
                'criteria_version': rnd.criteria_set.version}
        if detail:
            line['open_controls'] = ' '.join(r['open_controls'])
        writer.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in '=+-@' else v) for k, v in line.items()})
    audit('round_dashboard_export', 'assessment_round', rnd.id, 'csv detail' if detail else 'csv summary')
    db.session.commit()
    return Response('﻿' + buffer.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=round_{rnd.id}_status.csv'})


@bp.route('/rounds/<int:round_id>/export/dsv.json')
@login_required()
def round_export_dsv(round_id):
    """Payload prepared for Digital Single View. Not sent anywhere: the integration has no contract or credentials yet."""
    rnd = _round_or_403(round_id, coordinator=True)
    endpoint = db.session.get(IntegrationEndpoint, 'DSV')
    _, rows, _ = _dashboard_rows(rnd, False)
    items = [{'institution_ref': r['org'].external_ref, 'institution_ref_verified': False, 'organization_code': r['org'].code,
              'round': rnd.code, 'criteria': rnd.criteria_set.code, 'criteria_version': rnd.criteria_set.version,
              'assessments': r['assessments'], 'confirmed': r['confirmed'], 'open_critical_issues': r['open_critical'],
              'report_signature': 'unsigned'} for r in rows]
    audit('integration_export', 'assessment_round', rnd.id, 'DSV payload (not delivered)')
    db.session.commit()
    return jsonify({'integration': 'DSV', 'integration_status': endpoint.status if endpoint else 'prepared', 'delivery': 'not_sent',
                    'missing': json_loads(endpoint.missing_json, default=[]) if endpoint else [], 'demo': rnd.is_demo, 'items': items})


# ---------------------------------------------------------------- workflow
def _workflow_context(a):
    perms = ap.assessment_permissions(a)
    issues = RevisionRequest.query.filter_by(assessment_id=a.id).order_by(RevisionRequest.id).all()
    revisions = wf.revisions(a)
    events = WorkflowEvent.query.filter_by(assessment_id=a.id).order_by(WorkflowEvent.id).all()
    assignments = CommitteeAssignment.query.filter_by(check_id=a.check_id).all() if a.check_id else []
    users = {u.id: u for u in User.query.filter(User.id.in_({i.responsible_user_id for i in issues} | {i.verifier_user_id for i in issues}
                                                            | {e.actor_id for e in events if e.actor_id} | {r.submitted_by for r in revisions} | {-1})).all()}
    config = current_config(a) if ap.VIEW in perms else None
    findings = DomainFinding.query.filter_by(assessment_id=a.id).order_by(DomainFinding.control_id).all() if ap.VIEW in perms else []
    controls = {c['id']: c for c in (config or {}).get('controls', [])}
    editors = [m.user for m in OrganizationMembership.query.filter(OrganizationMembership.organization_id == a.organization_id,
                                                                   OrganizationMembership.role.in_(ap.EDITOR_ROLES), OrganizationMembership.is_active.is_(True)).all()] if a.organization_id else []
    files = DocumentFile.query.filter_by(check_id=a.check_id).order_by(DocumentFile.id).all() if a.check_id and ap.READ_SOURCE in perms else []
    return {'a': a, 'perms': perms, 'issues': issues, 'revisions': [(r, json_loads(r.diff_json, default={}), json_loads(r.files_json, default=[])) for r in revisions],
            'events': events, 'assignments': assignments, 'users': users, 'config': config, 'findings': findings, 'controls': controls, 'editors': editors,
            'files': files, 'committee': User.query.filter_by(role='committee', is_active=True).order_by(User.full_name).all() if ap.ASSIGN in perms else [],
            'summary': json_loads(a.summary_json, default={}) if ap.VIEW in perms else {}, 'uid': session.get('user_id'),
            'can_modify': ap.EDIT in perms and wf.org_can_modify(a), 'criteria': a.criteria_set}


@bp.route('/assessments/<int:assessment_id>/workflow')
@login_required()
def workflow(assessment_id):
    a = db.session.get(DomainAssessment, assessment_id)
    if a is None:
        abort(404)
    if ap.VIEW_STATUS not in ap.assessment_permissions(a):
        ap.deny('domain_assessment', assessment_id, ap.VIEW_STATUS)
        abort(403)
    return render_template('pilot/workflow.html', **_workflow_context(a))


def _workflow_target(assessment_id):
    a = db.session.get(DomainAssessment, assessment_id)
    if a is None:
        abort(404)
    if ap.VIEW_STATUS not in ap.assessment_permissions(a):
        ap.deny('domain_assessment', assessment_id, 'workflow_action')
        abort(403)
    return a


@bp.route('/assessments/<int:assessment_id>/workflow/<action>', methods=['POST'])
@login_required()
def workflow_action(assessment_id, action):
    a = _workflow_target(assessment_id)
    back = url_for('pilot.workflow', assessment_id=a.id)
    version = request.form.get('version', type=int)
    note = request.form.get('note', '')
    try:
        if action == 'submit':
            wf.submit(a, version, note)
            flash('ส่งงานแล้ว ระบบบันทึกเป็นฉบับที่ 1', 'success')
        elif action == 'assign':
            wf.assign_reviewer(a, request.form.get('committee_user_id', type=int), version)
            flash('มอบหมายกรรมการแล้ว', 'success')
        elif action == 'revoke':
            wf.revoke_reviewer(a, request.form.get('committee_user_id', type=int), note)
            flash('ถอนสิทธิ์กรรมการแล้ว', 'success')
        elif action == 'start-review':
            wf.start_review(a, version)
            flash('เริ่มทบทวนแล้ว', 'success')
        elif action == 'raise-issue':
            wf.raise_issue(a, request.form.get('control_id', ''), request.form.get('severity', ''), request.form.get('reason', ''),
                           request.form.get('evidence_required', ''), request.form.get('responsible_user_id', type=int), _date(request.form.get('due_on')))
            flash('เปิดประเด็นแล้ว', 'success')
        elif action == 'request-changes':
            wf.request_changes(a, version, note)
            flash('ส่งกลับให้หน่วยงานแก้ไขแล้ว', 'success')
        elif action == 'resubmit':
            row = wf.resubmit(a, version, note)
            flash(f'ส่งฉบับแก้ไขแล้ว (ฉบับที่ {row.revision_no})', 'success')
        elif action == 'confirm':
            wf.confirm(a, version, note)
            flash('ยืนยันผลแล้ว', 'success')
        else:
            abort(404)
    except wf.WorkflowError as exc:
        return _fail(exc, back)
    except ValueError as exc:
        return _fail(wf.WorkflowError(str(exc)), back)
    return redirect(back)


@bp.route('/assessments/<int:assessment_id>/issues/<int:issue_id>/<action>', methods=['POST'])
@login_required()
def issue_action(assessment_id, issue_id, action):
    a = _workflow_target(assessment_id)
    issue = db.session.get(RevisionRequest, issue_id)
    back = url_for('pilot.workflow', assessment_id=a.id)
    if issue is None or issue.assessment_id != a.id:
        abort(404)
    try:
        if action == 'respond':
            wf.save_response(a, issue, request.form.get('note', ''))
            flash('บันทึกคำชี้แจงแล้ว ส่งฉบับแก้ไขเมื่อชี้แจงครบทุกประเด็น', 'success')
        elif action == 'close':
            refs = []
            for value in request.form.getlist('evidence'):
                file_id, _, page = value.partition(':')
                refs.append((int(file_id) if file_id.isdigit() else None, int(page) if page.isdigit() else None))
            page_override = request.form.get('page', type=int)
            if page_override and refs:
                refs = [(refs[0][0], page_override)] + refs[1:]
            wf.close_issue(a, issue, request.form.get('version', type=int), request.form.get('note', ''), refs)
            flash('ปิดประเด็นแล้ว', 'success')
        elif action == 'reopen':
            wf.reopen_issue(a, issue, request.form.get('version', type=int), request.form.get('note', ''))
            flash('เปิดประเด็นอีกครั้งแล้ว', 'success')
        else:
            abort(404)
    except wf.WorkflowError as exc:
        return _fail(exc, back)
    return redirect(back + f'#issue-{issue.id}')


@bp.route('/assessments/<int:assessment_id>/findings/<int:finding_id>/judge', methods=['POST'])
@login_required()
def judge(assessment_id, finding_id):
    a = _workflow_target(assessment_id)
    finding = db.session.get(DomainFinding, finding_id)
    back = url_for('pilot.workflow', assessment_id=a.id)
    if finding is None:
        abort(404)
    try:
        wf.judge_control(a, finding, request.form.get('judgement', ''), request.form.get('reason', ''), request.form.get('level'))
    except wf.WorkflowError as exc:
        return _fail(exc, back)
    flash(f'บันทึกผลของกรรมการสำหรับ {finding.control_id} แล้ว', 'success')
    return redirect(back + f'#f-{finding.id}')


# ---------------------------------------------------------------- review queue
@bp.route('/review-queue')
@login_required()
def review_queue():
    uid = session['user_id']
    rows = []
    for assignment in CommitteeAssignment.query.filter_by(committee_user_id=uid).order_by(CommitteeAssignment.id.desc()).all():
        a = DomainAssessment.query.filter_by(check_id=assignment.check_id).first()
        if a is None:
            continue
        revisions = wf.revisions(a)
        my_last = WorkflowEvent.query.filter(WorkflowEvent.assessment_id == a.id, WorkflowEvent.actor_id == uid).order_by(WorkflowEvent.id.desc()).first()
        latest = revisions[-1] if revisions else None
        new_files = len(json_loads(latest.diff_json, default={}).get('added', [])) if latest and latest.revision_no > 1 and (not my_last or latest.submitted_at > my_last.created_at) else 0
        rows.append({'assignment': assignment, 'a': a, 'revision': latest.revision_no if latest else None, 'new_files': new_files,
                     'open': RevisionRequest.query.filter(RevisionRequest.assessment_id == a.id, RevisionRequest.status != 'closed').count(),
                     'responded': RevisionRequest.query.filter_by(assessment_id=a.id, status='responded').count(),
                     'history': WorkflowEvent.query.filter_by(assessment_id=a.id, actor_id=uid).order_by(WorkflowEvent.id.desc()).limit(5).all()})
    return render_template('pilot/review_queue.html', rows=rows)


# ---------------------------------------------------------------- notifications
@bp.route('/notifications')
@login_required()
def notifications():
    rows = Notification.query.filter_by(user_id=session['user_id']).order_by(Notification.created_at.desc()).limit(100).all()
    return render_template('pilot/notifications.html', rows=rows)


@bp.route('/notifications/read', methods=['POST'])
@login_required()
def notifications_read():
    Notification.query.filter_by(user_id=session['user_id'], is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(request.form.get('next') or url_for('pilot.notifications'))


# ---------------------------------------------------------------- AI register
def _registry_orgs():
    editable = set(ap.editor_org_ids())
    readable = set(editable)
    rounds = AssessmentRound.query.filter(AssessmentRound.owner_org_id.in_(ap.oversight_org_ids() or [-1])).all()
    readable |= {p.organization_id for p in RoundParticipation.query.filter(RoundParticipation.round_id.in_([r.id for r in rounds] or [-1])).all()}
    readable |= set(ap.oversight_org_ids())
    return editable, readable


@bp.route('/ai-registry', methods=['GET', 'POST'])
@login_required()
def ai_registry():
    editable, readable = _registry_orgs()
    if request.method == 'POST':
        org_id = ap.active_org_id()
        if org_id not in editable or session.get('role') != 'user':
            ap.deny('ai_system', None, 'create')
            abort(403)
        row = db.session.get(AISystem, request.form.get('id', type=int) or 0) or AISystem(organization_id=org_id, created_by=session['user_id'])
        if row.organization_id != org_id:
            abort(403)
        name, owner, purpose = (request.form.get(k, '').strip() for k in ('name', 'owner_name', 'purpose'))
        risk = request.form.get('risk_level', 'medium')
        if not name or not owner or not purpose or risk not in ('low', 'medium', 'high', 'critical'):
            flash('กรุณาระบุชื่อระบบ เจ้าของระบบ วัตถุประสงค์ และระดับความเสี่ยง', 'warning')
            return redirect(url_for('pilot.ai_registry'))
        own_ids = {a.id for a in DomainAssessment.query.filter_by(organization_id=org_id).all()}
        links = [i for i in request.form.getlist('assessment_ids', type=int) if i in own_ids]
        row.name, row.owner_name, row.purpose = name[:255], owner[:255], purpose[:4000]
        row.affected_persons, row.provider, row.model_name = (request.form.get(k, '').strip()[:4000] for k in ('affected_persons', 'provider', 'model_name'))
        row.data_types, row.risk_level = request.form.get('data_types', '').strip()[:4000], risk
        row.review_cycle_months = max(1, min(36, request.form.get('review_cycle_months', type=int) or 12))
        row.next_review_on, row.linked_assessment_ids_json = _date(request.form.get('next_review_on')), json_dumps(links)
        row.is_demo = row.is_demo or current_app.config.get('DEMO_MODE', False)
        db.session.add(row)
        db.session.flush()
        audit('ai_system_save', 'ai_system', row.id, f'org={org_id}; risk={risk}')
        db.session.commit()
        flash('บันทึกทะเบียน AI แล้ว', 'success')
        return redirect(url_for('pilot.ai_registry'))
    rows = AISystem.query.filter(AISystem.organization_id.in_(readable or {-1})).order_by(AISystem.organization_id, AISystem.name).all()
    linked = {}
    for row in rows:
        ids = json_loads(row.linked_assessment_ids_json, default=[])
        linked[row.id] = [a for a in DomainAssessment.query.filter(DomainAssessment.id.in_(ids or [-1])).all() if ap.VIEW_STATUS in ap.assessment_permissions(a)]
    active = ap.active_org_id()
    choices = DomainAssessment.query.filter_by(organization_id=active).all() if active in editable else []
    return render_template('pilot/ai_registry.html', rows=rows, linked=linked, editable=editable, can_add=active in editable and session.get('role') == 'user',
                           choices=choices, edit=db.session.get(AISystem, request.args.get('edit', type=int) or 0))


# ---------------------------------------------------------------- criteria sets
def _bundle(domain_slug):
    """Freeze the domain pack, its layers, its extended pack and the core into one snapshot."""
    pack = get_pack(db.session, domain_slug)
    if pack is None:
        return None
    names = [domain_slug, 'general'] + list(pack.get('layers', [])) + ([pack['extends']] if pack.get('extends') else [])
    packs = {name: get_pack(db.session, name) for name in dict.fromkeys(names)}
    from models import RegulatoryReference
    registry = {r.source_id: r.verification_status for r in RegulatoryReference.query.filter_by(is_active=True).all()}
    return {'packs': packs, 'registry_status_at_snapshot': registry}


@bp.route('/criteria')
@login_required()
def criteria():
    if not _is_criteria_manager() and not ap.oversight_org_ids():
        abort(403)
    rows = CriteriaSet.query.order_by(CriteriaSet.code, CriteriaSet.id.desc()).all()
    from models import RegulatoryReference
    refs = RegulatoryReference.query.filter_by(is_active=True).all()
    verification = Counter(r.verification_status for r in refs)
    users = {u.id: u for u in User.query.filter(User.id.in_({x for r in rows for x in (r.created_by, r.submitted_by, r.approved_by, r.published_by) if x} | {-1})).all()}
    usage = {r.id: AssessmentRound.query.filter_by(criteria_set_id=r.id).count() for r in rows}
    from services.domain_catalog import list_profiles
    return render_template('pilot/criteria.html', rows=rows, verification=verification, users=users, usage=usage, manager=_is_criteria_manager(),
                           approver=any(m.role == 'criteria_approver' for m in ap.memberships()), profiles=list_profiles(db.session))


@bp.route('/criteria/new', methods=['POST'])
@login_required()
def criteria_new():
    if not _is_criteria_manager():
        abort(403)
    slug, code, version, title = (request.form.get(k, '').strip() for k in ('domain_slug', 'code', 'version', 'title'))
    bundle = _bundle(slug)
    if bundle is None or not code or not version or not title:
        flash('กรุณาระบุ Domain รหัส เวอร์ชัน และชื่อชุดเกณฑ์', 'warning')
        return redirect(url_for('pilot.criteria'))
    if CriteriaSet.query.filter_by(code=code[:60], version=version[:40]).first():
        flash('มีชุดเกณฑ์รหัสและเวอร์ชันนี้แล้ว', 'warning')
        return redirect(url_for('pilot.criteria'))
    payload = json_dumps(bundle)
    row = CriteriaSet(code=code[:60], version=version[:40], title=title[:255], domain_slug=slug, status='draft', snapshot_json=payload,
                      content_hash=content_hash(bundle), is_demo=current_app.config.get('DEMO_MODE', False), created_by=session['user_id'])
    db.session.add(row)
    db.session.flush()
    audit('criteria_create', 'criteria_set', row.id, f'{row.code}@{row.version}; hash={row.content_hash}')
    db.session.commit()
    flash('สร้างร่างชุดเกณฑ์แล้ว', 'success')
    return redirect(url_for('pilot.criteria'))


@bp.route('/criteria/<int:criteria_id>/<action>', methods=['POST'])
@login_required()
def criteria_action(criteria_id, action):
    row = db.session.get(CriteriaSet, criteria_id)
    if row is None:
        abort(404)
    approver = any(m.role == 'criteria_approver' for m in ap.memberships())
    note = request.form.get('note', '').strip()
    flow = {'submit': ('draft', 'in_review', _is_criteria_manager()), 'approve': ('in_review', 'approved', approver),
            'publish': ('approved', 'published', approver), 'retire': ('published', 'retired', approver)}
    if action not in flow:
        abort(404)
    current, target, allowed = flow[action]
    if not allowed:
        ap.deny('criteria_set', criteria_id, action)
        abort(403)
    if row.status != current:
        return _fail(wf.WorkflowError(f'ทำรายการนี้ไม่ได้ในสถานะ "{CRITERIA_LABELS.get(row.status)}"'), url_for('pilot.criteria'))
    if action == 'approve':
        if row.submitted_by == session['user_id']:
            return _fail(wf.WorkflowForbidden('ผู้ส่งตรวจอนุมัติชุดเกณฑ์ของตนเองไม่ได้'), url_for('pilot.criteria'))
        if len(note) < MIN_NOTE:
            return _fail(wf.WorkflowError('การอนุมัติต้องมีบันทึกอย่างน้อย 8 ตัวอักษร'), url_for('pilot.criteria'))
    row.status = target
    stamp = datetime.utcnow()
    if action == 'submit':
        row.submitted_by = session['user_id']
    elif action == 'approve':
        row.approved_by, row.approved_at, row.reviewed_by = session['user_id'], stamp, session['user_id']
    elif action == 'publish':
        row.published_by, row.published_at = session['user_id'], stamp
    if note:
        row.note = ((row.note + '\n') if row.note else '') + f'[{action}] {note[:1000]}'
    audit('criteria_' + action, 'criteria_set', row.id, f'{row.code}@{row.version}' + (' (DEMO)' if row.is_demo else ''))
    db.session.commit()
    flash(f'{CRITERIA_LABELS[target]}: {row.code} {row.version}' + (' (สภาพแวดล้อมสาธิต)' if row.is_demo else ''), 'success')
    return redirect(url_for('pilot.criteria'))


# ---------------------------------------------------------------- organizations (system admin)
@bp.route('/admin/organizations', methods=['GET', 'POST'])
@login_required(role='admin')
def organizations():
    if request.method == 'POST':
        code, name = request.form.get('code', '').strip()[:40], request.form.get('name', '').strip()[:255]
        org_type = request.form.get('org_type', 'other')
        parent = request.form.get('parent_id', type=int)
        if not code or not name or org_type not in ORG_TYPES or Organization.query.filter_by(code=code).first():
            flash('กรุณาระบุรหัสหน่วยงานที่ไม่ซ้ำ ชื่อ และประเภท', 'warning')
            return redirect(url_for('pilot.organizations'))
        row = Organization(code=code, name=name, name_en=request.form.get('name_en', '').strip()[:255] or None, org_type=org_type,
                           parent_id=parent if parent and db.session.get(Organization, parent) else None,
                           external_ref=request.form.get('external_ref', '').strip()[:60] or None, is_demo=current_app.config.get('DEMO_MODE', False))
        db.session.add(row)
        db.session.flush()
        audit('organization_create', 'organization', row.id, code)
        db.session.commit()
        flash('เพิ่มหน่วยงานแล้ว', 'success')
        return redirect(url_for('pilot.organizations'))
    orgs = Organization.query.order_by(Organization.org_type, Organization.name).all()
    members = OrganizationMembership.query.order_by(OrganizationMembership.organization_id, OrganizationMembership.role).all()
    return render_template('pilot/organizations.html', orgs=orgs, members=members, users=User.query.order_by(User.email).all(),
                           roles=MEMBERSHIP_ROLES, org_types=ORG_TYPE_LABELS, rules=ModelProcessingRule.query.order_by(ModelProcessingRule.provider, ModelProcessingRule.disclosure_class).all())


@bp.route('/admin/memberships', methods=['POST'])
@login_required(role='admin')
def membership_grant():
    user = db.session.get(User, request.form.get('user_id', type=int) or 0)
    org = db.session.get(Organization, request.form.get('organization_id', type=int) or 0)
    role = request.form.get('role', '')
    if user is None or org is None or role not in MEMBERSHIP_ROLES:
        abort(400)
    row = OrganizationMembership.query.filter_by(user_id=user.id, organization_id=org.id, role=role).first()
    if row is None:
        row = OrganizationMembership(user_id=user.id, organization_id=org.id, role=role)
        db.session.add(row)
    row.is_active, row.granted_by, row.revoked_at, row.revoked_by = True, session['user_id'], None, None
    row.can_read_source = request.form.get('can_read_source') == '1' and role in ap.OVERSIGHT_ROLES and role != 'executive'
    audit('permission_membership_grant', 'organization', org.id, f'{user.email}: {role}; read_source={row.can_read_source}')
    db.session.commit()
    flash('ให้สิทธิ์แล้ว', 'success')
    return redirect(url_for('pilot.organizations'))


@bp.route('/admin/memberships/<int:membership_id>/revoke', methods=['POST'])
@login_required(role='admin')
def membership_revoke(membership_id):
    row = db.session.get(OrganizationMembership, membership_id)
    if row is None:
        abort(404)
    row.is_active, row.revoked_at, row.revoked_by = False, datetime.utcnow(), session['user_id']
    audit('permission_membership_revoke', 'organization', row.organization_id, f'user={row.user_id}; {row.role}')
    db.session.commit()
    flash('ถอนสิทธิ์แล้ว', 'success')
    return redirect(url_for('pilot.organizations'))


@bp.route('/admin/model-rules/<int:rule_id>/toggle', methods=['POST'])
@login_required(role='admin')
def model_rule_toggle(rule_id):
    row = db.session.get(ModelProcessingRule, rule_id)
    if row is None:
        abort(404)
    row.is_active, row.updated_by = not row.is_active, session['user_id']
    audit('model_rule_' + ('enable' if row.is_active else 'disable'), 'model_processing_rule', row.id, f'{row.provider}/{row.disclosure_class}/{row.personal_data}')
    db.session.commit()
    return redirect(url_for('pilot.organizations') + '#rules')


@bp.route('/integrations')
@login_required()
def integrations():
    if session.get('role') != 'admin' and not ap.oversight_org_ids(role='round_coordinator'):
        abort(403)
    rows = IntegrationEndpoint.query.order_by(IntegrationEndpoint.code).all()
    return render_template('pilot/integrations.html', rows=rows, missing={r.code: json_loads(r.missing_json, default=[]) for r in rows},
                           encryption=current_app.config.get('ENCRYPTION_AT_REST_CONFIRMED', False))
