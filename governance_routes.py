"""V16 routes: portal, domains, taxonomy, guided assessment, evidence, registry and reports."""
import csv
import hashlib
import io
import os
import uuid
from datetime import datetime

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models import (ApplicabilityDecision, AuditLog, CommitteeAssignment, DocumentCheck, DocumentFile, DomainAssessment, DomainControl,
                    DomainFinding, EvidenceMapping, EvidenceRequirement, RegulatoryReference, Standard, TaxonomyNode, Template, User)
from services.applicability import IMPACT_ORDER, category_sensitivity
from services.domain_catalog import CORE_SUITES, get_pack, list_profiles, taxonomy_payload
from services.domain_kg import build_assessment_graph, finding_trace
from services.domain_orchestrator import (current_config, decisions_for, ensure_check, freeze, locate_requirements, mappings_by_requirement, recalculate,
                                          refresh_evidence_mappings, run_assessment)
from services.domain_rubric import REVIEWED, clamp_level
from services import access_policy as ap
from services import workflow as wf
from services.file_safety import inspect_pdf
from services.model_gate import DISCLOSURE_LABELS, PERSONAL_LABELS
from services.pdf_service import extract_pages_from_pdf
from utils import json_dumps, json_loads, login_required

bp = Blueprint('gov', __name__)
STEPS = [(1, 'องค์กรและ Domain'), (2, 'AI Use Case'), (3, 'กฎหมายและมาตรฐาน'), (4, 'Test Suite และ Control'), (5, 'หลักฐาน'), (6, 'ประเมินด้วย AI'), (7, 'ผลและรายงาน')]
IMPACT_LABELS = {'information': 'ให้ข้อมูลเท่านั้น', 'assistive': 'ช่วยงาน มนุษย์ตัดสินใจ', 'significant': 'มีผลต่อสิทธิหรือการตัดสินใจสำคัญ', 'safety_critical': 'มีผลต่อความปลอดภัยของชีวิต'}
LIFECYCLE = ['วางแผนและออกแบบ', 'พัฒนาและทดสอบ', 'นำร่อง', 'ใช้งานจริง', 'ปรับปรุงหรือยกเลิก']
STATUS_LABELS = {'draft': 'ฉบับร่าง', 'configured': 'กำลังดำเนินการ', 'pending_review': 'รอผู้ตรวจ', 'completed': 'เสร็จสิ้น'}
MAX_REVIEW_NOTE = 4000


def audit(action, target_type=None, target_id=None, detail=None):
    db.session.add(AuditLog(user_id=session.get('user_id'), actor_email=session.get('email'), action=action, target_type=target_type,
                            target_id=str(target_id) if target_id else None, detail=(detail or '')[:15000]))


def assessments_query(action=ap.VIEW_STATUS):
    """Authorization boundary for every list, count and search. Rules live in services/access_policy.py."""
    return ap.visible_assessments_query(action)


def is_owner(assessment):
    """The person may edit this work (legacy owner, or an editor of the owning organization in that context)."""
    return ap.EDIT in ap.assessment_permissions(assessment)


def can_review(assessment):
    """People who may confirm applicability or human review. An owner cannot certify their own assessment."""
    return ap.REVIEW in ap.assessment_permissions(assessment)


def get_assessment_or_403(assessment_id, need=ap.VIEW):
    assessment = db.session.get(DomainAssessment, assessment_id)
    if assessment is None:
        abort(404)
    if need not in ap.assessment_permissions(assessment):
        ap.deny('domain_assessment', assessment_id, need)
        abort(403)
    return assessment


def owner_or_403(assessment):
    """Edits need the edit right and a workflow state in which the organization holds the work."""
    if not is_owner(assessment):
        ap.deny('domain_assessment', assessment.id, ap.EDIT)
        abort(403)
    if not wf.org_can_modify(assessment):
        flash('งานนี้ส่งแล้วและอยู่ในขั้นทบทวน จึงแก้ไขไม่ได้จนกว่าจะถูกส่งกลับ', 'warning')
        abort(redirect(url_for('pilot.workflow', assessment_id=assessment.id)))


def standalone_checks(action=ap.VIEW):
    """Classic (pre-domain) checks the user may see, using the same policy as the classic pages."""
    linked = db.session.query(DomainAssessment.check_id).filter(DomainAssessment.check_id.isnot(None))
    query = DocumentCheck.query.filter(DocumentCheck.id.notin_(linked))
    role = session.get('role')
    if role == 'user':
        query = query.filter(db.or_(DocumentCheck.user_id == session['user_id'], DocumentCheck.organization_id.in_(ap.editor_org_ids() or [-1])))
    elif role == 'committee':
        checks = [a.check_id for a in CommitteeAssignment.query.filter_by(committee_user_id=session['user_id'], is_active=True).all()]
        query = query.filter(DocumentCheck.id.in_(checks or [-1]))
    return [c for c in query.order_by(DocumentCheck.created_at.desc()).all() if action in ap.check_permissions(c)]


def overview_stats():
    rows = assessments_query().all()
    summaries = [json_loads(a.summary_json, default={}) for a in rows]
    critical = sum(len((s.get('critical_gate') or {}).get('open') or []) for s in summaries)
    legacy = sum(1 for c in standalone_checks() if c.compliance_results_json)
    count = lambda status: sum(1 for a in rows if a.status == status)
    return {'active': count('configured'), 'draft': count('draft'), 'completed': count('completed'), 'legacy_completed': legacy,
            'pending_review': count('pending_review'), 'critical': critical}


def domain_cards():
    cards = []
    rows = assessments_query().all()
    core = DomainControl.query.filter_by(domain_slug='general', is_active=True).count()
    for profile in list_profiles(db.session):
        pack = json_loads(profile.payload_json, default={})
        own = DomainControl.query.filter_by(domain_slug=profile.slug, is_active=True).count()
        cards.append({'slug': profile.slug, 'title': profile.title, 'title_th': profile.title_th, 'icon': profile.icon, 'accent': profile.accent,
                      'summary_th': pack.get('summary_th'), 'org_types': [o['title_th'] for o in pack.get('organization_types', [])],
                      'key_concerns': pack.get('key_concerns', []), 'own_controls': own, 'core_controls': 0 if profile.slug == 'general' else core,
                      'assessments': sum(1 for a in rows if a.domain_slug == profile.slug), 'provisional': bool(pack.get('provisional_note_th'))})
    return cards


