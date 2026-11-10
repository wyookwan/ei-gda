"""Regenerate docs/PILOT_CONTROL_MAPPING.md from the pilot packs and the registry (single source of truth)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / 'domain_packs' / 'v16'
TYPES = {'law': 'กฎหมาย', 'standard': 'มาตรฐาน', 'internal_notice': 'ประกาศ/นโยบายภายใน', 'guideline': 'แนวทางแนะนำ', 'project_criteria': 'เกณฑ์ที่โครงการเสนอ'}
CLASSES = {'binding_legislation': 'กฎหมาย', 'mandated_standard': 'มาตรฐานภาครัฐ', 'internal_policy': 'ประกาศ/นโยบายภายใน', 'voluntary_standard': 'มาตรฐานที่เกี่ยวข้อง',
           'non_binding_guideline': 'แนวทางแนะนำ', 'project_criteria': 'เกณฑ์ที่โครงการเสนอ'}


def cell(text):
    return str(text or '-').replace('|', '\\|').replace('\n', ' ')


def main():
    registry = {r['source_id']: r for r in json.loads((PACKS / 'regulatory_registry.json').read_text())['references']}
    lines = ['# ตาราง mapping ราย Control (นำร่อง อว./สป.อว. และศาลปกครอง)', '',
             '> สร้างจาก `domain_packs/v16/*.json` ด้วย `python tools/export_control_mapping.py` อย่าแก้ไฟล์นี้ด้วยมือ',
             '> ยังไม่มีแหล่งอ้างอิงใดได้รับการยืนยันโดยผู้มีสิทธิ์ (expert_verified) แหล่งที่เพิ่มใหม่ทั้งหมดเป็น **pending_verification** และข้อ/มาตราที่ระบุเป็นข้อเสนอที่รอตรวจกับตัวบท', '']
    for slug in ('common_aidg', 'ops_mhesi', 'higher_education', 'administrative_court'):
        pack = json.loads((PACKS / f'{slug}.json').read_text())
        lines += [f"## {pack['title_th']} (`{slug}` เวอร์ชัน {pack['pack_version']})", '']
        if pack.get('extends'):
            lines += [f"ต่อยอด Education Pack: ใช้ Control {', '.join(pack['extends_controls'])} ร่วมด้วย (ตามเงื่อนไขเดิมของ Control นั้น)", '']
        if pack.get('layers'):
            lines += [f"ใช้ชั้นเกณฑ์ร่วม: {', '.join(pack['layers'])} และแกนกลาง general", '']
        lines += ['| Control | ชื่อ | ประเภทข้อกำหนด | ขอบเขต | แหล่งอ้างอิงและข้อ/มาตรา | หลักฐานนโยบาย | หลักฐานการปฏิบัติ | ประเด็นสำคัญ | สถานะตรวจสอบ | เวอร์ชัน |',
                  '|---|---|---|---|---|---|---|---|---|---|']
        ev = {e['id']: e['title_th'] for e in pack['evidence_requirements']}
        for c in pack['controls']:
            refs = '<br>'.join(f"{cell((registry.get(x['source_id']) or {}).get('title_th') or x['source_id'])} ({CLASSES.get((registry.get(x['source_id']) or {}).get('normative_class'), '-')}): {cell(x['clause'])}" for x in c['reference_clauses'])
            status = sorted({(registry.get(r) or {}).get('verification_status', '?') for r in c['references']})
            critical = 'สำคัญเสมอ' if c.get('critical') else ('สำคัญเมื่อ ' + cell(c.get('critical_condition_th') or json.dumps(c.get('critical_when'), ensure_ascii=False)) if c.get('critical_when') else '-')
            lines.append(f"| {c['id']} | {cell(c['title_th'])} | {TYPES.get(c['requirement_type'], c['requirement_type'])} | {cell(c['scope_th'])} | {refs} | "
                         f"{cell(', '.join(ev.get(e, e) for e in c['evidence_policy']))} | {cell(', '.join(ev.get(e, e) for e in c['evidence_practice']))} | {critical} | {', '.join(status)} | {c['version']} |")
        lines.append('')
    lines += ['## ทะเบียนแหล่งอ้างอิงที่เพิ่มสำหรับนำร่อง', '', '| รหัส | ชื่อเอกสาร | ผู้ออก | ฉบับ | วันที่มีผล | ประเภท | ขอบเขต | สถานะ | หมายเหตุ |', '|---|---|---|---|---|---|---|---|---|']
    for sid, r in registry.items():
        if {'ops_mhesi', 'higher_education', 'common_aidg', 'administrative_court'} & set(r.get('domains', [])):
            notes = []
            if r.get('supersedes'):
                notes.append('ยกเลิก ' + ', '.join(r['supersedes']))
            if r.get('superseded_by'):
                notes.append('ถูกยกเลิกโดย ' + r['superseded_by'] + ' (เก็บไว้สำหรับผลย้อนหลัง)')
            if r.get('enforcement_hold'):
                notes.append('ระงับการใช้เป็นเกณฑ์บังคับ: ' + r.get('hold_reason_th', ''))
            if r.get('not_basis_for_th'):
                notes.append(r['not_basis_for_th'])
            notes.append(r.get('verification_note') or '')
            lines.append(f"| {sid} | {cell(r.get('title_th'))} | {cell(r.get('issuing_authority'))} | {cell(r.get('version'))} | {cell(r.get('effective_date'))} | "
                         f"{CLASSES.get(r['normative_class'], r['normative_class'])} | {cell(r.get('scope_th') or r.get('condition_th'))} | {r['verification_status']} | {cell(' · '.join(n for n in notes if n))} |")
    (ROOT / 'docs' / 'PILOT_CONTROL_MAPPING.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('written', len(lines), 'lines')


if __name__ == '__main__':
    main()
