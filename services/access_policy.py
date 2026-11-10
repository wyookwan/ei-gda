"""One authorization rule set for every entry point: V16 pages, legacy pages, files, exports and APIs.

Two scopes exist side by side:

* Legacy scope (organization_id IS NULL). The rule that applied before the pilot is kept unchanged:
  the owner, an admin, or a committee member with an active assignment.
  Legacy work is never moved into an organization by inference, for example from the
  organization name typed into a form.
* Organization scope. Members of the owning organization edit and read their own work.
  An assigned committee member reviews it while the assignment is active. A round
  coordinator sees status and assigns reviewers; reading originals needs the separate
  `can_read_source` grant. Executives see status only. A system admin manages accounts
  and settings, and does not read evidence by role.

Callers ask for an action and get True or False. Routes must not re-implement these rules.
"""
from flask import g, has_request_context, session

from extensions import db

VIEW_STATUS, VIEW, READ_SOURCE, EDIT, REVIEW, EXPORT, ASSIGN = 'view_status', 'view', 'read_source', 'edit', 'review', 'export', 'assign'
EDITOR_ROLES = ('org_coordinator', 'org_staff')
OVERSIGHT_ROLES = ('round_coordinator', 'executive')


def _uid():
    return session.get('user_id') if has_request_context() else None


def _role():
    return session.get('role') if has_request_context() else None


def memberships(user_id=None):
    """Active memberships of a user, cached for the request."""
    from models import OrganizationMembership
    user_id = user_id or _uid()
    if not user_id:
        return []
    cache = g.setdefault('_memberships', {}) if has_request_context() else {}
    if user_id not in cache:
        cache[user_id] = OrganizationMembership.query.filter_by(user_id=user_id, is_active=True).all()
    return cache[user_id]


def org_roles(org_id, user_id=None):
    return {m.role for m in memberships(user_id) if m.organization_id == org_id}


def editor_org_ids(user_id=None):
    return sorted({m.organization_id for m in memberships(user_id) if m.role in EDITOR_ROLES})


def oversight_org_ids(user_id=None, role=None):
    roles = (role,) if role else OVERSIGHT_ROLES
    direct = {m.organization_id for m in memberships(user_id) if m.role in roles}
    return sorted(direct | _child_org_ids(direct))


def _child_org_ids(org_ids):
    """An oversight grant at the ministry level also covers its offices (one level is enough for the pilot)."""
    from models import Organization
    if not org_ids:
        return set()
    return {o.id for o in Organization.query.filter(Organization.parent_id.in_(org_ids)).all()}


def can_read_source_in(org_id, user_id=None):
    return any(m.organization_id == org_id and m.role in OVERSIGHT_ROLES and m.can_read_source for m in memberships(user_id))


def active_org_id():
    """The organization the user chose to work in. Must still be an active membership."""
    org_id = session.get('org_id') if has_request_context() else None
    if org_id and any(m.organization_id == org_id for m in memberships()):
        return org_id
    return None


def has_active_assignment(check_id, user_id=None):
    from models import CommitteeAssignment
    user_id = user_id or _uid()
    if not check_id or not user_id:
        return False
    return CommitteeAssignment.query.filter_by(check_id=check_id, committee_user_id=user_id, is_active=True).first() is not None


def assessment_permissions(assessment, user_id=None, role=None):
    """Return the set of actions the user may take on one assessment."""
    from models import AssessmentRound
    user_id, role = user_id or _uid(), role or _role()
    if not user_id or assessment is None:
        return set()
    perms = set()
    assigned = role == 'committee' and has_active_assignment(assessment.check_id, user_id)
    if assessment.organization_id is None:
        # Legacy rule, unchanged.
        if role == 'admin':
            perms |= {VIEW_STATUS, VIEW, READ_SOURCE, REVIEW, EXPORT, ASSIGN}
        if assessment.user_id == user_id:
            perms |= {VIEW_STATUS, VIEW, READ_SOURCE, EXPORT}
            if role == 'user':
                perms.add(EDIT)
        if assigned:
            perms |= {VIEW_STATUS, VIEW, READ_SOURCE, REVIEW, EXPORT}
        return perms

    roles = org_roles(assessment.organization_id, user_id)
    if roles & set(EDITOR_ROLES):
        perms |= {VIEW_STATUS, VIEW, READ_SOURCE, EXPORT}
        if role == 'user' and session.get('org_id') == assessment.organization_id:
            perms.add(EDIT)
    if assigned:
        perms |= {VIEW_STATUS, VIEW, READ_SOURCE, REVIEW, EXPORT}
    if assessment.round_id:
        rnd = db.session.get(AssessmentRound, assessment.round_id)
        if rnd is not None:
            if rnd.owner_org_id in oversight_org_ids(user_id, 'round_coordinator'):
                perms |= {VIEW_STATUS, ASSIGN}
                if can_read_source_in(rnd.owner_org_id, user_id):
                    perms |= {VIEW, READ_SOURCE, EXPORT}
            if rnd.owner_org_id in oversight_org_ids(user_id, 'executive'):
                perms.add(VIEW_STATUS)
    if role == 'admin':
        perms |= {VIEW_STATUS, ASSIGN}
    return perms