@bp.app_context_processor
def inject_v16():
    if not session.get('user_id'):
        return {}
    try:
        user = db.session.get(User, session['user_id'])
        pending = assessments_query().filter_by(status='pending_review').order_by(DomainAssessment.updated_at.desc()).limit(6).all()
        drafts = []
        if session.get('role') == 'user':
            drafts = assessments_query().filter(DomainAssessment.status.in_(('draft', 'configured'))).order_by(DomainAssessment.updated_at.desc()).limit(4).all()
        from models import Notification, Organization
        rows = ap.memberships()
        orgs = {o.id: o for o in Organization.query.filter(Organization.id.in_({m.organization_id for m in rows} or {-1})).all()}
        active = ap.active_org_id()
        unread = Notification.query.filter_by(user_id=session['user_id'], is_read=False).order_by(Notification.created_at.desc()).limit(8).all()
        return {'current_org': orgs[active].name if active in orgs else (user.organization if user else None), 'nav_profiles': list_profiles(db.session),
                'nav_pending': pending, 'nav_drafts': drafts, 'status_labels': STATUS_LABELS, 'nav_memberships': rows, 'nav_orgs': orgs,
                'active_org_id': active, 'nav_notifications': unread, 'pilot_roles': {m.role for m in rows},
                'demo_mode': current_app.config.get('DEMO_MODE', False)}
    except Exception:
        # A not-yet-migrated database must not take every page down.
        db.session.rollback()
        return {'current_org': None, 'nav_profiles': [], 'nav_pending': [], 'nav_drafts': [], 'status_labels': STATUS_LABELS,
                'nav_memberships': [], 'nav_orgs': {}, 'active_org_id': None, 'nav_notifications': [], 'pilot_roles': set(), 'demo_mode': False}


# ---------------------------------------------------------------- portal and domains
@bp.route('/overview')
@login_required()
def overview():
    recent = assessments_query().order_by(DomainAssessment.updated_at.desc()).limit(5).all()
    resume = next((a for a in recent if a.status in ('draft', 'configured') and is_owner(a)), None)
    return render_template('gov/overview.html', stats=overview_stats(), cards=domain_cards(), recent=recent, resume=resume)


@bp.route('/domains')
@login_required()
def domains():
    return render_template('gov/domains.html', cards=domain_cards())


@bp.route('/domains/<slug>')
@login_required()
def domain_detail(slug):
    pack = get_pack(db.session, slug)
    if pack is None:
        abort(404)
    general = get_pack(db.session, 'general') if slug != 'general' else None
    from services.domain_catalog import layer_packs
    layers = layer_packs(db.session, pack)
    refs = RegulatoryReference.query.filter_by(is_active=True).all()
    references = [r for r in refs if slug in json_loads(r.domains_json, default=[])]
    references.sort(key=lambda r: (r.normative_class, r.source_id))
    evidence = {e['id']: e for e in (general or {}).get('evidence_requirements', [])}
    for layer in layers:
        evidence.update({e['id']: e for e in layer['evidence_requirements']})
    evidence.update({e['id']: e for e in pack['evidence_requirements']})
    suites = []
    all_controls = pack['controls'] + [c for layer in layers for c in layer['controls']] + (general or {}).get('controls', [])
    for code, name in CORE_SUITES:
        suites.append({'code': code, 'name': name, 'focus': (pack.get('suite_focus') or {}).get(code), 'controls': [c for c in all_controls if code in c['suites']]})
    labels = {r.source_id: r for r in refs}
    return render_template('gov/domain_detail.html', pack=pack, general=general, references=references, evidence=evidence, suites=suites, reg_lookup=labels,
                           core_controls=[c for layer in layers for c in layer['controls']] + (general or {}).get('controls', []))


@bp.route('/taxonomy')
@login_required()
def taxonomy_home():
    first = next(iter(list_profiles(db.session)), None)
    return redirect(url_for('gov.taxonomy', slug=first.slug)) if first else redirect(url_for('gov.domains'))


@bp.route('/domains/<slug>/taxonomy')
@login_required()
def taxonomy(slug):
    pack = get_pack(db.session, slug)
    if pack is None:
        abort(404)
    return render_template('gov/taxonomy.html', pack=pack, slug=slug, suites=CORE_SUITES, profiles=list_profiles(db.session))


@bp.route('/api/taxonomy/<slug>')
@login_required()
def taxonomy_api(slug):
    if get_pack(db.session, slug) is None:
        return jsonify({'error': 'unknown domain'}), 404
    return jsonify(taxonomy_payload(db.session, slug))


# ---------------------------------------------------------------- assessment list and wizard
@bp.route('/assessments')
@login_required()
def assessments():
    query = assessments_query()
    domain = request.args.get('domain', '').strip()
    if domain:
        query = query.filter(DomainAssessment.domain_slug == domain)
    rows = query.order_by(DomainAssessment.updated_at.desc()).all()
    profiles = {p.slug: p for p in list_profiles(db.session)}
    return render_template('gov/assessments.html', rows=rows, domain_filter=domain, legacy=standalone_checks(), profiles=profiles,
                           summaries={a.id: json_loads(a.summary_json, default={}) for a in rows},
                           perms={a.id: ap.assessment_permissions(a) for a in rows}, wf_labels=wf.STATUS_LABELS)


def _validate_step1(form):
    slug = form.get('domain_slug', '').strip()
    pack = get_pack(db.session, slug)
    if pack is None:
        return None, 'กรุณาเลือก Domain'
    org_type = form.get('org_type', '').strip()
    if org_type not in {o['id'] for o in pack['organization_types']}:
        return None, 'กรุณาเลือกประเภทองค์กร'
    org = form.get('organization_name', '').strip()[:255]
    name = form.get('name', '').strip()[:255]
    if not org or not name:
        return None, 'กรุณาระบุชื่อองค์กรและชื่องานประเมิน'
    return {'slug': slug, 'org_type': org_type, 'organization_name': org, 'name': name, 'context': form.get('organization_context', '').strip()[:4000]}, None


@bp.route('/assessments/new', methods=['GET', 'POST'])
@login_required(role='user')
def assessment_new():
    if request.method == 'POST':
        data, error = _validate_step1(request.form)
        if error:
            flash(error, 'warning')
            return redirect(url_for('gov.assessment_new', domain=request.form.get('domain_slug', '')))
        org_id = ap.active_org_id() if ap.active_org_id() in ap.editor_org_ids() else None
        assessment = DomainAssessment(user_id=session['user_id'], domain_slug=data['slug'], name=data['name'], organization_name=data['organization_name'],
                                      organization_context=data['context'], profile_json=json_dumps({'org_type': data['org_type']}), status='draft', current_step=2,
                                      organization_id=org_id, created_by_id=session['user_id'], responsible_user_id=session['user_id'],
                                      workflow_status='draft' if org_id else None)
        db.session.add(assessment)
        db.session.flush()
        audit('domain_assessment_create', 'domain_assessment', assessment.id, f"domain={data['slug']}")
        db.session.commit()
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=2))
    user = db.session.get(User, session['user_id'])
    profiles = list_profiles(db.session)
    packs = {p.slug: json_loads(p.payload_json, default={}) for p in profiles}
    return render_template('gov/wizard.html', assessment=None, number=1, steps=STEPS, profiles=profiles, org_type_map={k: v.get('organization_types', []) for k, v in packs.items()}, profile={},
                           selected=request.args.get('domain', ''), default_org=user.organization if user else '', editable=True)


