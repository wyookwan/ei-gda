"""V16 domain rubric scoring. Pure functions; the V14 hybrid score is untouched.

Five results stay separate on purpose: compliance findings, governance maturity,
evidence coverage, risk status and assessment confidence.
"""
SCORING_VERSION = 'domain-rubric/1'
SCORED, REVIEWED, NOT_APPLICABLE, NOT_ASSESSED, INSUFFICIENT, PENDING_REVIEW = (
    'scored', 'human_reviewed', 'not_applicable', 'not_assessed', 'insufficient_evidence', 'pending_human_review')


def coverage_cap(ratio, caps):
    """Highest level the located evidence can support. caps = [[upper_bound_exclusive, level], ...]."""
    for bound, level in caps:
        if ratio < bound:
            return level
    return caps[-1][1] if caps else 3


def clamp_level(value):
    try:
        return max(0, min(3, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def needs_human_review(rubric, critical, risk_level):
    policy = rubric.get('human_review', 'critical_or_high_risk')
    return policy == 'always' or critical or risk_level in ('high', 'critical')


def score_finding(control, located_requirements, model_item, rubric, risk_level, human=None):
    """Score one control from frozen inputs. Evidence caps the model; the model cannot add evidence."""
    required = control.get('evidence') or []
    located = [r for r in required if located_requirements.get(r)]
    ratio = round(len(located) / len(required), 3) if required else 0.0
    critical = bool(control.get('is_critical'))
    missing = [r for r in required if r not in located]
    base = {'control_id': control['id'], 'critical': critical, 'coverage_ratio': ratio, 'missing_requirements': missing}

    if control.get('final_status') == 'not_applicable':
        return {**base, 'state': NOT_APPLICABLE, 'level': None, 'proposed_level': None, 'confidence': None, 'method': 'applicability',
                'reason': control.get('reason_th', ''), 'gap': '', 'recommendation': ''}

    cap = coverage_cap(ratio, rubric.get('coverage_caps') or [[1.01, 3]])
    model_level = clamp_level((model_item or {}).get('score'))
    if not located:
        result = {**base, 'state': INSUFFICIENT, 'level': 0, 'proposed_level': 0, 'confidence': 'low', 'method': 'no_evidence',
                  'reason': 'ไม่พบหลักฐานที่ตรงกับข้อกำหนด จึงไม่สรุปผลจากการคาดเดา', 'gap': 'ยังไม่มีหลักฐานสำหรับ control นี้',
                  'recommendation': 'แนบหลักฐานตามรายการที่ยังขาด แล้วประเมินใหม่'}
    elif model_level is None:
        level = min(cap, 1)
        result = {**base, 'state': PENDING_REVIEW, 'level': level, 'proposed_level': level, 'confidence': 'low', 'method': 'evidence_only',
                  'reason': 'พบหลักฐานจากคำสำคัญ แต่ไม่มีผลจากโมเดล ระบบจึงให้ระดับเบื้องต้นและรอผู้ตรวจ',
                  'gap': 'ยังไม่มีการตีความเนื้อหาหลักฐาน', 'recommendation': 'ให้ผู้ตรวจอ่านหลักฐานและยืนยันระดับ'}
    else:
        level = min(cap, model_level)
        capped = level < model_level
        state = PENDING_REVIEW if needs_human_review(rubric, critical, risk_level) else SCORED
        reason = str((model_item or {}).get('reason') or '')
        if capped:
            reason = f'{reason} (โมเดลเสนอระดับ {model_level} แต่หลักฐานครอบคลุมพอสำหรับระดับ {cap})'.strip()
        result = {**base, 'state': state, 'level': level, 'proposed_level': level, 'method': 'rubric+model',
                  'confidence': 'medium' if ratio >= 0.67 else 'low', 'reason': reason,
                  'gap': str((model_item or {}).get('gap') or ''), 'recommendation': str((model_item or {}).get('recommendation') or '')}

    if human and human.get('level') is not None:
        result.update(state=REVIEWED, level=clamp_level(human['level']), confidence='high', method=result['method'] + '+human')
    return result


def compliance_status(finding, confirmed_binding_refs, gate_min_level):
    """Compliance is only concluded against expert-verified rules a reviewer confirmed for this assessment."""
    if finding['state'] == NOT_APPLICABLE:
        return 'not_applicable'
    if not confirmed_binding_refs:
        return 'not_determined'
    if finding['state'] != REVIEWED:
        return 'pending_review'
    return 'evidence_supports' if (finding.get('level') or 0) >= gate_min_level else 'gap_identified'


def maturity_label(percent):
    if percent is None:
        return 'ยังประเมินไม่ได้'
    if percent < 25:
        return 'Initial'
    if percent < 50:
        return 'Developing'
    if percent < 75:
        return 'Defined'
    return 'Managed'


def summarize(findings, config):
    """Deterministic rollup. Critical gaps are reported separately so an average cannot hide them."""
    rubric = config['rubric']
    gate_min = rubric.get('gate_min_level', 2)
    findings = sorted(findings, key=lambda f: f['control_id'])
    active = [f for f in findings if f['state'] != NOT_APPLICABLE]
    scored = [f for f in active if f['state'] != NOT_ASSESSED and f.get('level') is not None]

    states, confidence = {}, {'low': 0, 'medium': 0, 'high': 0}
    for f in findings:
        states[f['state']] = states.get(f['state'], 0) + 1
        if f.get('confidence') in confidence:
            confidence[f['confidence']] += 1

    required, located = 0, 0
    by_id = {c['id']: c for c in config['controls']}
    for f in active:
        count = len(by_id.get(f['control_id'], {}).get('evidence') or [])
        required += count
        located += count - len(f.get('missing_requirements') or [])
    coverage = round(100 * located / required, 1) if required else None

    maturity = round(100 * sum(f['level'] for f in scored) / (3 * len(scored)), 1) if scored else None
    by_finding = {f['control_id']: f for f in active}
    suites = []
    for suite in config['suites']:
        rows = [by_finding[c] for c in suite['control_ids'] if c in by_finding]
        with_level = [r for r in rows if r.get('level') is not None]
        suites.append({'code': suite['code'], 'name': suite['name'], 'controls': len(rows),
                       'maturity_percent': round(100 * sum(r['level'] for r in with_level) / (3 * len(with_level)), 1) if with_level else None,
                       'critical_open': sum(1 for r in rows if r['critical'] and not _critical_met(r, gate_min))})

    critical = [f for f in active if f['critical']]
    open_critical = [f for f in critical if not _critical_met(f, gate_min)]
    failed = [f for f in open_critical if f['state'] in (INSUFFICIENT, REVIEWED, SCORED) or (f.get('level') or 0) < gate_min]
    gate = 'passed' if critical and not open_critical else ('not_applicable' if not critical else ('blocked' if failed else 'pending_review'))

    compliance = {}
    for f in findings:
        key = f.get('compliance_status') or 'not_determined'
        compliance[key] = compliance.get(key, 0) + 1

    inherent = config['risk']['level']
    if gate == 'blocked':
        risk_status = 'critical_gap'
    elif gate == 'pending_review' or (coverage is not None and coverage < 50):
        risk_status = 'elevated'
    else:
        risk_status = 'managed'

    overlay = domain_suite_rollup(active, config, gate_min, gate) if config.get('domain_suites') else None

    total_conf = sum(confidence.values())
    overall_conf = None
    if total_conf:
        overall_conf = 'high' if confidence['high'] == total_conf else ('medium' if confidence['low'] * 2 <= total_conf else 'low')
    return {'scoring_version': SCORING_VERSION, 'rubric': {'id': rubric.get('id'), 'version': rubric.get('version'), 'gate_min_level': gate_min},
            'evidence_coverage_percent': coverage, 'requirements_required': required, 'requirements_located': located,
            'maturity_percent': maturity, 'maturity_label': maturity_label(maturity), 'suites': suites,
            'compliance': compliance, 'states': states, 'confidence': confidence, 'confidence_overall': overall_conf,
            'risk': {'inherent': inherent, 'status': risk_status},
            'critical_gate': {'status': gate, 'open': [f['control_id'] for f in open_critical], 'total': len(critical)},
            'pending_review': states.get(PENDING_REVIEW, 0), **(overlay or {})}


def _critical_met(finding, gate_min):
    return finding['state'] in (REVIEWED, SCORED) and (finding.get('level') or 0) >= gate_min


def domain_suite_rollup(active, config, gate_min, gate):
    """Extra results for packs with a domain suite overlay. Pure and deterministic; other domains never call it.

    Critical controls are listed separately: a high average cannot hide an open critical control.
    """
    by_id = {f['control_id']: f for f in active}
    controls = {c['id']: c for c in config['controls']}

    def stats(ids):
        rows = [by_id[i] for i in ids if i in by_id]
        leveled = [r for r in rows if r.get('level') is not None]
        required = sum(len(controls.get(r['control_id'], {}).get('evidence') or []) for r in rows)
        missing = sum(len(r.get('missing_requirements') or []) for r in rows)
        reviewed = [r for r in rows if r['state'] == REVIEWED]
        critical_open = [r['control_id'] for r in rows if r['critical'] and not _critical_met(r, gate_min)]
        return {'controls': len(rows), 'not_applicable': len([i for i in ids if i not in by_id]),
                'maturity_percent': round(100 * sum(r['level'] for r in leveled) / (3 * len(leveled)), 1) if leveled else None,
                'evidence_completeness_percent': round(100 * (required - missing) / required, 1) if required else None,
                'evidence_validity_percent': round(100 * sum(1 for r in reviewed if r.get('judgement') == 'sufficient' or (not r.get('judgement') and r.get('human_stance') == 'supported')) / len(reviewed), 1) if reviewed else None,
                'critical_open': critical_open,
                'status': 'not_applicable' if not rows else ('critical_gap' if critical_open else ('not_assessed' if not leveled else 'assessed'))}

    suites = []
    for suite in config['domain_suites']:
        ids = list(dict.fromkeys(c for section in suite.get('sections', []) for c in section.get('control_ids', [])))
        row = {'id': suite['id'], 'title_th': suite.get('title_th'), 'criticality': suite.get('criticality'), 'status_of_framework': suite.get('status', 'proposed'), **stats(ids)}
        row['sections'] = [{'id': sec['id'], 'title_th': sec.get('title_th'), **stats(sec.get('control_ids', []))} for sec in suite.get('sections', [])]
        suites.append(row)
    refs = {r['source_id']: r for r in config.get('references', [])}
    used = sorted({ref for f in active for ref in controls.get(f['control_id'], {}).get('references', [])})
    verified = [r for r in used if refs.get(r, {}).get('verification_status') == 'expert_verified']
    critical_findings = [{'control_id': f['control_id'], 'state': f['state'], 'level': f.get('level')} for f in active if f['critical'] and not _critical_met(f, gate_min)]
    deployment = {'policy_status': 'proposed', 'note_th': 'เกณฑ์ที่เสนอ ยังไม่ได้รับอนุมัติจากผู้มีอำนาจ',
                  'status': {'passed': 'eligible_pending_approval', 'blocked': 'blocked', 'pending_review': 'pending_review'}.get(gate, 'not_applicable')}
    return {'domain_suites': suites, 'critical_findings': critical_findings, 'deployment_gate': deployment,
            'legal_reference_coverage': {'references': len(used), 'expert_verified': len(verified), 'pending': len(used) - len(verified),
                                         'note_th': 'แหล่งอ้างอิงที่ยังไม่ยืนยันไม่ถูกใช้สรุปการปฏิบัติตามกฎหมาย'}}