def assessment_for_check(check):
    from models import DomainAssessment
    return DomainAssessment.query.filter_by(check_id=check.id).first() if check is not None else None


def check_permissions(check, user_id=None, role=None):
    """Legacy DocumentCheck routes use the same rule as the assessment that owns the check."""
    user_id, role = user_id or _uid(), role or _role()
    if check is None or not user_id:
        return set()
    assessment = assessment_for_check(check)
    if assessment is not None:
        return assessment_permissions(assessment, user_id, role)
    perms = set()
    assigned = role == 'committee' and has_active_assignment(check.id, user_id)
    if check.organization_id is None:
        if role == 'admin':
            perms |= {VIEW_STATUS, VIEW, READ_SOURCE, REVIEW, EXPORT, ASSIGN}
        if check.user_id == user_id:
            perms |= {VIEW_STATUS, VIEW, READ_SOURCE, EXPORT}
            if role == 'user':
                perms.add(EDIT)
    else:
        roles = org_roles(check.organization_id, user_id)
        if roles & set(EDITOR_ROLES):
            perms |= {VIEW_STATUS, VIEW, READ_SOURCE, EXPORT}
            if role == 'user' and session.get('org_id') == check.organization_id:
                perms.add(EDIT)
        if role == 'admin':
            perms |= {VIEW_STATUS, ASSIGN}
    if assigned:
        perms |= {VIEW_STATUS, VIEW, READ_SOURCE, REVIEW, EXPORT}
    return perms


def visible_assessments_query(action=VIEW_STATUS):
    """Query of assessments where the user has at least `action`. Used by every list, search and count."""
    from models import AssessmentRound, CommitteeAssignment, DomainAssessment
    user_id, role = _uid(), _role()
    query = DomainAssessment.query
    if not user_id:
        return query.filter(db.false())
    legacy = DomainAssessment.organization_id.is_(None)
    clauses = []
    if role == 'admin':
        clauses.append(legacy)
        if action in (VIEW_STATUS, ASSIGN):
            clauses.append(DomainAssessment.organization_id.isnot(None))
    else:
        clauses.append(db.and_(legacy, DomainAssessment.user_id == user_id))
    if role == 'committee':
        checks = [a.check_id for a in CommitteeAssignment.query.filter_by(committee_user_id=user_id, is_active=True).all()]
        if checks:
            clauses.append(DomainAssessment.check_id.in_(checks))
    editors = editor_org_ids(user_id)
    if editors and action != EDIT:
        clauses.append(DomainAssessment.organization_id.in_(editors))
    elif editors and action == EDIT and role == 'user' and session.get('org_id') in editors:
        clauses.append(DomainAssessment.organization_id == session.get('org_id'))
    coordinator_orgs = oversight_org_ids(user_id, 'round_coordinator')
    executive_orgs = oversight_org_ids(user_id, 'executive')
    status_orgs = set()
    if action in (VIEW_STATUS, ASSIGN):
        status_orgs |= set(coordinator_orgs)
    if action == VIEW_STATUS:
        status_orgs |= set(executive_orgs)
    if action in (VIEW, READ_SOURCE, EXPORT):
        status_orgs |= {o for o in coordinator_orgs if can_read_source_in(o, user_id)}
    if status_orgs:
        round_ids = [r.id for r in AssessmentRound.query.filter(AssessmentRound.owner_org_id.in_(status_orgs)).all()]
        if round_ids:
            clauses.append(db.and_(DomainAssessment.organization_id.isnot(None), DomainAssessment.round_id.in_(round_ids)))
    if action == EDIT:
        clauses = [c for c in clauses if c is not None]
    return query.filter(db.or_(*clauses)) if clauses else query.filter(db.false())


def visible_check_ids_with(action=READ_SOURCE):
    """IDs of DocumentChecks whose files the user may read. Used by the evidence library and file reuse."""
    from models import DocumentCheck
    user_id = _uid()
    if not user_id:
        return []
    ids = {a.check_id for a in visible_assessments_query(action).all() if a.check_id and action in assessment_permissions(a)}
    # Legacy checks without an assessment (classic upload flow).
    from models import DomainAssessment
    linked = db.session.query(DomainAssessment.check_id).filter(DomainAssessment.check_id.isnot(None))
    standalone = DocumentCheck.query.filter(DocumentCheck.id.notin_(linked))
    if _role() == 'admin':
        candidates = standalone.all()
    else:
        candidates = standalone.filter(db.or_(DocumentCheck.user_id == user_id, DocumentCheck.organization_id.in_(editor_org_ids(user_id) or [-1]))).all()
        if _role() == 'committee':
            from models import CommitteeAssignment
            assigned = [a.check_id for a in CommitteeAssignment.query.filter_by(committee_user_id=user_id, is_active=True).all()]
            candidates += standalone.filter(DocumentCheck.id.in_(assigned or [-1])).all()
    ids |= {c.id for c in candidates if action in check_permissions(c)}
    return sorted(ids)


def deny(target_type, target_id, action):
    """Record a refused attempt (no document content) and return the audit row for the caller to commit."""
    from models import AuditLog
    row = AuditLog(user_id=_uid(), actor_email=session.get('email') if has_request_context() else None, action='access_denied',
                   target_type=target_type, target_id=str(target_id) if target_id is not None else None, detail=f'need={action}')
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return row
