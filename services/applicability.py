"""V16 applicability engine. Deterministic, explainable, and never LLM-driven.

A rule is a dict of selectors. Each selector compares one profile attribute:
org_types, functional_areas, use_cases, data_categories_any,
data_categories_min_sensitivity, min_risk, flags.
"""

RISK_ORDER = ['low', 'medium', 'high', 'critical']
SENSITIVITY_ORDER = ['public', 'internal', 'personal', 'sensitive']
IMPACT_ORDER = ['information', 'assistive', 'significant', 'safety_critical']
BINDING_CLASSES = ('binding_legislation', 'mandated_standard', 'internal_policy')
UNVERIFIED_STATUSES = ('pending_verification', 'draft')

APPLICABLE, CONDITIONAL, NOT_APPLICABLE, PENDING = 'applicable', 'conditional', 'not_applicable', 'pending_verification'
SELECTOR_LABELS = {'org_types': 'ประเภทองค์กร', 'functional_areas': 'ภารกิจ', 'use_cases': 'AI Use Case'}


def _rank(order, value, default=0):
    return order.index(value) if value in order else default


def category_sensitivity(pack_categories, selected):
    """Return the highest sensitivity among selected categories, or None if none were chosen."""
    if not selected:
        return None
    by_id = {c['id']: c.get('sensitivity', 'internal') for c in pack_categories}
    known = [by_id[x] for x in selected if x in by_id]
    return max(known, key=lambda s: _rank(SENSITIVITY_ORDER, s)) if known else None


def derive_risk(profile, use_case=None, sensitivity=None):
    """Derive inherent risk from impact, data sensitivity and flags. The use-case floor cannot be lowered."""
    reasons = []
    impact = profile.get('decision_impact') or 'assistive'
    floor = (use_case or {}).get('floor_impact')
    if floor and _rank(IMPACT_ORDER, floor) > _rank(IMPACT_ORDER, impact):
        impact = floor
        reasons.append(f"Use Case นี้มีผลกระทบขั้นต่ำระดับ {floor}")
    level = 'low'
    if impact == 'safety_critical':
        level = 'critical'
    elif impact == 'significant':
        level = 'high'
    elif sensitivity == 'sensitive':
        level = 'high'
    elif sensitivity == 'personal':
        level = 'medium'
    if impact in ('significant', 'safety_critical'):
        reasons.append(f'ผลต่อการตัดสินใจระดับ {impact}')
    if sensitivity in ('personal', 'sensitive'):
        reasons.append(f'ใช้ข้อมูลระดับ {sensitivity}')
    if (profile.get('flags') or {}).get('involves_minors') and _rank(RISK_ORDER, level) < _rank(RISK_ORDER, 'high'):
        level = 'high'
        reasons.append('ผู้ได้รับผลกระทบเป็นผู้เยาว์')
    return {'level': level, 'impact': impact, 'sensitivity': sensitivity, 'reasons': reasons or ['ไม่มีปัจจัยเพิ่มความเสี่ยงจากข้อมูลที่ระบุ']}


def build_context(profile, pack_categories, use_case=None):
    sensitivity = category_sensitivity(pack_categories, profile.get('data_categories'))
    risk = derive_risk(profile, use_case, sensitivity)
    return {'org_type': profile.get('org_type') or None, 'functional_area': profile.get('functional_area') or None,
            'use_case': profile.get('use_case') or None, 'data_categories': profile.get('data_categories') or None,
            'sensitivity': sensitivity, 'risk': risk['level'], 'flags': profile.get('flags') or {}, 'risk_detail': risk}


