import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def font_name():
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        return 'STSong-Light'
    except Exception:
        return 'Helvetica'


def _draw_lines(c, lines, x, y, fname, size=10, step=14):
    c.setFont(fname, size)
    h = A4[1]
    for line in lines:
        if y < 50:
            c.showPage()
            c.setFont(fname, size)
            y = h - 40
        c.drawString(x, y, str(line)[:110])
        y -= step
    return y


def generate_system_report(path, report_data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fname = font_name()
    c = canvas.Canvas(path, pagesize=A4)
    y = A4[1] - 40
    filenames = report_data.get('filenames') or [report_data.get('filename','-')]
    y = _draw_lines(c, [
        'Ei-GDA Governance & Digital Assurance Report',
        f"Source documents: {len(filenames)}",
        *[f"  - {x}" for x in filenames[:20]],
        f"Test Suite: {report_data.get('template_name','-')}",
        f"Compliance: {report_data.get('compliance_score',0)}%",
        f"Maturity: {report_data.get('maturity_level','-')}",
        f"Classification: {report_data.get('data_classification','open')}",
        f"Processing: {report_data.get('processing_provider','-')}",
    ], 40, y, fname, 11)
    y -= 8
    y = _draw_lines(c, ['', 'Per Standard Summary:'], 40, y, fname, 11)
    y = _draw_lines(c, [f"{s['code']} - {s['name']}: {s['avg_score_0_to_5']}/5 ({s['percent']}%)" for s in report_data.get('standard_summary',[])], 40, y, fname, 10)

    items = report_data.get('compliance_items', [])
    if items:
        y = _draw_lines(c, ['', 'Compliance Items & Evidence:'], 40, y, fname, 11)
        for item in items:
            y = _draw_lines(c, [f"{item.get('item_code')} = {item.get('score')}/5 | {item.get('maturity','-')}", f"  {item.get('title','')}"], 40, y, fname, 9)
            ev = item.get('evidence') or []
            if ev:
                for e in ev[:3]:
                    y = _draw_lines(c, [f"  Evidence: {e.get('filename','-')} page {e.get('page','-')}: {e.get('snippet','')[:170]}"], 40, y, fname, 8, 12)
            else:
                y = _draw_lines(c, ['  Evidence: no page-level trace located'], 40, y, fname, 8, 12)
    c.save()


def generate_committee_report(path, report_data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fname = font_name()
    c = canvas.Canvas(path, pagesize=A4)
    y = A4[1] - 40
    y = _draw_lines(c, [
        'Committee Onsite Review Report',
        f"Committee: {report_data.get('committee_name','-')}",
        f"Document: {report_data.get('filename','-')}",
        f"System Compliance: {report_data.get('system_score',0)}%", '', 'Committee Scores:'
    ], 40, y, fname, 11)
    y = _draw_lines(c, [f"{x['item_code']} {x['title']} = {x['score']}/5" for x in report_data.get('committee_scores',[])], 40, y, fname, 10)
    y -= 10
    y = _draw_lines(c, ['Comments:'], 40, y, fname, 11)
    _draw_lines(c, (report_data.get('comments','') or '').splitlines(), 40, y, fname, 10)
    c.save()