def _step_context(assessment, number):
    profile = json_loads(assessment.profile_json, default={})
    pack = get_pack(db.session, assessment.domain_slug, include_inactive=True)
    context = {'assessment': assessment, 'number': number, 'steps': STEPS, 'profile': profile, 'pack': pack,
               'editable': is_owner(assessment) and wf.org_can_modify(assessment) and not assessment.config_snapshot_json,
               'editable_evidence': is_owner(assessment) and wf.org_can_modify(assessment), 'wf_labels': wf.STATUS_LABELS,
               'disclosure_labels': DISCLOSURE_LABELS, 'personal_labels': PERSONAL_LABELS, 'supported_classes': current_app.config.get('SUPPORTED_DISCLOSURE_CLASSES', ()),
               'is_owner': is_owner(assessment), 'can_review': can_review(assessment), 'status_labels': STATUS_LABELS}
    if number == 1:
        profiles = list_profiles(db.session)
        context.update(profiles=profiles, org_type_map={p.slug: json_loads(p.payload_json, default={}).get('organization_types', []) for p in profiles}, selected=assessment.domain_slug, default_org=assessment.organization_name)
    if number == 2:
        context.update(impact_labels=IMPACT_LABELS, impact_order=IMPACT_ORDER, lifecycle=LIFECYCLE)
    if number in (3, 4, 5, 6):
        context['config'] = current_config(assessment)
    if number == 5:
        check = db.session.get(DocumentCheck, assessment.check_id) if assessment.check_id else None
        files = DocumentFile.query.filter_by(check_id=check.id).order_by(DocumentFile.id).all() if check else []
        located = {}
        if files:
            _, located = locate_requirements(assessment, context['config'])
            refresh_evidence_mappings(assessment, located)
            db.session.commit()
        mapped = mappings_by_requirement(assessment)
        attached = {f.content_hash for f in files if f.content_hash}
        reusable = []
        if is_owner(assessment):
            seen = set()
            for row in _reusable_files(assessment):
                key = row.content_hash or row.stored_filename
                if key in seen or row.check_id == assessment.check_id or (row.content_hash and row.content_hash in attached):
                    continue
                seen.add(key)
                reusable.append(row)
        sensitivity = category_sensitivity(pack.get('data_categories', []), profile.get('data_categories'))
        active = [c for c in context['config']['controls'] if c['final_status'] != 'not_applicable']
        references = {r['source_id']: r for r in context['config']['references']}
        requirement_links = {}
        for control in active:
            for requirement in control['evidence']:
                link = requirement_links.setdefault(requirement, {'controls': [], 'regulations': []})
                link['controls'].append(control['id'])
                for ref in control['references']:
                    title = (references.get(ref) or {}).get('title_th') or ref
                    if title not in link['regulations']:
                        link['regulations'].append(title)
        context.update(files=files, mapped=mapped, reusable=reusable[:30], sensitivity=sensitivity, force_confidential=sensitivity == 'sensitive', active_controls=active, requirement_links=requirement_links)
    if number == 6:
        mapped = mappings_by_requirement(assessment)
        active = [c for c in context['config']['controls'] if c['final_status'] != 'not_applicable']
        required = {e for c in active for e in c['evidence']}
        context.update(active_controls=active, required_count=len(required), located_count=len([r for r in required if mapped.get(r)]),
                       file_count=DocumentFile.query.filter_by(check_id=assessment.check_id).count() if assessment.check_id else 0)
    return context


@bp.route('/assessments/<int:assessment_id>')
@login_required()
def assessment_resume(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    if assessment.summary_json:
        return redirect(url_for('gov.results', assessment_id=assessment.id))
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=assessment.current_step or 1))


@bp.route('/assessments/<int:assessment_id>/step/<int:number>')
@login_required()
def step(assessment_id, number):
    assessment = get_assessment_or_403(assessment_id)
    if number == 7:
        return redirect(url_for('gov.results', assessment_id=assessment.id))
    if number not in (1, 2, 3, 4, 5, 6):
        abort(404)
    profile = json_loads(assessment.profile_json, default={})
    if number >= 3 and not profile.get('data_categories'):
        flash('กรุณากรอก AI Use Case และประเภทข้อมูลก่อน', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=2))
    if number >= 5 and not assessment.config_snapshot_json:
        flash('กรุณายืนยันขอบเขต Control ก่อนแนบหลักฐาน', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))
    return render_template('gov/wizard.html', **_step_context(assessment, number))


@bp.route('/assessments/<int:assessment_id>/step/1', methods=['POST'])
@login_required(role='user')
def save_step1(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    if assessment.config_snapshot_json:
        flash('ขอบเขตถูกยืนยันแล้ว ต้องปลดล็อกก่อนแก้ไข', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=1))
    data, error = _validate_step1(request.form)
    if error:
        flash(error, 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=1))
    profile = json_loads(assessment.profile_json, default={})
    if data['slug'] != assessment.domain_slug:
        # Selections from another domain are invalid under the new taxonomy.
        profile = {}
        ApplicabilityDecision.query.filter_by(assessment_id=assessment.id).delete()
    profile['org_type'] = data['org_type']
    assessment.domain_slug, assessment.name, assessment.organization_name, assessment.organization_context = data['slug'], data['name'], data['organization_name'], data['context']
    assessment.profile_json = json_dumps(profile)
    assessment.current_step = max(assessment.current_step or 1, 2)
    db.session.commit()
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=2))


