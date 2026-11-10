"""Retention by data type. Report first; delete only with apply=True, and never evidence files automatically.

Periods are pilot defaults and must be confirmed by the data owner (see docs/PILOT_DEPLOY.md).
"""
from datetime import datetime, timedelta

from extensions import db

POLICY = {
    'notifications_read': {'days': 180, 'auto_delete': True, 'th': 'การแจ้งเตือนที่อ่านแล้ว'},
    'audit_logs': {'days': 365 * 5, 'auto_delete': True, 'th': 'บันทึกการใช้งาน (เก็บ 5 ปี)'},
    'access_denied_logs': {'days': 365 * 2, 'auto_delete': True, 'th': 'บันทึกการปฏิเสธสิทธิ์ (เก็บ 2 ปี)'},
    'evidence_closed_rounds': {'days': 365 * 5, 'auto_delete': False, 'th': 'หลักฐานของรอบที่ปิดแล้ว (รายงานเท่านั้น ให้เจ้าของข้อมูลอนุมัติการลบ)'},
}


def report(now=None, apply=False):
    from models import AssessmentRound, AuditLog, DocumentFile, DomainAssessment, Notification
    now = now or datetime.utcnow()
    cutoff = lambda key: now - timedelta(days=POLICY[key]['days'])
    out = {}
    q = Notification.query.filter(Notification.is_read.is_(True), Notification.created_at < cutoff('notifications_read'))
    out['notifications_read'] = q.count()
    if apply:
        q.delete(synchronize_session=False)
    q = AuditLog.query.filter(AuditLog.action == 'access_denied', AuditLog.created_at < cutoff('access_denied_logs'))
    out['access_denied_logs'] = q.count()
    if apply:
        q.delete(synchronize_session=False)
    q = AuditLog.query.filter(AuditLog.action != 'access_denied', AuditLog.created_at < cutoff('audit_logs'))
    out['audit_logs'] = q.count()
    if apply:
        q.delete(synchronize_session=False)
    closed = [r.id for r in AssessmentRound.query.filter(AssessmentRound.status.in_(('closed_complete', 'closed_incomplete')),
                                                         AssessmentRound.updated_at < cutoff('evidence_closed_rounds')).all()]
    checks = [a.check_id for a in DomainAssessment.query.filter(DomainAssessment.round_id.in_(closed or [-1])).all() if a.check_id]
    out['evidence_closed_rounds'] = DocumentFile.query.filter(DocumentFile.check_id.in_(checks or [-1])).count()
    if apply:
        db.session.commit()
    return out