def evaluate_rule(rule, context, labels=None):
    """Return (matched, mismatched, unknown) as lists of Thai explanations."""
    labels = labels or {}
    matched, mismatched, unknown = [], [], []
    name = lambda value: labels.get(value, value)
    for selector, key in (('org_types', 'org_type'), ('functional_areas', 'functional_area'), ('use_cases', 'use_case')):
        wanted = (rule or {}).get(selector)
        if not wanted:
            continue
        current = context.get(key)
        label = SELECTOR_LABELS[selector]
        if not current:
            unknown.append(f'ยังไม่ได้ระบุ{label}')
        elif current in wanted:
            matched.append(f'{label}ตรงกับ {name(current)}')
        else:
            mismatched.append(f'{label} {name(current)} ไม่อยู่ในขอบเขต')
    wanted = (rule or {}).get('data_categories_any')
    if wanted:
        current = context.get('data_categories')
        if current is None:
            unknown.append('ยังไม่ได้ระบุประเภทข้อมูล')
        elif set(current) & set(wanted):
            matched.append('ใช้ประเภทข้อมูลที่เกี่ยวข้อง')
        else:
            mismatched.append('ไม่ได้ใช้ประเภทข้อมูลที่เกี่ยวข้อง')
    wanted = (rule or {}).get('data_categories_min_sensitivity')
    if wanted:
        current = context.get('sensitivity')
        if current is None:
            unknown.append('ยังไม่ได้ระบุประเภทข้อมูล')
        elif _rank(SENSITIVITY_ORDER, current) >= _rank(SENSITIVITY_ORDER, wanted):
            matched.append(f'ข้อมูลระดับ {current} ถึงเกณฑ์ {wanted}')
        else:
            mismatched.append(f'ข้อมูลระดับ {current} ต่ำกว่าเกณฑ์ {wanted}')
    wanted = (rule or {}).get('min_risk')
    if wanted:
        current = context.get('risk')
        if _rank(RISK_ORDER, current) >= _rank(RISK_ORDER, wanted):
            matched.append(f'ความเสี่ยงระดับ {current} ถึงเกณฑ์ {wanted}')
        else:
            mismatched.append(f'ความเสี่ยงระดับ {current} ต่ำกว่าเกณฑ์ {wanted}')
    for flag, expected in ((rule or {}).get('flags') or {}).items():
        current = (context.get('flags') or {}).get(flag)
        if current is None:
            unknown.append(f'ยังไม่ได้ตอบคำถาม {flag}')
        elif bool(current) == bool(expected):
            matched.append(f'คำตอบ {flag} ตรงเงื่อนไข')
        else:
            mismatched.append(f'คำตอบ {flag} ไม่ตรงเงื่อนไข')
    return matched, mismatched, unknown


def resolve_control(control, context, labels=None):
    """Decide whether a control is applicable and explain why."""
    matched, mismatched, unknown = evaluate_rule(control.get('applies_when'), context, labels)
    if mismatched:
        return {'status': NOT_APPLICABLE, 'reason_th': 'ไม่รวม: ' + '; '.join(mismatched)}
    if unknown:
        return {'status': CONDITIONAL, 'reason_th': 'มีเงื่อนไข: ' + '; '.join(unknown)}
    if control.get('applies_when'):
        return {'status': APPLICABLE, 'reason_th': 'รวม: ' + '; '.join(matched)}
    return {'status': APPLICABLE, 'reason_th': 'รวม: control นี้ใช้กับทุกโปรไฟล์ใน Domain'}


def resolve_critical(control, context, labels=None):
    if control.get('critical'):
        return True
    rule = control.get('critical_when')
    if not rule:
        return False
    _, mismatched, unknown = evaluate_rule(rule, context, labels)
    return not mismatched and not unknown


def resolve_reference(reference, context, labels=None):
    """Resolve a regulation. Unverified sources are never treated as binding."""
    if context.get('use_case') and context['use_case'] in (reference.get('excluded_use_cases') or []):
        return {'status': NOT_APPLICABLE, 'is_binding': False,
                'reason_th': reference.get('not_basis_for_th') or 'แหล่งอ้างอิงนี้ไม่ใช้เป็นฐานข้อบังคับของ Use Case นี้'}
    rule = reference.get('applies_when')
    matched, mismatched, unknown = evaluate_rule(rule, context, labels)
    binding = reference.get('normative_class') in BINDING_CLASSES
    status = reference.get('verification_status')
    is_binding = binding and status == 'expert_verified' and not reference.get('enforcement_hold')
    if binding and reference.get('enforcement_hold') and not mismatched:
        return {'status': PENDING, 'is_binding': False, 'reason_th': reference.get('hold_reason_th') or 'ระงับการใช้เป็นเกณฑ์บังคับระหว่างรอยืนยัน'}
    if mismatched:
        return {'status': NOT_APPLICABLE, 'is_binding': False, 'reason_th': 'ไม่เกี่ยวข้อง: ' + '; '.join(mismatched)}
    if binding and status != 'expert_verified':
        return {'status': PENDING, 'is_binding': False,
                'reason_th': 'เป็นกฎหมายหรือมาตรฐานบังคับที่ยังไม่ผ่านการยืนยัน จึงยังไม่ใช้สรุปการปฏิบัติตามกฎหมาย'}
    if status in UNVERIFIED_STATUSES:
        return {'status': PENDING, 'is_binding': False, 'reason_th': 'ยังไม่ยืนยันแหล่งอ้างอิง'}
    if unknown:
        return {'status': CONDITIONAL, 'is_binding': False, 'reason_th': 'มีเงื่อนไข: ' + '; '.join(unknown)}
    prefix = 'เข้าเงื่อนไข: ' + '; '.join(matched) + ' · ' if matched else ''
    if is_binding:
        return {'status': APPLICABLE, 'is_binding': True, 'reason_th': prefix + 'ยืนยันแหล่งแล้ว ต้องให้ผู้ตรวจยืนยันขอบเขตของ Assessment นี้'}
    return {'status': APPLICABLE, 'is_binding': False, 'reason_th': prefix + 'ใช้เป็นแนวปฏิบัติอ้างอิง ไม่ผูกพันตามกฎหมายโดยอัตโนมัติ'}