@bp.route('/assessments/<int:assessment_id>/step/2', methods=['POST'])
@login_required(role='user')
def save_step2(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    if assessment.config_snapshot_json:
        flash('ขอบเขตถูกยืนยันแล้ว ต้องปลดล็อกก่อนแก้ไข', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=2))
    pack = get_pack(db.session, assessment.domain_slug)
    profile = json_loads(assessment.profile_json, default={})
    area = request.form.get('functional_area', '').strip()
    case = request.form.get('use_case', '').strip()
    categories = request.form.getlist('data_categories')
    impact = request.form.get('decision_impact', '').strip()
    valid_cats = {c['id'] for c in pack.get('data_categories', [])}
    org = profile.get('org_type')
    valid_areas = {a['id'] for a in pack['functional_areas'] if not a.get('org_types') or org in a['org_types']}
    errors = []
    if area and area not in valid_areas:
        errors.append('ภารกิจไม่อยู่ในประเภทองค์กรนี้')
    if case != 'custom' and case not in {u['id'] for u in pack['use_cases']}:
        errors.append('กรุณาเลือก AI Use Case')
    if case == 'custom' and not request.form.get('use_case_custom', '').strip():
        errors.append('กรุณาระบุชื่อ Use Case ใหม่')
    if not categories or set(categories) - valid_cats:
        errors.append('กรุณาเลือกประเภทข้อมูลอย่างน้อย 1 รายการ')
    if impact not in IMPACT_ORDER:
        errors.append('กรุณาเลือกผลต่อการตัดสินใจ')
    flags = {}
    for question in pack.get('profile_questions', []):
        answer = request.form.get('flag_' + question['id'], '')
        flags[question['id']] = True if answer == 'yes' else False if answer == 'no' else None
    profile.update(functional_area=area or None, use_case=None if case == 'custom' else case, use_case_custom=request.form.get('use_case_custom', '').strip()[:255] if case == 'custom' else None,
                   purpose=request.form.get('purpose', '').strip()[:2000], ai_users=request.form.get('ai_users', '').strip()[:1000], affected_persons=request.form.get('affected_persons', '').strip()[:1000],
                   data_categories=[c for c in categories if c in valid_cats], decision_impact=impact if impact in IMPACT_ORDER else None, lifecycle_stage=request.form.get('lifecycle_stage', '')[:60], flags=flags)
    assessment.profile_json = json_dumps(profile)
    if errors:
        db.session.commit()
        flash(' · '.join(errors), 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=2))
    assessment.current_step = max(assessment.current_step or 1, 3)
    db.session.commit()
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=3))


def _upsert_decision(assessment, target_type, target_id, **fields):
    row = ApplicabilityDecision.query.filter_by(assessment_id=assessment.id, target_type=target_type, target_id=target_id).first()
    if row is None:
        row = ApplicabilityDecision(assessment_id=assessment.id, target_type=target_type, target_id=target_id)
        db.session.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    row.decided_by, row.decided_by_email, row.decided_at = session['user_id'], session.get('email'), datetime.utcnow()
    return row


@bp.route('/assessments/<int:assessment_id>/regulations/<source_id>/decision', methods=['POST'])
@login_required()
def regulation_decision(assessment_id, source_id):
    assessment = get_assessment_or_403(assessment_id)
    if not can_review(assessment):
        abort(403)
    if assessment.config_snapshot_json:
        flash('ขอบเขตถูกยืนยันแล้ว ต้องปลดล็อกก่อนแก้ไข', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=3))
    reference = db.session.get(RegulatoryReference, source_id)
    if reference is None:
        abort(404)
    action = request.form.get('action')
    reason = request.form.get('reason', '').strip()[:1000]
    if len(reason) < 8:
        flash('กรุณาระบุเหตุผลอย่างน้อย 8 ตัวอักษร', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=3))
    if action == 'confirm':
        if reference.verification_status != 'expert_verified':
            flash('ยังยืนยันไม่ได้ เพราะแหล่งอ้างอิงนี้ยังไม่ผ่านการตรวจใน Regulatory Registry', 'warning')
            return redirect(url_for('gov.step', assessment_id=assessment.id, number=3))
        _upsert_decision(assessment, 'regulation', source_id, confirmed=True, override_status=None, reason=reason)
    elif action == 'exclude':
        _upsert_decision(assessment, 'regulation', source_id, confirmed=False, override_status='not_applicable', reason=reason)
    elif action == 'reset':
        _upsert_decision(assessment, 'regulation', source_id, confirmed=False, override_status=None, reason=reason)
    else:
        abort(400)
    audit('applicability_regulation_' + action, 'domain_assessment', assessment.id, f'{source_id}: {reason}')
    db.session.commit()
    flash('บันทึกการตัดสินใจแล้ว', 'success')
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=3))


@bp.route('/assessments/<int:assessment_id>/controls/<control_id>/override', methods=['POST'])
@login_required()
def control_override(assessment_id, control_id):
    assessment = get_assessment_or_403(assessment_id)
    if not can_review(assessment):
        abort(403)
    if assessment.config_snapshot_json:
        flash('ขอบเขตถูกยืนยันแล้ว ต้องปลดล็อกก่อนแก้ไข', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))
    status = request.form.get('status', '')
    reason = request.form.get('reason', '').strip()[:1000]
    known = {c['id'] for c in current_config(assessment)['controls']}
    if control_id not in known or status not in ('applicable', 'conditional', 'not_applicable', 'reset'):
        abort(400)
    if len(reason) < 8:
        flash('การเปลี่ยนขอบเขตต้องมีเหตุผลอย่างน้อย 8 ตัวอักษร', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))
    _upsert_decision(assessment, 'control', control_id, override_status=None if status == 'reset' else status, reason=reason)
    audit('applicability_control_override', 'domain_assessment', assessment.id, f'{control_id} -> {status}: {reason}')
    db.session.commit()
    flash(f'บันทึกการเปลี่ยนขอบเขตของ {control_id} แล้ว', 'success')
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))


@bp.route('/assessments/<int:assessment_id>/freeze', methods=['POST'])
@login_required(role='user')
def assessment_freeze(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    try:
        freeze(assessment)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))
    audit('domain_assessment_freeze', 'domain_assessment', assessment.id, f'hash={assessment.snapshot_hash}')
    db.session.commit()
    flash('ยืนยันขอบเขตแล้ว ระบบล็อกเกณฑ์ไว้สำหรับ Assessment นี้', 'success')
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=5))


@bp.route('/assessments/<int:assessment_id>/unfreeze', methods=['POST'])
@login_required(role='user')
def assessment_unfreeze(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    if DomainFinding.query.filter_by(assessment_id=assessment.id).first():
        flash('มีผลประเมินแล้ว จึงปลดล็อกไม่ได้ เพื่อรักษาความสอดคล้องของผล ให้สร้าง Assessment ใหม่แทน', 'warning')
        return redirect(url_for('gov.results', assessment_id=assessment.id))
    assessment.config_snapshot_json, assessment.snapshot_hash, assessment.frozen_at = None, None, None
    assessment.status, assessment.current_step = 'draft', 4
    audit('domain_assessment_unfreeze', 'domain_assessment', assessment.id)
    db.session.commit()
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))


# ---------------------------------------------------------------- evidence
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reusable_files(assessment):
    """Files the user may copy into this assessment: readable by the user and from the same organization scope."""
    readable = set(ap.visible_check_ids_with(ap.READ_SOURCE))
    query = DocumentFile.query.join(DocumentCheck, DocumentFile.check_id == DocumentCheck.id).filter(DocumentCheck.id.in_(readable or {-1}))
    if assessment.organization_id:
        query = query.filter(DocumentCheck.organization_id == assessment.organization_id)
    else:
        query = query.filter(DocumentCheck.organization_id.is_(None), DocumentCheck.user_id == session['user_id'])
    return query.order_by(DocumentFile.id.desc()).all()


