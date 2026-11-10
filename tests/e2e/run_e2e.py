"""Real-browser E2E using the system Chrome. Requires: pip install -r requirements-dev.txt

Usage: python tests/e2e/run_e2e.py <base_url> <screenshot_dir>
"""
import io
import sys
from pathlib import Path

import fitz
from playwright.sync_api import expect, sync_playwright

BASE, SHOTS = sys.argv[1].rstrip('/'), Path(sys.argv[2])
SHOTS.mkdir(parents=True, exist_ok=True)
PASSWORD = 'e2e-test-password-1'
results = []


def check(name, condition, detail=''):
    results.append((name, bool(condition), detail))
    print(('PASS ' if condition else 'FAIL ') + name + (f' :: {detail}' if detail and not condition else ''), flush=True)


def make_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 60, 545, 780), text, fontsize=11)
    doc.save(path)
    doc.close()


def login(page, email):
    page.goto(BASE + '/login')
    page.fill('input[name=username_or_email]', email)
    page.fill('input[name=password]', PASSWORD)
    page.locator('form[method=post] button[type=submit], form[method=post] button').first.click()
    page.wait_for_url('**/overview')


def main():
    pdf = SHOTS / 'synthetic_ems_evidence.pdf'
    make_pdf(pdf, [
        'Synthetic EMS SOP for automated testing only. This standard operating procedure describes the emergency dispatch workflow. No real patient data.',
        'Triage guideline: operators assign urgency using the triage protocol. An undertriage review is performed monthly. Human override: the operator can override the AI suggestion and every override is recorded in the human override log.',
        'Escalation: when the model is not confident the case goes to the medical director. Training: all staff complete competency training before use.',
    ])
    fake = SHOTS / 'fake.pdf'
    fake.write_bytes(b'this is not a pdf')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1360, 'height': 900}, locale='th-TH')
        page = context.new_page()
        console_errors, server_errors = [], []
        page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: console_errors.append(str(e)))
        page.on('response', lambda r: server_errors.append(f'{r.status} {r.url}') if r.status >= 500 else None)

        login(page, 'owner@e2e.invalid')
        check('portal loads after login', page.locator('h1', has_text='EI-GDA Governance Intelligence Platform').is_visible())
        check('eight domain cards (5 original + 2 pilot + administrative court)', page.locator('.domain-card').count() == 8)
        check('portal stats are real zero', page.locator('.stat b').first.inner_text() == '0')
        page.screenshot(path=SHOTS / '01_portal.png', full_page=True)

        page.goto(BASE + '/domains/healthcare')
        page.get_by_role('tab', name='Test Suites').click()
        check('domain detail shows eight suites', page.locator('#t-suites details.acc').count() == 8)
        page.screenshot(path=SHOTS / '02_domain.png')

        page.goto(BASE + '/domains/healthcare/taxonomy')
        page.wait_for_selector('.tax-row')
        check('taxonomy tree renders', page.locator('.tax-row').count() >= 4)
        total = page.locator('#fCount').inner_text()
        page.select_option('#fCase', 'EMS.UC3')
        filtered = page.locator('#fCount').inner_text()
        check('use-case filter narrows controls', total != filtered, f'{total} / {filtered}')
        check('tree shows matching EMS-07', page.locator('.tax-row', has_text='EMS-07').count() >= 1)
        check('tree hides non-matching EMS-01', page.locator('.tax-row', has_text='EMS-01').count() == 0)
        page.locator('.tax-row', has_text='EMS-07').first.click()
        check('node detail lists evidence', 'หลักฐานที่ต้องใช้' in page.locator('#taxDetail').inner_text())
        check('breadcrumb shows path', page.locator('#taxCrumb span').count() >= 3)
        page.screenshot(path=SHOTS / '03_taxonomy.png', full_page=True)
        page.click('#fClear')
        page.fill('#fSearch', 'undertriage-no-such-term')
        check('search with no match empties controls', '0 จาก' in page.locator('#fCount').inner_text())
        page.fill('#fSearch', '')

        page.goto(BASE + '/assessments/new?domain=healthcare')
        page.fill('#name', 'E2E EMS Triage')
        page.fill('#organization_name', 'E2E Org')
        page.select_option('#org_type', 'HLT.ORG.EMS')
        page.screenshot(path=SHOTS / '04_step1.png', full_page=True)
        page.get_by_role('button', name='บันทึกและไปต่อ').click()
        page.wait_for_url('**/step/2')
        check('EMS stages are offered for EMS org', page.locator('#functional_area option', has_text='คัดแยก').count() == 1)
        check('hospital stages hidden for EMS org', page.locator('#functional_area option', has_text='ภาพทางการแพทย์').count() == 0)
        page.select_option('#functional_area', 'EMS.STAGE.3')
        page.select_option('#use_case', 'EMS.UC1')
        page.fill('#purpose', 'ช่วยเจ้าหน้าที่จัดลำดับความเร่งด่วน')
        page.locator('input[name=data_categories][value="HLT.DATA.HEALTH"]').check()
        page.locator('input[name=decision_impact][value=assistive]').check()
        page.screenshot(path=SHOTS / '05_step2.png', full_page=True)
        page.get_by_role('button', name='บันทึกและไปต่อ').click()
        page.wait_for_url('**/step/3')
        assessment_url = page.url.rsplit('/step', 1)[0]
        check('step 3 shows EMS Act', page.get_by_text('พระราชบัญญัติการแพทย์ฉุกเฉิน').count() >= 1)
        check('risk floor raised to critical', page.locator('.badge-s', has_text='วิกฤต').count() >= 1)
        check('owner has no confirm control', page.get_by_role('button', name='ยืนยันว่าใช้กับงานนี้').count() == 0)
        page.screenshot(path=SHOTS / '06_step3.png', full_page=True)

        page.goto(assessment_url + '/step/1')
        check('resume keeps values', page.input_value('#name') == 'E2E EMS Triage' and page.input_value('#org_type') == 'HLT.ORG.EMS')
        page.goto(assessment_url + '/step/4')
        check('all eight suites listed', page.locator('details.acc').count() == 8)
        page.locator('details.acc').nth(3).locator('summary').click()
        check('TS04 has EMS-02', page.locator('details.acc').nth(3).get_by_text('EMS-02').count() >= 1)
        check('exclusion reason shown', page.get_by_text('ไม่รวม:').count() >= 1)
        page.screenshot(path=SHOTS / '07_step4.png', full_page=True)
        page.get_by_role('button', name='ยืนยันขอบเขตและไปแนบหลักฐาน').click()
        page.wait_for_url('**/step/5')
        check('open option disabled for sensitive data', page.locator('input[name=data_classification][value=open]').is_disabled())
        page.locator('input[name=data_classification][value=confidential]').check()
        page.check('#ack')
        page.get_by_role('button', name='บันทึกระดับเอกสาร').click()
        page.wait_for_load_state()
        page.set_input_files('#pdf_files', str(fake))
        page.get_by_role('button', name='อัปโหลด').click()
        page.wait_for_load_state()
        check('fake PDF rejected', page.get_by_text('ไม่ใช่ไฟล์ PDF').count() >= 1)
        page.set_input_files('#pdf_files', str(pdf))
        page.get_by_role('button', name='อัปโหลด').click()
        page.wait_for_load_state()
        check('evidence listed with pages', page.get_by_text('3 หน้า').count() >= 1)
        check('located and missing are both shown', page.locator('.badge-s', has_text='พบ').count() >= 1 and page.locator('.badge-s', has_text='ยังขาด').count() >= 1)
        page.screenshot(path=SHOTS / '08_step5.png', full_page=True)
        page.set_input_files('#pdf_files', str(pdf))
        page.get_by_role('button', name='อัปโหลด').click()
        page.wait_for_load_state()
        check('duplicate upload skipped', page.get_by_text('ข้ามไฟล์ซ้ำ').count() >= 1)

        page.goto(assessment_url + '/step/6')
        page.screenshot(path=SHOTS / '09_step6.png', full_page=True)
        page.set_default_timeout(600000)
        page.get_by_role('button', name='เริ่มประเมิน').click()
        page.wait_for_url('**/results')
        page.set_default_timeout(30000)
        check('results reached', page.locator('.metric').count() == 5)
        check('five separate measures', all(page.get_by_text(t).count() >= 1 for t in ('สถานะความเสี่ยง', 'ความครอบคลุมหลักฐาน', 'ระดับ Governance', 'การปฏิบัติตามกฎหมาย', 'ความเชื่อมั่นของผล')))
        check('compliance not concluded', page.get_by_text('ยังสรุปไม่ได้').count() >= 1)
        check('critical issue is visible', page.locator('.notice-bad, .notice-warn').count() >= 1)
        check('chart drawn', page.locator('#suiteChart').evaluate('c => !!(window.Chart && Chart.getChart(c))'))
        run_note = page.locator('p.small-note').first.inner_text()
        print('RUN NOTE:', run_note, flush=True)
        page.wait_for_timeout(600)
        page.screenshot(path=SHOTS / '10_results.png', full_page=True)
        page.locator('.finding-row', has_text='EMS-01').click()
        page.wait_for_timeout(500)
        panel = page.locator('.offcanvas.show')
        check('finding traces to source file and page', 'synthetic_ems_evidence.pdf หน้า' in panel.inner_text(), panel.inner_text()[:200])
        check('finding traces to regulation', 'พระราชบัญญัติการแพทย์ฉุกเฉิน' in panel.inner_text())
        check('owner cannot review', panel.get_by_role('button', name='บันทึกผลตรวจ').count() == 0)
        page.screenshot(path=SHOTS / '11_finding.png')
        page.locator('.offcanvas.show .btn-close').click()
        page.goto(assessment_url + '/report')
        check('report loads', page.get_by_text('รายงานการประเมิน AI และ Data Governance').count() == 1)
        page.emulate_media(media='print')
        page.pdf(path=str(SHOTS / 'report_from_browser.pdf'), format='A4')
        page.emulate_media(media='screen')
        doc = fitz.open(SHOTS / 'report_from_browser.pdf')
        text = ''.join(p.get_text() for p in doc)
        check('printed PDF keeps Thai text', 'การประเมิน' in text, text[:120])
        doc.close()
        csv = page.request.get(assessment_url + '/report.csv')
        check('CSV export', csv.status == 200 and 'EMS-01' in csv.text())
        check('JSON export', page.request.get(assessment_url + '/report.json').status == 200)
        check('KG export', page.request.get(assessment_url + '/kg.json').status == 200)
        page.goto(BASE + '/overview')
        check('portal now counts real work', page.locator('.stat b').nth(3).inner_text() == '1' or page.locator('.stat b').nth(2).inner_text() == '1')
        check('notification lists pending item', page.locator('.notice-dot').count() == 1)

        other = browser.new_context()
        other_page = other.new_page()
        login(other_page, 'other@e2e.invalid')
        check('another user is denied', other_page.goto(assessment_url + '/results').status == 403)
        check('another user cannot read evidence list', 'synthetic_ems_evidence' not in (other_page.goto(BASE + '/evidence') and other_page.content()))
        status = other_page.evaluate("u => fetch(u, {method:'POST'}).then(r => r.status)", BASE + '/assessments/new')
        check('fetch wrapper supplies CSRF token', status in (200, 302, 400))
        raw = other.request.post(BASE + '/assessments/new', form={'name': 'x'}, max_redirects=0)
        check('POST without CSRF token is rejected', raw.status == 400, str(raw.status))
        other.close()

        admin_ctx = browser.new_context(viewport={'width': 1360, 'height': 900})
        admin = admin_ctx.new_page()
        admin.on('pageerror', lambda e: console_errors.append(str(e)))
        login(admin, 'admin@e2e.invalid')
        admin.goto(assessment_url + '/results')
        admin.locator('.finding-row', has_text='EMS-01').click()
        admin.wait_for_timeout(500)
        panel = admin.locator('.offcanvas.show')
        panel.locator('select[name=level]').select_option('1')
        panel.locator('textarea[name=note]').fill('บันทึกการแก้ไขยังไม่ครบตามเกณฑ์')
        panel.get_by_role('button', name='บันทึกผลตรวจ').click()
        admin.wait_for_load_state()
        check('reviewer decision saved', admin.get_by_text('บันทึกผลตรวจ EMS-01 แล้ว').count() >= 1)
        check('low critical level blocks gate', admin.locator('.notice-bad').count() >= 1)
        admin.goto(BASE + '/admin/users')
        check('admin users page has no password column', admin.locator('th', has_text='Password').count() == 0)
        admin.goto(BASE + '/regulations')
        check('registry no longer shows unverified-status labels', admin.get_by_text('รอตรวจสอบ').count() == 0 and admin.get_by_text('ปรับสถานะ').count() >= 1)
        admin.screenshot(path=SHOTS / '12_registry.png')
        admin_ctx.close()

        mobile = browser.new_context(viewport={'width': 390, 'height': 800}, is_mobile=True, has_touch=True)
        phone = mobile.new_page()
        login(phone, 'owner@e2e.invalid')
        overflow = lambda: phone.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
        check('portal has no horizontal scroll on phone', overflow() <= 1, str(overflow()))
        phone.screenshot(path=SHOTS / '13_mobile_portal.png', full_page=True)
        phone.locator('.sidebar-toggle').click()
        phone.wait_for_timeout(350)
        check('phone menu opens', phone.locator('.side-nav a').first.is_visible() and phone.locator('.app-sidebar').bounding_box()['x'] >= -1)
        phone.screenshot(path=SHOTS / '14_mobile_menu.png')
        phone.goto(assessment_url + '/results')
        check('results have no horizontal scroll on phone', overflow() <= 1, str(overflow()))
        phone.screenshot(path=SHOTS / '15_mobile_results.png', full_page=True)
        phone.goto(BASE + '/domains/healthcare/taxonomy')
        phone.wait_for_selector('.tax-row')
        check('taxonomy has no horizontal scroll on phone', overflow() <= 1, str(overflow()))
        mobile.close()
        browser.close()
    ignorable = ('favicon',)
    real = [e for e in console_errors if not any(i in e for i in ignorable)]
    check('no browser console errors', not real, '; '.join(real)[:400])
    check('no server errors', not server_errors, '; '.join(server_errors)[:400])
    failed = [r for r in results if not r[1]]
    print(f'\nE2E: {len(results) - len(failed)} passed, {len(failed)} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
