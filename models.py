from datetime import datetime
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from extensions import db


@compiles(LONGTEXT, 'sqlite')
def _longtext_on_sqlite(type_, compiler, **kw):
    # Demo, test and migration-copy databases run on SQLite; production stays on MySQL.
    return 'TEXT'

class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(db.Model, TimestampMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    organization = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    password_plain = db.Column(db.String(255))
    role = db.Column(db.String(20), default='user', nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    auth_provider = db.Column(db.String(30), default='local', nullable=False)
    external_subject = db.Column(db.String(255), unique=True, index=True)
    thaid_reference_hash = db.Column(db.String(64), index=True)
    last_login_at = db.Column(db.DateTime)

class TestSuite(db.Model, TimestampMixin):
    __tablename__ = 'templates'
    id = db.Column(db.Integer, primary_key=True)
    display_order = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    suite_code = db.Column(db.String(10), unique=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    description = db.Column(db.Text)
    prompt_structure = db.Column(db.Text, nullable=False)
    sections_json = db.Column(LONGTEXT, nullable=False)
    applicable_framework_codes_json = db.Column(LONGTEXT)
    pass_threshold = db.Column(db.Float, default=70.0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)

class Standard(db.Model, TimestampMixin):
    __tablename__ = 'standards'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    source_type = db.Column(db.String(50), default='international_standard', nullable=False)
    jurisdiction = db.Column(db.String(100))
    publisher = db.Column(db.String(255))
    reference_url = db.Column(db.String(500))
    published_year = db.Column(db.Integer)
    status = db.Column(db.String(120), default='ประกาศใช้แล้ว')
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)

class StandardItem(db.Model, TimestampMixin):
    __tablename__ = 'standard_items'
    id = db.Column(db.Integer, primary_key=True)
    standard_id = db.Column(db.Integer, db.ForeignKey('standards.id'), nullable=False)
    item_code = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(255))
    title = db.Column(db.Text, nullable=False)
    keywords_json = db.Column(LONGTEXT, nullable=False)
    weight = db.Column(db.Float, default=1.0, nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    standard = db.relationship('Standard')

class DocumentCheck(db.Model, TimestampMixin):
    __tablename__ = 'document_checks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    selected_standard_ids_json = db.Column(LONGTEXT, nullable=False)
    data_classification = db.Column(db.String(30), default='open', nullable=False)
    processing_provider = db.Column(db.String(50), default='pending', nullable=False)
    domain_slug = db.Column(db.String(50), default='general', nullable=False, server_default='general', index=True)
    # Pilot: NULL keeps the original per-user access rule (legacy work is never re-scoped automatically).
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), index=True)
    domain_subdomain = db.Column(db.String(150))
    assessment_use_case = db.Column(db.String(255))
    domain_review_json = db.Column(LONGTEXT)
    extracted_text = db.Column(LONGTEXT)
    extracted_headings_json = db.Column(LONGTEXT)
    matched_sections_json = db.Column(LONGTEXT)
    missing_sections_json = db.Column(LONGTEXT)
    section_scores_json = db.Column(LONGTEXT)
    completeness_score = db.Column(db.Float, default=0.0)
    completeness_passed = db.Column(db.Boolean, default=False)
    thai_recommendations = db.Column(LONGTEXT)
    compliance_results_json = db.Column(LONGTEXT)
    compliance_score = db.Column(db.Float, default=0.0)
    maturity_level = db.Column(db.String(50))
    standard_summary_json = db.Column(LONGTEXT)
    kg_summary_json = db.Column(LONGTEXT)
    gemini_summary_json = db.Column(LONGTEXT)
    local_model_summary_json = db.Column(LONGTEXT)
    report_pdf_path = db.Column(db.String(500))
    test_suite = db.relationship('TestSuite')
    # Backward-compatible alias used by legacy reports/routes.
    @property
    def template(self):
        return self.test_suite
    owner = db.relationship('User')

class DocumentFile(db.Model, TimestampMixin):
    __tablename__ = 'document_files'
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey('document_checks.id', ondelete='CASCADE'), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    content_hash = db.Column(db.String(64), index=True)
    page_count = db.Column(db.Integer, default=0, nullable=False)
    extracted_text = db.Column(LONGTEXT)
    pages_json = db.Column(LONGTEXT)
    # Pilot document protection: three separate facts. NULL = legacy file, derived from the check's Open/Confidential.
    disclosure_class = db.Column(db.String(30))      # public | internal | restricted | secret
    personal_data = db.Column(db.String(20))         # none | personal | sensitive | unknown
    is_redacted = db.Column(db.Boolean)
    classified_by = db.Column(db.Integer)
    classified_at = db.Column(db.DateTime)
    check = db.relationship('DocumentCheck', backref=db.backref('document_files', cascade='all, delete-orphan', lazy=True))