def _save_pdf(storage):
    """Save a verified PDF under a random name. Raises ValueError if it is not a safe, readable PDF."""
    problems = inspect_pdf(storage.stream, current_app.config.get('MAX_PDF_PAGES', 400))
    if problems:
        raise ValueError(' · '.join(problems))
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    name = f'{uuid.uuid4().hex}.pdf'
    path = os.path.join(folder, name)
    storage.save(path)
    try:
        pages = extract_pages_from_pdf(path)
    except Exception as exc:
        os.remove(path)
        raise ValueError('เปิดไฟล์ PDF ไม่ได้ อาจเสียหรือมีรหัสผ่าน') from exc
    return name, path, pages


def _attach(check, source_name, stored, pages, digest, labels=None):
    text = '\n'.join(p.get('text', '') for p in pages)
    labels = labels or {}
    row = DocumentFile(check_id=check.id, original_filename=source_name[:255], stored_filename=stored, content_hash=digest, page_count=len(pages),
                       extracted_text=text[:700000], pages_json=json_dumps(pages)[:4000000],
                       disclosure_class=labels.get('disclosure_class'), personal_data=labels.get('personal_data'), is_redacted=labels.get('is_redacted'),
                       classified_by=session.get('user_id') if labels else None, classified_at=datetime.utcnow() if labels else None)
    db.session.add(row)
    if not check.stored_filename:
        check.stored_filename = stored
    return row


@bp.route('/assessments/<int:assessment_id>/classification', methods=['POST'])
@login_required(role='user')
def set_classification(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    value = request.form.get('data_classification', '')
    config = current_config(assessment)
    pack = get_pack(db.session, assessment.domain_slug, include_inactive=True)
    sensitive = category_sensitivity(pack.get('data_categories', []), (config.get('profile') or {}).get('data_categories')) == 'sensitive'
    if value not in ('open', 'confidential') or request.form.get('acknowledged') != value:
        flash('กรุณาเลือกระดับเอกสารและกดรับทราบ', 'warning')
    elif value == 'open' and sensitive:
        flash('Assessment นี้ใช้ข้อมูลอ่อนไหว จึงต้องเป็น Confidential และใช้โมเดลภายในเท่านั้น', 'danger')
    elif value == 'open' and _has_confidential_source(assessment):
        flash('มีหลักฐานจากงานระดับ Confidential จึงเปลี่ยนเป็น Open ไม่ได้', 'danger')
    else:
        assessment.data_classification = value
        check = ensure_check(assessment, config)
        check.data_classification = value
        audit('domain_assessment_classification', 'domain_assessment', assessment.id, value)
        db.session.commit()
        flash('บันทึกระดับเอกสารแล้ว', 'success')
    return redirect(url_for('gov.step', assessment_id=assessment.id, number=5))


def _has_confidential_source(assessment):
    if not assessment.check_id:
        return False
    for row in DocumentFile.query.filter_by(check_id=assessment.check_id).all():
        if not row.content_hash:
            continue
        for other in DocumentFile.query.filter_by(content_hash=row.content_hash).all():
            source = db.session.get(DocumentCheck, other.check_id)
            if source and source.id != assessment.check_id and source.user_id == assessment.user_id and source.data_classification == 'confidential':
                return True
    return False


def _protection_labels(form, required):
    """Read the three document-protection facts. Unsupported classes are refused before the file is stored."""
    disclosure = form.get('disclosure_class', '').strip()
    personal = form.get('personal_data', '').strip()
    redacted = form.get('is_redacted') == '1'
    if not disclosure and not required:
        return None, None
    if disclosure not in DISCLOSURE_LABELS or personal not in PERSONAL_LABELS or personal == 'redacted':
        return None, 'กรุณาระบุชั้นข้อมูลของเอกสารและการมีข้อมูลส่วนบุคคล'
    if disclosure == 'secret' or disclosure not in (current_app.config.get('SUPPORTED_DISCLOSURE_CLASSES') or ()):
        return None, f'สภาพแวดล้อมนี้ยังไม่รองรับเอกสารชั้น "{DISCLOSURE_LABELS[disclosure]}" จึงไม่รับไฟล์'
    return {'disclosure_class': disclosure, 'personal_data': personal, 'is_redacted': redacted}, None


@bp.route('/assessments/<int:assessment_id>/evidence', methods=['POST'])
@login_required(role='user')
def upload_evidence(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    target = url_for('gov.step', assessment_id=assessment.id, number=5)
    if not assessment.config_snapshot_json:
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=4))
    if not assessment.data_classification:
        flash('กรุณาเลือกระดับเอกสารก่อนอัปโหลด', 'warning')
        return redirect(target)
    files = [f for f in request.files.getlist('pdf_files') if f and f.filename]
    if not files:
        flash('กรุณาเลือกไฟล์ PDF', 'warning')
        return redirect(target)
    labels, error = _protection_labels(request.form, required=assessment.organization_id is not None)
    if error:
        flash(error, 'danger')
        return redirect(target)
    check = ensure_check(assessment)
    added, duplicate, failed = 0, 0, []
    attached = {f.content_hash for f in DocumentFile.query.filter_by(check_id=check.id).all() if f.content_hash}
    for storage in files:
        if not storage.filename.lower().endswith('.pdf'):
            failed.append(f'{storage.filename}: รองรับเฉพาะ PDF')
            continue
        try:
            stored, path, pages = _save_pdf(storage)
        except ValueError as exc:
            failed.append(f'{storage.filename}: {exc}')
            continue
        digest = _sha256(path)
        if digest in attached:
            os.remove(path)
            duplicate += 1
            continue
        same = DocumentFile.query.join(DocumentCheck, DocumentFile.check_id == DocumentCheck.id).filter(DocumentCheck.user_id == session['user_id'], DocumentFile.content_hash == digest).first()
        if same and os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], same.stored_filename)):
            os.remove(path)
            stored = same.stored_filename
        _attach(check, storage.filename, stored, pages, digest, labels)
        attached.add(digest)
        added += 1
    check.extracted_text = '\n'.join((f.extracted_text or '') for f in DocumentFile.query.filter_by(check_id=check.id).all())[:1200000]
    audit('domain_evidence_upload', 'domain_assessment', assessment.id, f'added={added}; duplicate={duplicate}; failed={len(failed)}')
    db.session.commit()
    if added:
        flash(f'เพิ่มหลักฐาน {added} ไฟล์', 'success')
    if duplicate:
        flash(f'ข้ามไฟล์ซ้ำ {duplicate} ไฟล์', 'info')
    for message in failed:
        flash(message, 'danger')
    return redirect(target)


