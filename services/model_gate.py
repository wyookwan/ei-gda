"""Decide whether document content may be sent to a model provider. Default deny.

Three facts are kept apart for each file:
1. disclosure_class: public | internal | restricted | secret (official secret classes under the 2544 regulation)
2. personal_data: none | personal | sensitive | unknown, plus is_redacted
3. the provider that would process it: gemini (external) or local_model

A file may be sent only if an active ModelProcessingRule allows that exact provider, class and
personal-data level, the deployment supports the class, and the assessment's round scope allows it.
There is no fallback to another provider: a refusal stops the run.

Legacy files (disclosure_class NULL) are derived from the check's Open/Confidential choice, which the
user acknowledged at upload: Open -> public/none, Confidential -> restricted/unknown. The seeded rules
reproduce the V14 routing for those two cases, so earlier work keeps running the way it did.
"""
from flask import current_app, has_request_context, session

from extensions import db

DISCLOSURE_CLASSES = ('public', 'internal', 'restricted', 'secret')
PERSONAL_LEVELS = ('none', 'personal', 'sensitive', 'unknown')
PROVIDERS = ('gemini', 'local_model')
DISCLOSURE_LABELS = {'public': 'เผยแพร่ได้', 'internal': 'ใช้ภายใน', 'restricted': 'ไม่เปิดเผย (ม.15 พ.ร.บ.ข้อมูลข่าวสาร)', 'secret': 'ชั้นความลับราชการ'}
PERSONAL_LABELS = {'none': 'ไม่มีข้อมูลส่วนบุคคล', 'personal': 'มีข้อมูลส่วนบุคคล', 'sensitive': 'มีข้อมูลอ่อนไหว', 'unknown': 'ยังไม่ทราบ', 'redacted': 'ปกปิดข้อมูลแล้ว'}

# Explicit allow rules seeded by the migration. Everything else is refused.
DEFAULT_RULES = (
    ('gemini', 'public', 'none', 'เอกสารเผยแพร่ ไม่มีข้อมูลส่วนบุคคล'),
    ('gemini', 'public', 'redacted', 'เอกสารเผยแพร่ที่ปกปิดข้อมูลส่วนบุคคลแล้ว'),
    ('local_model', 'public', 'none', 'โมเดลภายใน'),
    ('local_model', 'public', 'redacted', 'โมเดลภายใน'),
    ('local_model', 'internal', 'none', 'โมเดลภายใน'),
    ('local_model', 'internal', 'redacted', 'โมเดลภายใน'),
    ('local_model', 'restricted', 'redacted', 'โมเดลภายใน เอกสารปกปิดแล้ว'),
    # Reproduces V14 behaviour for files classified Confidential before the pilot.
    ('local_model', 'restricted', 'unknown', 'งานเดิมระดับ Confidential ใช้โมเดลภายในเท่านั้น'),
    ('local_model', 'restricted', 'personal', 'โมเดลภายใน'),
)


def provider_for(classification):
    return 'gemini' if (classification or '').lower() == 'open' else 'local_model'


def effective_labels(file_row, check=None):
    """Return (disclosure_class, personal_level) for one file, deriving legacy values when needed."""
    disclosure = file_row.disclosure_class
    personal = file_row.personal_data
    if disclosure is None:
        legacy = ((check.data_classification if check is not None else None) or '').lower()
        disclosure = 'public' if legacy == 'open' else 'restricted'
        personal = personal or ('none' if legacy == 'open' else 'unknown')
    personal = personal or 'unknown'
    if file_row.is_redacted and personal != 'none':
        personal = 'redacted'
    return disclosure, personal


def seed_default_rules(session_=None):
    from models import ModelProcessingRule
    s = session_ or db.session
    existing = {(r.provider, r.disclosure_class, r.personal_data) for r in s.query(ModelProcessingRule).all()}
    added = 0
    for provider, disclosure, personal, note in DEFAULT_RULES:
        if (provider, disclosure, personal) not in existing:
            s.add(ModelProcessingRule(provider=provider, disclosure_class=disclosure, personal_data=personal, note=note, is_active=True))
            added += 1
    s.flush()
    return added


def _rule_allows(provider, disclosure, personal):
    from models import ModelProcessingRule
    return db.session.query(ModelProcessingRule.id).filter_by(provider=provider, disclosure_class=disclosure, personal_data=personal, is_active=True).first() is not None


def authorize(files, provider, check=None, assessment=None):
    """Return (allowed, reasons). `reasons` lists one Thai sentence per refused file, without document text."""
    reasons = []
    if provider not in PROVIDERS:
        return False, ['ผู้ให้บริการโมเดลไม่อยู่ในรายการที่อนุญาต']
    supported = set(current_app.config.get('SUPPORTED_DISCLOSURE_CLASSES') or ())
    round_scope = None
    if assessment is not None and assessment.round_id:
        from models import AssessmentRound
        rnd = db.session.get(AssessmentRound, assessment.round_id)
        round_scope = rnd.document_scope if rnd else None
    for row in files:
        disclosure, personal = effective_labels(row, check)
        name = row.original_filename
        if disclosure not in supported or disclosure == 'secret':
            reasons.append(f'{name}: สภาพแวดล้อมนี้ยังไม่รองรับเอกสารชั้น {DISCLOSURE_LABELS.get(disclosure, disclosure)}')
            continue
        if round_scope == 'public_or_redacted' and not (disclosure == 'public' or personal in ('redacted', 'none') and row.is_redacted):
            reasons.append(f'{name}: รอบนำร่องนี้รับเฉพาะเอกสารเผยแพร่หรือเอกสารที่ปกปิดข้อมูลแล้ว')
            continue
        if not _rule_allows(provider, disclosure, personal):
            reasons.append(f'{name}: ไม่มีนโยบายอนุญาตให้ส่ง {DISCLOSURE_LABELS.get(disclosure, disclosure)} / {PERSONAL_LABELS.get(personal, personal)} ไปยัง {provider}')
    return not reasons, reasons


def log_block(target_type, target_id, provider, reasons):
    """Audit a refusal. File names and counts only; no document text."""
    from models import AuditLog
    db.session.add(AuditLog(user_id=session.get('user_id') if has_request_context() else None,
                            actor_email=session.get('email') if has_request_context() else None,
                            action='model_gate_blocked', target_type=target_type, target_id=str(target_id),
                            detail=f'provider={provider}; refused_files={len(reasons)}; ' + ' | '.join(r.split(':')[0] for r in reasons)[:2000]))


class LegacyText:
    """Stand-in for a V12 check whose text was stored on the check itself, so the gate still evaluates it."""
    def __init__(self, check):
        self.original_filename = check.original_filename or f'check {check.id}'
        self.disclosure_class = None
        self.personal_data = None
        self.is_redacted = None