class CommitteeAssignment(db.Model, TimestampMixin):
    __tablename__ = 'committee_assignments'
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey('document_checks.id'), nullable=False)
    committee_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    assigned_by = db.Column(db.Integer)
    revoked_by = db.Column(db.Integer)
    revoked_at = db.Column(db.DateTime)
    revoke_reason = db.Column(db.String(500))
    check = db.relationship('DocumentCheck')
    committee = db.relationship('User', foreign_keys=[committee_user_id])

class CommitteeReview(db.Model, TimestampMixin):
    __tablename__ = 'committee_reviews'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('committee_assignments.id'), nullable=False)
    committee_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    check_id = db.Column(db.Integer, db.ForeignKey('document_checks.id'), nullable=False)
    scores_json = db.Column(LONGTEXT)
    comments = db.Column(LONGTEXT)
    report_pdf_path = db.Column(db.String(500))
    assignment = db.relationship('CommitteeAssignment')
    committee = db.relationship('User', foreign_keys=[committee_user_id])
    check = db.relationship('DocumentCheck', foreign_keys=[check_id])

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    actor_email = db.Column(db.String(255))
    action = db.Column(db.String(255), nullable=False)
    target_type = db.Column(db.String(100))
    target_id = db.Column(db.String(100))
    detail = db.Column(LONGTEXT)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Backward compatibility for existing migrations / imports. The physical table remains `templates`.
Template = TestSuite


