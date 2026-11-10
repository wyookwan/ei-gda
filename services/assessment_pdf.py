"""Server-side PDF of a domain assessment report (PyMuPDF Story + bundled Sarabun font, so Thai is shaped correctly).

Content comes from the same result context as the on-screen report. Evidence is cited by file name and page only;
no document text beyond the short snippets already shown on the results page.
"""
import io
from datetime import datetime
from html import escape
from pathlib import Path

import fitz

FONT_DIR = Path(__file__).resolve().parent.parent / 'static' / 'fonts'
CSS = """
@font-face { font-family: th; src: url(Sarabun-Regular.ttf); }
* { font-family: th; }
body { font-size: 9.5pt; color: #0f1b2d; line-height: 1.35; }
h1 { font-size: 17pt; margin: 0 0 4pt 0; font-weight: normal; }
h2 { font-size: 12.5pt; margin: 12pt 0 4pt 0; padding-bottom: 2pt; border-bottom: 1px solid #0b6357; font-weight: normal; color: #0b6357; }
h3 { font-size: 10.5pt; margin: 6pt 0 2pt 0; font-weight: normal; }
p { margin: 2pt 0; }
.muted { color: #475467; font-size: 8.5pt; }
.box { border: 1px solid #c8d0c6; padding: 5pt; margin: 4pt 0; }
.bad { color: #b42318; }
table { border-collapse: collapse; width: 100%; margin-top: 3pt; }
th, td { border: 1px solid #c8d0c6; padding: 2.5pt 4pt; vertical-align: top; text-align: left; font-weight: normal; }
th { color: #0b6357; border-bottom: 1.5px solid #0b6357; }
"""
STATE = {'scored': 'ประเมินแล้ว', 'human_reviewed': 'ผู้ตรวจยืนยันแล้ว', 'not_applicable': 'ไม่เกี่ยวข้อง', 'not_assessed': 'ยังไม่ประเมิน',
         'insufficient_evidence': 'หลักฐานไม่พอ', 'pending_human_review': 'รอผู้ตรวจ'}
GATE = {'passed': 'ผ่าน', 'blocked': 'ยังมีช่องว่างวิกฤต', 'pending_review': 'รอผู้ตรวจยืนยัน', 'not_applicable': 'ไม่มี Control วิกฤต'}
RISK = {'critical_gap': 'มีช่องว่างวิกฤต', 'elevated': 'ต้องติดตาม', 'managed': 'อยู่ในการควบคุม', 'low': 'ต่ำ', 'medium': 'ปานกลาง', 'high': 'สูง', 'critical': 'วิกฤต'}
JUDGEMENT = {'sufficient': 'หลักฐานเพียงพอ', 'more_evidence': 'ขอหลักฐานเพิ่ม', 'not_met': 'ไม่เข้าเงื่อนไข'}
WORKFLOW = {'draft': 'ฉบับร่าง', 'submitted': 'ส่งครั้งแรกแล้ว', 'assigned': 'มอบหมายกรรมการแล้ว', 'in_review': 'อยู่ระหว่างทบทวน',
            'changes_requested': 'ขอหลักฐานเพิ่ม', 'resubmitted': 'ส่งฉบับแก้ไขแล้ว', 're_review': 'ทบทวนซ้ำ', 'confirmed': 'ยืนยันผลแล้ว'}


def _e(value):
    return escape('' if value is None else str(value))


def _wrap(value, run=24):
    """Escape and add invisible break points so long Thai runs (no spaces) and file names wrap inside the page.

    Breaks are inserted only before a Thai consonant, never before a vowel or tone mark, so glyphs stay attached.
    """
    import re
    text = _e(value)
    for sep in ('_', '-', '/'):
        text = text.replace(sep, sep + '\u200b')

    def split(match):
        word, out, count = match.group(0), [], 0
        for ch in word:
            if count >= run and '\u0e01' <= ch <= '\u0e2e':
                out.append('\u200b')
                count = 0
            out.append(ch)
            count += 1
        return ''.join(out)
    return re.sub(r'[^\s\u200b]{%d,}' % (run + 1), split, text)


def _pct(value):
    return '-' if value is None else f'{value}%'