@bp.route('/assessments/<int:assessment_id>/evidence/reuse', methods=['POST'])
@login_required(role='user')
def reuse_evidence(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    target = url_for('gov.step', assessment_id=assessment.id, number=5)
    if not assessment.data_classification:
        flash('กรุณาเลือกระดับเอกสารก่อน', 'warning')
        return redirect(target)
    source = db.session.get(DocumentFile, request.form.get('file_id', type=int) or 0)
    if source is None:
        abort(404)
    source_check = db.session.get(DocumentCheck, source.check_id)
    if source_check is None or source.id not in {f.id for f in _reusable_files(assessment)}:
        ap.deny('document_file', source.id, ap.READ_SOURCE)
        abort(403)
    if assessment.data_classification == 'open' and source_check.data_classification == 'confidential':
        flash('ไฟล์นี้มาจากงานระดับ Confidential จึงใช้กับ Assessment ระดับ Open ไม่ได้', 'danger')
        return redirect(target)
    check = ensure_check(assessment)
    digest = source.content_hash
    if not digest:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], source.stored_filename)
        digest = _sha256(path) if os.path.exists(path) else None
        source.content_hash = digest
    if digest and DocumentFile.query.filter_by(check_id=check.id, content_hash=digest).first():
        flash('ไฟล์นี้อยู่ใน Assessment แล้ว', 'info')
        return redirect(target)
    db.session.add(DocumentFile(check_id=check.id, original_filename=source.original_filename, stored_filename=source.stored_filename, content_hash=digest,
                                page_count=source.page_count, extracted_text=source.extracted_text, pages_json=source.pages_json,
                                disclosure_class=source.disclosure_class, personal_data=source.personal_data, is_redacted=source.is_redacted,
                                classified_by=source.classified_by, classified_at=source.classified_at))
    audit('domain_evidence_reuse', 'domain_assessment', assessment.id, f'source_file={source.id}')
    db.session.commit()
    flash('นำหลักฐานเดิมมาใช้แล้ว', 'success')
    return redirect(target)


@bp.route('/assessments/<int:assessment_id>/evidence/map', methods=['POST'])
@login_required(role='user')
def map_evidence(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    target = url_for('gov.step', assessment_id=assessment.id, number=5)
    requirement = request.form.get('requirement_id', '')
    file_id = request.form.get('file_id', type=int)
    page = request.form.get('page', type=int)
    config = current_config(assessment)
    row = db.session.get(DocumentFile, file_id or 0)
    if requirement not in config['evidence_requirements'] or row is None or row.check_id != assessment.check_id:
        abort(400)
    if page is not None and not 1 <= page <= max(row.page_count or 1, 1):
        flash('เลขหน้าไม่อยู่ในไฟล์', 'warning')
        return redirect(target)
    db.session.add(EvidenceMapping(assessment_id=assessment.id, requirement_id=requirement, document_file_id=row.id, page=page,
                                   snippet=request.form.get('note', '').strip()[:1000], matched_keywords_json='[]', relevance=100.0, source='manual', created_by=session['user_id']))
    audit('domain_evidence_map', 'domain_assessment', assessment.id, f'{requirement} <- file {row.id}')
    db.session.commit()
    flash('เชื่อมหลักฐานกับข้อกำหนดแล้ว', 'success')
    return redirect(target)


@bp.route('/evidence')
@login_required()
def evidence_library():
    readable = ap.visible_check_ids_with(ap.READ_SOURCE)
    query = DocumentFile.query.filter(DocumentFile.check_id.in_(readable or [-1]))
    term = request.args.get('q', '').strip()
    if term:
        query = query.filter(DocumentFile.original_filename.ilike('%' + term.replace('%', r'\%').replace('_', r'\_') + '%', escape='\\'))
    rows = query.order_by(DocumentFile.id.desc()).limit(200).all()
    checks = {c.id: c for c in DocumentCheck.query.filter(DocumentCheck.id.in_({r.check_id for r in rows})).all()} if rows else {}
    usage = {}
    if rows:
        for mapping in EvidenceMapping.query.filter(EvidenceMapping.document_file_id.in_([r.id for r in rows])).all():
            usage.setdefault(mapping.document_file_id, set()).add(mapping.requirement_id)
    return render_template('gov/evidence.html', rows=rows, checks=checks, usage=usage, term=term)


# ---------------------------------------------------------------- run and results
@bp.route('/assessments/<int:assessment_id>/run', methods=['POST'])
@login_required(role='user')
def run(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    owner_or_403(assessment)
    if not assessment.config_snapshot_json or not assessment.data_classification:
        flash('กรุณายืนยันขอบเขตและเลือกระดับเอกสารก่อน', 'warning')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=5))
    try:
        run_assessment(assessment, include_core=request.form.get('include_core') == '1')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('gov.step', assessment_id=assessment.id, number=6))
    audit('domain_assessment_run', 'domain_assessment', assessment.id, f'classification={assessment.data_classification}; note={assessment.run_note}')
    db.session.commit()
    flash('ประเมินเสร็จแล้ว', 'success')
    return redirect(url_for('gov.results', assessment_id=assessment.id))


def _result_context(assessment):
    config = current_config(assessment)
    summary = json_loads(assessment.summary_json, default={})
    findings = DomainFinding.query.filter_by(assessment_id=assessment.id).all()
    controls = {c['id']: c for c in config['controls']}
    graph = build_assessment_graph(assessment, config)
    mapped = mappings_by_requirement(assessment)
    rows = []
    for finding in sorted(findings, key=lambda f: (f.state == 'not_applicable', not f.critical, f.control_id)):
        control = controls.get(finding.control_id, {})
        trace = finding_trace(graph, finding.control_id, assessment.id)
        rows.append({'finding': finding, 'control': control, 'trace': trace,
                     'requirements': [{'id': r, 'title': config['evidence_requirements'].get(r, {}).get('title_th', r), 'why': config['evidence_requirements'].get(r, {}).get('why_th'), 'evidence': mapped.get(r, [])} for r in control.get('evidence', [])]})
    return {'assessment': assessment, 'config': config, 'summary': summary, 'rows': rows, 'can_review': can_review(assessment) and (not wf.in_workflow(assessment) or assessment.workflow_status in wf.REVIEWING_STATES),
            'is_owner': is_owner(assessment), 'steps': STEPS, 'number': 7, 'check': assessment.check, 'in_workflow': wf.in_workflow(assessment),
            'wf_labels': wf.STATUS_LABELS, 'judgement_labels': wf.JUDGEMENTS, 'can_read_source': ap.READ_SOURCE in ap.assessment_permissions(assessment)}