# ---------------------------------------------------------------------------
# V16 Domain-Adaptive Assessment. All tables are additive; nothing above changes.
# ---------------------------------------------------------------------------
class DomainPackVersion(db.Model):
    __tablename__ = 'domain_pack_versions'
    __table_args__ = (db.UniqueConstraint('slug', 'content_hash', name='uq_pack_version_hash'),)
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), nullable=False, index=True)
    pack_version = db.Column(db.String(40), nullable=False)
    content_hash = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(LONGTEXT, nullable=False)
    loaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class DomainProfile(db.Model, TimestampMixin):
    __tablename__ = 'domain_profiles'
    slug = db.Column(db.String(50), primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    title_th = db.Column(db.String(150), nullable=False)
    icon = db.Column(db.String(50))
    accent = db.Column(db.String(20))
    display_order = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(30), default='pilot_draft', nullable=False)
    pack_version = db.Column(db.String(40), nullable=False)
    content_hash = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(LONGTEXT, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class TaxonomyNode(db.Model):
    __tablename__ = 'taxonomy_nodes'
    node_id = db.Column(db.String(80), primary_key=True)
    domain_slug = db.Column(db.String(50), nullable=False, index=True)
    node_type = db.Column(db.String(30), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    title_th = db.Column(db.String(300))
    attrs_json = db.Column(LONGTEXT)
    pack_version = db.Column(db.String(40))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class TaxonomyEdge(db.Model):
    __tablename__ = 'taxonomy_edges'
    __table_args__ = (db.UniqueConstraint('domain_slug', 'src_id', 'dst_id', 'relation', name='uq_taxonomy_edge'),)
    id = db.Column(db.Integer, primary_key=True)
    domain_slug = db.Column(db.String(50), nullable=False, index=True)
    src_id = db.Column(db.String(80), nullable=False, index=True)
    dst_id = db.Column(db.String(80), nullable=False, index=True)
    relation = db.Column(db.String(40), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class DomainControl(db.Model):
    __tablename__ = 'domain_controls'
    control_id = db.Column(db.String(40), primary_key=True)
    domain_slug = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    title_th = db.Column(db.String(255))
    critical = db.Column(db.Boolean, default=False, nullable=False)
    risk_level = db.Column(db.String(20))
    pack_version = db.Column(db.String(40))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class EvidenceRequirement(db.Model):
    __tablename__ = 'evidence_requirements'
    requirement_id = db.Column(db.String(60), primary_key=True)
    domain_slug = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    title_th = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

class DomainRubric(db.Model):
    __tablename__ = 'domain_rubrics'
    rubric_id = db.Column(db.String(40), primary_key=True)
    domain_slug = db.Column(db.String(50), nullable=False, index=True)
    version = db.Column(db.String(20), nullable=False)
    definition_json = db.Column(LONGTEXT, nullable=False)

class RegulatoryReference(db.Model, TimestampMixin):
    __tablename__ = 'regulatory_references'
    source_id = db.Column(db.String(60), primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    title_th = db.Column(db.String(500))
    issuing_authority = db.Column(db.String(255))
    jurisdiction = db.Column(db.String(100))
    document_type = db.Column(db.String(80))
    normative_class = db.Column(db.String(40), nullable=False, index=True)
    publication_date = db.Column(db.String(20))
    effective_date = db.Column(db.String(20))
    version = db.Column(db.String(80))
    official_url = db.Column(db.String(500))
    applicability_json = db.Column(LONGTEXT)
    condition_th = db.Column(db.Text)
    domains_json = db.Column(LONGTEXT)
    standard_code = db.Column(db.String(100), index=True)
    verification_status = db.Column(db.String(30), nullable=False, default='pending_verification', index=True)
    verification_note = db.Column(db.Text)
    verified_by = db.Column(db.String(255))
    verified_at = db.Column(db.DateTime)
    registry_version = db.Column(db.String(40))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Pilot: clauses, scope, supersession, excluded use cases, checked_on/by. Kept as JSON so the registry stays additive.
    details_json = db.Column(LONGTEXT)

class DomainAssessment(db.Model, TimestampMixin):
    __tablename__ = 'domain_assessments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    domain_slug = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    organization_name = db.Column(db.String(255))
    organization_context = db.Column(db.Text)
    profile_json = db.Column(LONGTEXT)
    status = db.Column(db.String(30), nullable=False, default='draft', index=True)
    current_step = db.Column(db.Integer, nullable=False, default=1)
    data_classification = db.Column(db.String(30))
    check_id = db.Column(db.Integer, db.ForeignKey('document_checks.id'), index=True)
    config_snapshot_json = db.Column(LONGTEXT)
    snapshot_hash = db.Column(db.String(64))
    pack_version = db.Column(db.String(40))
    frozen_at = db.Column(db.DateTime)
    summary_json = db.Column(LONGTEXT)
    scoring_version = db.Column(db.String(40))
    last_run_at = db.Column(db.DateTime)
    run_note = db.Column(db.Text)
    # Pilot scope. All nullable: an assessment without organization_id keeps the original owner-based access.
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), index=True)
    round_id = db.Column(db.Integer, db.ForeignKey('assessment_rounds.id'), index=True)
    created_by_id = db.Column(db.Integer)
    responsible_user_id = db.Column(db.Integer)
    criteria_set_id = db.Column(db.Integer, db.ForeignKey('criteria_sets.id'))
    criteria_version = db.Column(db.String(40))
    workflow_status = db.Column(db.String(30), index=True)   # NULL for legacy; see services/workflow.py
    workflow_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    submitted_at = db.Column(db.DateTime)
    confirmed_at = db.Column(db.DateTime)
    owner = db.relationship('User', foreign_keys=[user_id])
    check = db.relationship('DocumentCheck')
    organization = db.relationship('Organization', foreign_keys=[organization_id])
    round = db.relationship('AssessmentRound', foreign_keys=[round_id])
    criteria_set = db.relationship('CriteriaSet', foreign_keys=[criteria_set_id])

class ApplicabilityDecision(db.Model, TimestampMixin):
    __tablename__ = 'assessment_applicability_decisions'
    __table_args__ = (db.UniqueConstraint('assessment_id', 'target_type', 'target_id', name='uq_applicability_target'),)
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('domain_assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    target_type = db.Column(db.String(20), nullable=False)
    target_id = db.Column(db.String(60), nullable=False)
    override_status = db.Column(db.String(30))
    confirmed = db.Column(db.Boolean, default=False, nullable=False)
    reason = db.Column(db.Text)
    decided_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    decided_by_email = db.Column(db.String(255))
    decided_at = db.Column(db.DateTime)

class DomainFinding(db.Model, TimestampMixin):
    __tablename__ = 'domain_assessment_findings'
    __table_args__ = (db.UniqueConstraint('assessment_id', 'control_id', name='uq_finding_control'),)
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('domain_assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    control_id = db.Column(db.String(40), nullable=False, index=True)
    state = db.Column(db.String(30), nullable=False, index=True)
    level = db.Column(db.Integer)
    proposed_level = db.Column(db.Integer)
    critical = db.Column(db.Boolean, default=False, nullable=False, index=True)
    coverage_ratio = db.Column(db.Float)
    confidence = db.Column(db.String(10))
    compliance_status = db.Column(db.String(30))
    reason = db.Column(LONGTEXT)
    gap = db.Column(LONGTEXT)
    recommendation = db.Column(LONGTEXT)
    method = db.Column(db.String(40))
    human_level = db.Column(db.Integer)
    human_note = db.Column(LONGTEXT)
    human_stance = db.Column(db.String(20))
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_by_email = db.Column(db.String(255))
    reviewed_at = db.Column(db.DateTime)
    # Committee judgement, kept apart from the system's preliminary level.
    judgement = db.Column(db.String(30))          # sufficient | more_evidence | not_met
    judgement_reason = db.Column(LONGTEXT)
    judged_by = db.Column(db.Integer)
    judged_at = db.Column(db.DateTime)

class EvidenceMapping(db.Model, TimestampMixin):
    __tablename__ = 'evidence_control_mappings'
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('domain_assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    requirement_id = db.Column(db.String(60), nullable=False, index=True)
    document_file_id = db.Column(db.Integer, db.ForeignKey('document_files.id'), nullable=False, index=True)
    page = db.Column(db.Integer)
    snippet = db.Column(db.Text)
    matched_keywords_json = db.Column(LONGTEXT)
    relevance = db.Column(db.Float)
    source = db.Column(db.String(20), nullable=False, default='auto')
    created_by = db.Column(db.Integer)
    document_file = db.relationship('DocumentFile')


# ---------------------------------------------------------------------------
# MHESI / OPS-MHESI pilot. Additive tables; see migrate_mhesi_pilot.py.
# ---------------------------------------------------------------------------
ORG_TYPES = ('ministry', 'ministry_office', 'university', 'mhesi_agency', 'other')
MEMBERSHIP_ROLES = ('org_coordinator', 'org_staff', 'round_coordinator', 'executive', 'criteria_approver')


class Organization(db.Model, TimestampMixin):
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    name_en = db.Column(db.String(255))
    org_type = db.Column(db.String(30), nullable=False, default='other')
    parent_id = db.Column(db.Integer, db.ForeignKey('organizations.id'))
    # Institution reference used by Digital Single View / e-Office exports. Not verified until the agency confirms it.
    external_ref = db.Column(db.String(60))
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    parent = db.relationship('Organization', remote_side=[id])


class OrganizationMembership(db.Model, TimestampMixin):
    __tablename__ = 'organization_memberships'
    __table_args__ = (db.UniqueConstraint('user_id', 'organization_id', 'role', name='uq_membership_role'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    role = db.Column(db.String(30), nullable=False)
    # Reading original evidence is a separate grant; coordinators and executives do not get it by role.
    can_read_source = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    granted_by = db.Column(db.Integer)
    revoked_by = db.Column(db.Integer)
    revoked_at = db.Column(db.DateTime)
    user = db.relationship('User', foreign_keys=[user_id])
    organization = db.relationship('Organization')


class CriteriaSet(db.Model, TimestampMixin):
    """A versioned, approved bundle of domain packs. Approval is separate from source verification."""
    __tablename__ = 'criteria_sets'
    __table_args__ = (db.UniqueConstraint('code', 'version', name='uq_criteria_version'),)
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), nullable=False)
    version = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    domain_slug = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='draft')  # draft | in_review | approved | published | retired
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    snapshot_json = db.Column(LONGTEXT)
    content_hash = db.Column(db.String(64))
    note = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    submitted_by = db.Column(db.Integer)
    reviewed_by = db.Column(db.Integer)
    approved_by = db.Column(db.Integer)
    approved_at = db.Column(db.DateTime)
    published_by = db.Column(db.Integer)
    published_at = db.Column(db.DateTime)


class AssessmentRound(db.Model, TimestampMixin):
    __tablename__ = 'assessment_rounds'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    owner_org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    scope_th = db.Column(db.Text)
    opens_on = db.Column(db.Date)
    closes_on = db.Column(db.Date)
    criteria_set_id = db.Column(db.Integer, db.ForeignKey('criteria_sets.id'), nullable=False)
    # Pilot rounds start with published or redacted documents only.
    document_scope = db.Column(db.String(30), nullable=False, default='public_or_redacted')
    status = db.Column(db.String(30), nullable=False, default='draft')  # draft | open | closed_complete | closed_incomplete
    close_reason = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.Integer)
    owner_org = db.relationship('Organization')
    criteria_set = db.relationship('CriteriaSet')


class RoundParticipation(db.Model, TimestampMixin):
    __tablename__ = 'round_participations'
    __table_args__ = (db.UniqueConstraint('round_id', 'organization_id', name='uq_round_org'),)
    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('assessment_rounds.id'), nullable=False, index=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    coordinator_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(20), nullable=False, default='invited')  # invited | accepted | declined | withdrawn
    due_on = db.Column(db.Date)
    invited_by = db.Column(db.Integer)
    responded_at = db.Column(db.DateTime)
    round = db.relationship('AssessmentRound')
    organization = db.relationship('Organization')
    coordinator = db.relationship('User')


class SubmissionRevision(db.Model):
    __tablename__ = 'submission_revisions'
    __table_args__ = (db.UniqueConstraint('assessment_id', 'revision_no', name='uq_revision_no'),)
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('domain_assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    revision_no = db.Column(db.Integer, nullable=False)
    submitted_by = db.Column(db.Integer, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    criteria_set_id = db.Column(db.Integer)
    criteria_version = db.Column(db.String(40))
    snapshot_hash = db.Column(db.String(64))
    files_json = db.Column(LONGTEXT, nullable=False)      # [{file_id, filename, content_hash, page_count, stored_filename}]
    diff_json = db.Column(LONGTEXT)                       # {added: [...], removed: [...], unchanged: [...]}
    responses_json = db.Column(LONGTEXT)                  # {issue_id: response text}
    system_summary_json = db.Column(LONGTEXT)             # system result at submission time
    note = db.Column(db.Text)


class RevisionRequest(db.Model, TimestampMixin):
    """An issue raised by a reviewer. Its status is separate from the assessment workflow status."""
    __tablename__ = 'revision_requests'
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('domain_assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    control_id = db.Column(db.String(40), nullable=False)
    severity = db.Column(db.String(20), nullable=False, default='major')  # critical | major | minor
    reason = db.Column(db.Text, nullable=False)
    evidence_required = db.Column(db.Text, nullable=False)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    due_on = db.Column(db.Date)
    raised_by = db.Column(db.Integer, nullable=False)
    verifier_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open', index=True)  # open | responded | closed
    raised_in_revision = db.Column(db.Integer)
    response_note = db.Column(db.Text)
    responded_by = db.Column(db.Integer)
    responded_in_revision = db.Column(db.Integer)
    closed_by = db.Column(db.Integer)
    closed_at = db.Column(db.DateTime)
    close_note = db.Column(db.Text)
    closing_evidence_json = db.Column(LONGTEXT)   # [{file_id, filename, page, content_hash}]
    version = db.Column(db.Integer, nullable=False, default=0)
    responsible = db.relationship('User', foreign_keys=[responsible_user_id])
    verifier = db.relationship('User', foreign_keys=[verifier_user_id])


class WorkflowEvent(db.Model):
    __tablename__ = 'workflow_events'
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('domain_assessments.id', ondelete='CASCADE'), nullable=False, index=True)
    action = db.Column(db.String(40), nullable=False)
    from_status = db.Column(db.String(30))
    to_status = db.Column(db.String(30))
    actor_id = db.Column(db.Integer)
    actor_email = db.Column(db.String(255))
    reason = db.Column(db.Text)
    revision_no = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ModelProcessingRule(db.Model, TimestampMixin):
    """Explicit allow rules. Anything without a matching active rule is refused (default deny)."""
    __tablename__ = 'model_processing_rules'
    __table_args__ = (db.UniqueConstraint('provider', 'disclosure_class', 'personal_data', name='uq_model_rule'),)
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(30), nullable=False)          # gemini | local_model
    disclosure_class = db.Column(db.String(30), nullable=False)
    personal_data = db.Column(db.String(20), nullable=False)     # none | personal | sensitive | unknown | redacted
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.String(500))
    updated_by = db.Column(db.Integer)


class AISystem(db.Model, TimestampMixin):
    __tablename__ = 'ai_systems'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    owner_name = db.Column(db.String(255), nullable=False)
    owner_user_id = db.Column(db.Integer)
    purpose = db.Column(db.Text, nullable=False)
    affected_persons = db.Column(db.Text)
    provider = db.Column(db.String(255))
    model_name = db.Column(db.String(255))
    data_types = db.Column(db.Text)
    risk_level = db.Column(db.String(20), nullable=False, default='medium')
    review_cycle_months = db.Column(db.Integer, nullable=False, default=12)
    next_review_on = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default='active')
    linked_assessment_ids_json = db.Column(LONGTEXT)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.Integer)
    organization = db.relationship('Organization')


class IntegrationEndpoint(db.Model, TimestampMixin):
    """Digital Single View, MHESI e-Office and TUC signing. 'prepared' until a contract and credentials exist."""
    __tablename__ = 'integration_endpoints'
    code = db.Column(db.String(40), primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='prepared')   # prepared | configured | live
    missing_json = db.Column(LONGTEXT)
    note = db.Column(db.Text)
