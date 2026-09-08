from datetime import datetime
from sqlalchemy.dialects.mysql import LONGTEXT
from extensions import db

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
    page_count = db.Column(db.Integer, default=0, nullable=False)
    extracted_text = db.Column(LONGTEXT)
    pages_json = db.Column(LONGTEXT)
    check = db.relationship('DocumentCheck', backref=db.backref('document_files', cascade='all, delete-orphan', lazy=True))

class CommitteeAssignment(db.Model, TimestampMixin):
    __tablename__ = 'committee_assignments'
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey('document_checks.id'), nullable=False)
    committee_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    check = db.relationship('DocumentCheck')
    committee = db.relationship('User')

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
