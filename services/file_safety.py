"""Attachment checks before a PDF is stored. Messages are in Thai and never echo file content."""
import fitz

# Active content that a governance evidence PDF has no reason to contain.
ACTIVE_MARKERS = (b'/JavaScript', b'/Launch', b'/EmbeddedFile', b'/RichMedia', b'/XFA')


def inspect_pdf(stream, max_pages=400):
    """Return a list of problems. Empty list = acceptable. The stream position is restored."""
    position = stream.tell()
    data = stream.read()
    stream.seek(position)
    problems = []
    if not data.startswith(b'%PDF-'):
        return ['ไม่ใช่ไฟล์ PDF']
    found = [m.decode() for m in ACTIVE_MARKERS if m in data]
    if found:
        problems.append('มีเนื้อหาที่ทำงานได้ (' + ', '.join(found) + ') จึงไม่รับไฟล์')
    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception:
        return problems + ['เปิดไฟล์ PDF ไม่ได้ อาจเสีย']
    try:
        if doc.needs_pass or doc.is_encrypted:
            problems.append('ไฟล์มีรหัสผ่านหรือเข้ารหัส')
        if doc.page_count > max_pages:
            problems.append(f'จำนวนหน้าเกิน {max_pages} หน้า')
    finally:
        doc.close()
    return problems