@bp.route('/assessments/<int:assessment_id>/results')
@login_required()
def results(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    if not assessment.summary_json:
        flash('ยังไม่มีผลประเมิน', 'info')
        return redirect(url_for('gov.assessment_resume', assessment_id=assessment.id)) if assessment.current_step < 7 else redirect(url_for('gov.step', assessment_id=assessment.id, number=6))
    return render_template('gov/results.html', **_result_context(assessment))


@bp.route('/assessments/<int:assessment_id>/findings/<int:finding_id>/review', methods=['POST'])
@login_required()
def review_finding(assessment_id, finding_id):
    assessment = get_assessment_or_403(assessment_id)
    if not can_review(assessment):
        abort(403)
    finding = db.session.get(DomainFinding, finding_id)
    if finding is None or finding.assessment_id != assessment.id:
        abort(404)
    if finding.state == 'not_applicable':
        abort(400)
    if wf.in_workflow(assessment) and assessment.workflow_status not in wf.REVIEWING_STATES:
        flash('บันทึกผลตรวจได้เมื่องานอยู่ระหว่างทบทวนเท่านั้น', 'warning')
        return redirect(url_for('gov.results', assessment_id=assessment.id))
    level = clamp_level(request.form.get('level'))
    note = request.form.get('note', '').strip()[:MAX_REVIEW_NOTE]
    stance = request.form.get('stance', 'supported')
    if level is None or stance not in ('supported', 'contradicted'):
        abort(400)
    if level != finding.proposed_level and len(note) < 8:
        flash('การเปลี่ยนระดับจากที่ระบบเสนอต้องมีเหตุผลอย่างน้อย 8 ตัวอักษร', 'warning')
        return redirect(url_for('gov.results', assessment_id=assessment.id))
    finding.human_level, finding.human_note, finding.human_stance, finding.level = level, note, stance, level
    finding.state, finding.confidence = REVIEWED, 'high'
    finding.reviewed_by, finding.reviewed_by_email, finding.reviewed_at = session['user_id'], session.get('email'), datetime.utcnow()
    db.session.flush()
    recalculate(assessment)
    audit('domain_finding_review', 'domain_assessment', assessment.id, f'{finding.control_id}: level={level}; stance={stance}')
    db.session.commit()
    flash(f'บันทึกผลตรวจ {finding.control_id} แล้ว', 'success')
    return redirect(url_for('gov.results', assessment_id=assessment.id))


@bp.route('/assessments/<int:assessment_id>/report')
@login_required()
def report(assessment_id):
    assessment = get_assessment_or_403(assessment_id)
    if not assessment.summary_json:
        abort(404)
    context = _result_context(assessment)
    audit('domain_report_view', 'domain_assessment', assessment.id)
    db.session.commit()
    return render_template('gov/report_print.html', generated_at=datetime.utcnow(), **context)


def _export_rows(assessment):
    context = _result_context(assessment)
    overlay = {}
    for suite in context['config'].get('domain_suites') or []:
        for section in suite.get('sections', []):
            for cid in section.get('control_ids', []):
                overlay.setdefault(cid, []).append(suite['id'])
    for row in context['rows']:
        finding, control = row['finding'], row['control']
        extra = {'domain_suites': ' '.join(dict.fromkeys(overlay.get(finding.control_id, []))), 'judgement': finding.judgement,
                 'control_status': control.get('control_status', '')} if overlay else {}
        yield {**extra, 'control_id': finding.control_id, 'title': control.get('title_th') or control.get('title'), 'suites': ' '.join(control.get('suites', [])), 'critical': finding.critical,
               'state': finding.state, 'level': finding.level, 'coverage_ratio': finding.coverage_ratio, 'confidence': finding.confidence, 'compliance_status': finding.compliance_status,
               'reason': finding.reason, 'gap': finding.gap, 'recommendation': finding.recommendation, 'reviewed_by': finding.reviewed_by_email,
               'evidence': '; '.join(f"{e.get('label')}" for e in row['trace']['evidence']), 'regulations': '; '.join(r['label'] for r in row['trace']['regulations'])}


@bp.route('/assessments/<int:assessment_id>/report.csv')
@login_required()
def report_csv(assessment_id):
    assessment = get_assessment_or_403(assessment_id, ap.EXPORT)
    buffer = io.StringIO()
    writer = None
    for row in _export_rows(assessment):
        if writer is None:
            writer = csv.DictWriter(buffer, fieldnames=list(row))
            writer.writeheader()
        # A leading formula character is neutralized so a spreadsheet will not execute evidence text.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in '=+-@' else v) for k, v in row.items()})
    audit('domain_report_export', 'domain_assessment', assessment.id, 'csv')
    db.session.commit()
    return Response('﻿' + buffer.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=eigda_assessment_{assessment.id}.csv'})


@bp.route('/assessments/<int:assessment_id>/report.pdf')
@login_required()
def report_pdf(assessment_id):
    from services.assessment_pdf import build_html, render_pdf
    assessment = get_assessment_or_403(assessment_id, ap.EXPORT)
    if not assessment.summary_json:
        flash('ยังไม่มีผลประเมินให้ส่งออก', 'info')
        return redirect(url_for('gov.assessment_resume', assessment_id=assessment.id))
    data = render_pdf(build_html(_result_context(assessment), demo=current_app.config.get('DEMO_MODE', False)), title=assessment.name)
    audit('domain_report_export', 'domain_assessment', assessment.id, 'pdf')
    db.session.commit()
    return Response(data, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename=eigda_assessment_{assessment.id}.pdf'})


@bp.route('/assessments/<int:assessment_id>/report.json')
@login_required()
def report_json(assessment_id):
    assessment = get_assessment_or_403(assessment_id, ap.EXPORT)
    audit('domain_report_export', 'domain_assessment', assessment.id, 'json')
    db.session.commit()
    return jsonify({'assessment_id': assessment.id, 'name': assessment.name, 'domain': assessment.domain_slug, 'pack_version': assessment.pack_version,
                    'snapshot_hash': assessment.snapshot_hash, 'scoring_version': assessment.scoring_version, 'summary': json_loads(assessment.summary_json, default={}), 'findings': list(_export_rows(assessment))})


@bp.route('/assessments/<int:assessment_id>/kg.json')
@login_required()
def assessment_kg(assessment_id):
    assessment = get_assessment_or_403(assessment_id, ap.EXPORT)
    audit('domain_report_export', 'domain_assessment', assessment.id, 'kg.json')
    db.session.commit()
    return jsonify(build_assessment_graph(assessment, current_config(assessment)))


# ---------------------------------------------------------------- registry, reports, search
@bp.route('/regulations')
@login_required()
def regulations():
    rows = RegulatoryReference.query.filter_by(is_active=True).order_by(RegulatoryReference.normative_class, RegulatoryReference.source_id).all()
    domain = request.args.get('domain', '')
    if domain:
        rows = [r for r in rows if domain in json_loads(r.domains_json, default=[])]
    return render_template('gov/regulations.html', rows=rows, profiles=list_profiles(db.session), domain=domain,
                           standards=Standard.query.count(), test_suites=Template.query.count())


@bp.route('/regulations/<source_id>/verify', methods=['POST'])
@login_required(role='admin')
def verify_regulation(source_id):
    reference = db.session.get(RegulatoryReference, source_id)
    if reference is None:
        abort(404)
    note = request.form.get('note', '').strip()[:1000]
    action = request.form.get('action')
    if len(note) < 8:
        flash('กรุณาระบุแหล่งที่ตรวจและเหตุผล อย่างน้อย 8 ตัวอักษร', 'warning')
        return redirect(url_for('gov.regulations'))
    if action == 'verify':
        reference.verification_status = 'expert_verified'
        reference.verified_by, reference.verified_at = session.get('email'), datetime.utcnow()
    elif action == 'revoke':
        reference.verification_status = 'pending_verification'
        reference.verified_by, reference.verified_at = None, None
    else:
        abort(400)
    reference.verification_note = note
    audit('regulation_' + action, 'regulatory_reference', source_id, note)
    db.session.commit()
    flash('บันทึกสถานะแหล่งอ้างอิงแล้ว', 'success')
    return redirect(url_for('gov.regulations'))


@bp.route('/reports')
@login_required()
def reports():
    rows = assessments_query().filter(DomainAssessment.summary_json.isnot(None)).order_by(DomainAssessment.updated_at.desc()).all()
    return render_template('gov/reports.html', rows=rows, summaries={a.id: json_loads(a.summary_json, default={}) for a in rows}, profiles={p.slug: p for p in list_profiles(db.session)})


@bp.route('/search')
@login_required()
def search():
    term = request.args.get('q', '').strip()
    results = {'assessments': [], 'controls': [], 'regulations': [], 'taxonomy': []}
    if len(term) >= 2:
        like = '%' + term.replace('%', r'\%').replace('_', r'\_') + '%'
        results['assessments'] = assessments_query().filter(db.or_(DomainAssessment.name.ilike(like, escape='\\'), DomainAssessment.organization_name.ilike(like, escape='\\'))).limit(20).all()
        results['controls'] = DomainControl.query.filter(DomainControl.is_active == True, db.or_(DomainControl.control_id.ilike(like, escape='\\'), DomainControl.title.ilike(like, escape='\\'), DomainControl.title_th.ilike(like, escape='\\'))).limit(20).all()
        results['regulations'] = RegulatoryReference.query.filter(RegulatoryReference.is_active == True, db.or_(RegulatoryReference.title.ilike(like, escape='\\'), RegulatoryReference.title_th.ilike(like, escape='\\'), RegulatoryReference.source_id.ilike(like, escape='\\'))).limit(20).all()
        results['taxonomy'] = TaxonomyNode.query.filter(TaxonomyNode.is_active == True, TaxonomyNode.node_type.in_(('use_case', 'functional_area', 'org_type', 'dimension')), db.or_(TaxonomyNode.title.ilike(like, escape='\\'), TaxonomyNode.title_th.ilike(like, escape='\\'))).limit(20).all()
    return render_template('gov/search.html', term=term, results=results)


# ---------------------------------------------------------------------------
# 3D Knowledge Graph explorer for Test Suites (read-only catalog view)
# ---------------------------------------------------------------------------
def _selected_suite_ids(suites):
    valid = {s.id for s in suites}
    chosen = [i for i in request.args.getlist('suite', type=int) if i in valid]
    return chosen or ([suites[0].id] if suites else [])


@bp.route('/test-suites/graph')
@login_required()
def suite_graph():
    if session.get('role') not in ('user', 'admin'):
        abort(403)
    from services.suite_graph import enabled_suites
    suites = enabled_suites()
    chosen = _selected_suite_ids(suites)
    return render_template('gov/suite_graph.html', suites=suites, chosen=chosen,
                           show_keywords=request.args.get('keywords', '1') != '0')


@bp.route('/test-suites/graph.json')
@login_required()
def suite_graph_json():
    if session.get('role') not in ('user', 'admin'):
        abort(403)
    from services.suite_graph import build_suite_graph, enabled_suites
    suites = enabled_suites()
    return jsonify(build_suite_graph(_selected_suite_ids(suites),
                                     include_keywords=request.args.get('keywords', '1') != '0'))


# ---------------------------------------------------------------------------
# Domain dashboard (config-driven: any pack, e.g. administrative_court) and SILA test-pack specification
# ---------------------------------------------------------------------------
@bp.route('/domains/<slug>/dashboard')
@login_required()
def domain_dashboard(slug):
    from collections import Counter
    from services.domain_catalog import read_sila_pack
    pack = get_pack(db.session, slug)
    if pack is None:
        abort(404)
    rows = [a for a in assessments_query(ap.VIEW).filter(DomainAssessment.domain_slug == slug).order_by(DomainAssessment.updated_at.desc()).all()
            if ap.VIEW in ap.assessment_permissions(a)]
    assessed = [a for a in rows if a.summary_json]
    summaries = {a.id: json_loads(a.summary_json, default={}) for a in assessed}
    gaps, critical = Counter(), []
    for a in assessed[:20]:
        config = current_config(a)
        mapped = mappings_by_requirement(a)
        for control in config['controls']:
            if control['final_status'] == 'not_applicable':
                continue
            for req in control['evidence']:
                if not mapped.get(req):
                    gaps[(config['evidence_requirements'].get(req) or {}).get('title_th') or req] += 1
        for cid in (summaries[a.id].get('critical_gate') or {}).get('open') or []:
            critical.append({'assessment': a, 'control_id': cid})
    coverage = [summaries[a.id].get('evidence_coverage_percent') for a in assessed if summaries[a.id].get('evidence_coverage_percent') is not None]
    maturity = [summaries[a.id].get('maturity_percent') for a in assessed if summaries[a.id].get('maturity_percent') is not None]
    refs = [r for r in RegulatoryReference.query.filter_by(is_active=True).all() if slug in json_loads(r.domains_json, default=[])]
    ref_status = Counter(r.verification_status for r in refs)
    sila = read_sila_pack(pack.get('sila_test_pack'))
    latest = assessed[0] if assessed else None
    return render_template('gov/domain_dashboard.html', pack=pack, rows=rows, assessed=assessed, summaries=summaries, latest=latest,
                           latest_summary=summaries.get(latest.id) if latest else None, gaps=gaps.most_common(10), critical=critical,
                           avg_coverage=round(sum(coverage) / len(coverage), 1) if coverage else None,
                           avg_maturity=round(sum(maturity) / len(maturity), 1) if maturity else None,
                           refs=refs, ref_status=ref_status, sila=sila, status_only=assessments_query().filter(DomainAssessment.domain_slug == slug).count() - len(rows))


@bp.route('/api/sila/test-packs/<slug>')
@login_required()
def sila_test_pack(slug):
    """Specification only. There is no SILA system connected, so no results are returned or invented."""
    from services.domain_catalog import read_sila_pack
    pack = get_pack(db.session, slug)
    sila = read_sila_pack((pack or {}).get('sila_test_pack'))
    if sila is None:
        return jsonify({'error': 'no SILA test pack for this domain'}), 404
    return jsonify({**sila, 'integration_status': 'not_connected', 'results': []})