def build_html(context, generated_at=None, demo=False):
    a, config, summary, rows = context['assessment'], context['config'], context['summary'], context['rows']
    generated_at = generated_at or datetime.utcnow()
    labels = config.get('labels') or {}
    profile = config.get('profile') or {}
    out = [f"<h1>รายงานผลการประเมิน: {_e(a.name)}</h1>",
           f"<p>{_e(a.organization_name)} · {_e(config.get('domain_title_th'))}"
           f"{' · ' + _e(labels.get(profile.get('use_case')) or profile.get('use_case_custom')) if (labels.get(profile.get('use_case')) or profile.get('use_case_custom')) else ''}</p>",
           f"<p class='muted'>สร้างเมื่อ {generated_at.strftime('%Y-%m-%d %H:%M')} UTC · pack {_e(a.pack_version)} · scoring {_e(a.scoring_version)}"
           f"{' · ชุดเกณฑ์ ' + _e(a.criteria_set.code) + ' ' + _e(a.criteria_version) if a.criteria_set else ''}"
           f"{' · สถานะงาน ' + WORKFLOW.get(a.workflow_status, '') if a.workflow_status else ''} · snapshot {_e((a.snapshot_hash or '')[:16])}</p>"]
    if demo or (a.criteria_set and a.criteria_set.is_demo):
        out.append("<div class='box'><p class='bad'>ข้อมูลสาธิต: ไม่ใช่การรับรองหรือผลประเมินจาก อว. หรือ สป.อว.</p></div>")
    out.append("<div class='box'><p>ผลนี้แสดงความพร้อมด้านธรรมาภิบาล ไม่ใช่คำวินิจฉัยการปฏิบัติตามกฎหมาย "
               "แหล่งอ้างอิงที่ยังไม่ได้รับการยืนยันไม่ถูกใช้สรุปการปฏิบัติตามกฎหมาย รายงานนี้ยังไม่ได้ลงนามดิจิทัล</p></div>")

    gate = summary.get('critical_gate') or {}
    out.append('<h2>สรุปผล</h2><table><tr><th>ระดับ Governance</th><th>ความครอบคลุมหลักฐาน</th><th>ความเสี่ยง</th><th>Control วิกฤต</th></tr>'
               f"<tr><td>{_pct(summary.get('maturity_percent'))} ({_e(summary.get('maturity_label'))})</td>"
               f"<td>{_pct(summary.get('evidence_coverage_percent'))} ({summary.get('requirements_located', 0)}/{summary.get('requirements_required', 0)})</td>"
               f"<td>{RISK.get((summary.get('risk') or {}).get('status'), '-')} · ตั้งต้น {RISK.get((summary.get('risk') or {}).get('inherent'), '-')}</td>"
               f"<td>{GATE.get(gate.get('status'), '-')}{' : ' + _e(', '.join(gate.get('open') or [])) if gate.get('open') else ''}</td></tr></table>")
    if a.run_note:
        out.append(f"<p class='muted'>{_wrap(a.run_note)}</p>")

    if summary.get('domain_suites'):
        dg = summary.get('deployment_gate') or {}
        out.append('<h2>ชุดทดสอบเฉพาะ Domain</h2>')
        out.append(f"<p>Deployment Gate (เกณฑ์ที่เสนอ): {_e({'blocked': 'ยังไม่ผ่าน', 'pending_review': 'รอผู้ตรวจ', 'eligible_pending_approval': 'ผ่านเกณฑ์ที่เสนอ รอผู้มีอำนาจอนุมัติ'}.get(dg.get('status'), '-'))}</p>")
        out.append('<table><tr><th>Test Suite</th><th>ระดับ</th><th>หลักฐานครบ</th><th>วิกฤตที่เปิด</th></tr>')
        for s in summary['domain_suites']:
            out.append(f"<tr><td>{_e(s['id'])} {_e(s.get('title_th'))}</td><td>{_pct(s.get('maturity_percent'))}</td>"
                       f"<td>{_pct(s.get('evidence_completeness_percent'))}</td><td>{_e(', '.join(s.get('critical_open') or [])) or '-'}</td></tr>")
        out.append('</table>')
    else:
        out.append('<h2>Test Suite</h2><table><tr><th>Test Suite</th><th>Control</th><th>ระดับ</th><th>วิกฤตที่เปิด</th></tr>')
        for s in summary.get('suites') or []:
            out.append(f"<tr><td>{_e(s['code'])} {_e(s['name'])}</td><td>{s.get('controls', 0)}</td><td>{_pct(s.get('maturity_percent'))}</td><td>{s.get('critical_open', 0)}</td></tr>")
        out.append('</table>')

    out.append('<h2>ผลราย Control</h2><table><tr><th width="46%">Control</th><th width="18%">สถานะ</th><th width="12%">ผลระบบ</th><th width="24%">ผลผู้ตรวจ</th></tr>')
    evidence_blocks = []
    for row in rows:
        f, c = row['finding'], row['control']
        if f.state == 'not_applicable':
            continue
        reviewer = '-'
        if f.human_level is not None:
            reviewer = f"{f.human_level}{' · ' + JUDGEMENT.get(f.judgement, '') if f.judgement else ''}"
        out.append(f"<tr><td>{_e(f.control_id)}{' (วิกฤต)' if f.critical else ''}<br/>{_wrap(c.get('title_th') or c.get('title'))}</td>"
                   f"<td>{STATE.get(f.state, _e(f.state))}</td><td>{'-' if f.proposed_level is None else f.proposed_level}</td><td>{reviewer}</td></tr>")
        lines = []
        for req in row['requirements']:
            hits = ', '.join(f"{_wrap(e['filename'])}{' หน้า ' + str(e['page']) if e.get('page') else ''}" for e in req['evidence'][:3])
            lines.append(f"<p>· {_wrap(req['title'])}: {hits or '<span class=\"bad\">ยังขาด</span>'}</p>")
        if lines:
            evidence_blocks.append(f"<h3>{_e(f.control_id)}</h3>" + ''.join(lines))
    out.append('</table>')
    if evidence_blocks:
        out.append('<h2>หลักฐานที่พบราย Control</h2>' + ''.join(evidence_blocks))

    gaps = [(row['finding'], row['control']) for row in rows if row['finding'].state != 'not_applicable' and (row['finding'].gap or row['finding'].recommendation)]
    if gaps:
        out.append('<h2>ช่องว่างและข้อเสนอแนะ</h2>')
        for f, c in gaps:
            out.append(f"<h3>{_e(f.control_id)} {_e(c.get('title_th'))}</h3>")
            if f.gap:
                out.append(f"<p>ช่องว่าง: {_wrap(f.gap)}</p>")
            if f.recommendation:
                out.append(f"<p>ข้อเสนอแนะ: {_wrap(f.recommendation)}</p>")

    refs = [r for r in config.get('references') or [] if r.get('status') != 'not_applicable']
    if refs:
        out.append('<h2>แหล่งอ้างอิงที่เกี่ยวข้อง</h2><table><tr><th>แหล่งอ้างอิง</th><th>ฉบับ</th></tr>')
        for r in refs:
            out.append(f"<tr><td>{_wrap(r.get('title_th') or r.get('title'))}</td><td>{_wrap(r.get('version'))}</td></tr>")
        out.append('</table>')
    return '<html><body>' + ''.join(out) + '</body></html>'


def render_pdf(html, title=''):
    story = fitz.Story(html=html, user_css=CSS, archive=fitz.Archive(str(FONT_DIR)))
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    page_rect = fitz.paper_rect('a4')
    area = page_rect + (40, 42, -40, -48)
    more = 1
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    doc = fitz.open(stream=buffer.getvalue(), filetype='pdf')
    for number, page in enumerate(doc, 1):
        page.insert_font(fontname='th', fontfile=str(FONT_DIR / 'Sarabun-Regular.ttf'))
        page.insert_text((40, page.rect.height - 24), f'Ei-GDA · หน้า {number}/{doc.page_count}', fontsize=7.5, fontname='th', color=(0.4, 0.45, 0.5))
    doc.set_metadata({'title': title, 'producer': 'Ei-GDA', 'creator': 'Ei-GDA'})
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data
