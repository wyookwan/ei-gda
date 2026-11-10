"""Browser E2E for pilot case B with the system Chrome: submit -> assign -> request evidence -> new evidence ->
resubmit -> committee closes the issue -> confirm -> OPS-MHESI dashboard. Plus cross-organization direct-link checks.

Usage: python tests/e2e/run_pilot_e2e.py <base_url> <screenshot_dir>
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.pilot_demo import TEXT_B2, make_pdf  # noqa: E402

BASE, SHOTS = sys.argv[1].rstrip('/'), Path(sys.argv[2])
SHOTS.mkdir(parents=True, exist_ok=True)
PASSWORD = 'Demo-Pilot-2569'
results = []


def check(name, condition, detail=''):
    results.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ') + name + (f' :: {detail}' if detail and not condition else ''), flush=True)


def main():
    evidence = SHOTS / 'buu_applicant_review_channel_e2e.pdf'
    evidence.write_bytes(make_pdf(TEXT_B2))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        errors = []

        def session(email):
            ctx = browser.new_context(viewport={'width': 1360, 'height': 900}, locale='th-TH')
            page = ctx.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda r: errors.append(f'{r.status} {r.url}') if r.status >= 500 else None)
            page.goto(BASE + '/login')
            page.fill('input[name=username_or_email]', email)
            page.fill('input[name=password]', PASSWORD)
            page.locator('form[method=post] button').first.click()
            page.wait_for_url('**/overview')
            return ctx, page

        def submit(page, label):
            with page.expect_navigation():
                page.get_by_role('button', name=label).first.click()

        # 1. University staff submits case B
        ctx, page = session('buu.staff@demo.invalid')
        page.goto(BASE + '/rounds')
        check('round page lists the university round', page.locator('.round-card', has_text='สถาบันอุดมศึกษา').count() >= 1)
        check('DEMO label visible', page.locator('.demo-tag').count() >= 1)
        page.screenshot(path=SHOTS / 'p01_rounds_university.png', full_page=True)
        page.locator('.round-card', has_text='สถาบันอุดมศึกษา').get_by_role('link', name='ติดตาม').first.click()
        page.wait_for_load_state()
        workflow_url = page.url
        assessment_id = re.search(r'/assessments/(\d+)/workflow', workflow_url).group(1)
        submit(page, 'ส่งงานครั้งแรก')
        check('status is submitted', 'ส่งครั้งแรกแล้ว' in page.locator('.wf-track li.cur').inner_text())
        check('revision 1 recorded', page.locator('summary', has_text='ฉบับที่ 1').count() == 1)
        page.screenshot(path=SHOTS / 'p02_submitted.png', full_page=True)
        ctx.close()

        # 2. Another university cannot reach case B, even by direct link
        ctx, page = session('rpu.coordinator@demo.invalid')
        response = page.goto(f'{BASE}/assessments/{assessment_id}/workflow')
        check('other university gets 403 on workflow', response.status == 403)
        response = page.goto(f'{BASE}/assessments/{assessment_id}/results')
        check('other university gets 403 on results', response.status == 403)
        response = page.goto(f'{BASE}/assessments/{assessment_id}/report.csv')
        check('other university gets 403 on export', response.status == 403)
        page.goto(f'{BASE}/evidence')
        check('other university evidence library has no case B file', page.locator('text=buu_ai_data_governance_policy_draft_demo.pdf').count() == 0)
        ctx.close()

        # 3. OPS-MHESI coordinator assigns a committee member
        ctx, page = session('ops.coordinator@demo.invalid')
        page.goto(workflow_url)
        page.select_option('#cmUser', value=page.locator('#cmUser option', has_text='committee1@demo.invalid').get_attribute('value'))
        submit(page, 'มอบหมาย')
        check('status is assigned', 'มอบหมายกรรมการแล้ว' in page.locator('.wf-track li.cur').inner_text())
        response = page.goto(f'{BASE}/assessments/{assessment_id}/results')
        check('coordinator cannot open results without source grant', response.status == 403)
        ctx.close()

        # 4. Committee reviews and requests evidence of the applicant review channel
        ctx, page = session('committee1@demo.invalid')
        page.goto(BASE + '/review-queue')
        check('review queue lists the assignment', page.locator('tbody tr', has_text='คัดกรองผู้สมัคร').count() == 1)
        page.screenshot(path=SHOTS / 'p03_review_queue.png', full_page=True)
        page.goto(workflow_url)
        submit(page, 'เริ่มทบทวน')
        page.locator('details:has(#isCtl)').evaluate('d => { d.open = true; }')
        page.select_option('#isCtl', value='HED-03')
        page.select_option('#isSev', value='critical')
        page.fill('#isReason', 'ยังไม่พบช่องทางให้ผู้สมัครขอทบทวนผลการคัดกรอง')
        page.fill('#isEv', 'ประกาศช่องทางขอทบทวนผลและบันทึกการพิจารณาคำร้อง')
        submit(page, 'เปิดประเด็น')
        check('issue opened', page.locator('.issue', has_text='HED-03').count() == 1)
        submit(page, 'ขอหลักฐานเพิ่ม')
        check('status is changes requested', 'ขอหลักฐานเพิ่ม' in page.locator('.wf-track li.cur').inner_text())
        page.screenshot(path=SHOTS / 'p04_changes_requested.png', full_page=True)
        ctx.close()

        # 5. University attaches new evidence, answers the issue and resubmits
        ctx, page = session('buu.staff@demo.invalid')
        page.locator('button[aria-label^="การแจ้งเตือน"]').click()
        check('notification about the request', page.locator('.notice-menu', has_text='มีคำขอหลักฐานเพิ่ม').count() == 1)
        page.goto(f'{BASE}/assessments/{assessment_id}/step/5')
        page.set_input_files('#pdf_files', str(evidence))
        page.select_option('#disclosure_class', value='public')
        page.select_option('#personal_data', value='none')
        submit(page, 'อัปโหลด')
        check('new evidence attached', page.locator('text=buu_applicant_review_channel_e2e.pdf').count() >= 1)
        page.goto(workflow_url)
        page.locator('.issue textarea[name=note]').fill('แนบประกาศช่องทางขอทบทวนผลและบันทึกคำร้องปี 2569 แล้ว')
        submit(page, 'บันทึกคำชี้แจง')
        submit(page, 'ส่งฉบับแก้ไข')
        check('status is resubmitted', 'ส่งฉบับแก้ไขแล้ว' in page.locator('.wf-track li.cur').inner_text())
        check('revision 2 shows the added file', page.locator('details', has_text='ฉบับที่ 2').locator('.badge-s', has_text='ใหม่').count() == 1)
        page.screenshot(path=SHOTS / 'p05_resubmitted.png', full_page=True)
        ctx.close()

        # 6. Committee re-reviews, closes the issue with the new evidence, records results and confirms
        ctx, page = session('committee1@demo.invalid')
        page.goto(BASE + '/review-queue')
        check('review queue flags new evidence', page.locator('tbody tr', has_text='หลักฐานใหม่').count() == 1)
        page.goto(workflow_url)
        submit(page, 'เริ่มทบทวนซ้ำ')
        issue = page.locator('.issue', has_text='HED-03')
        issue.locator('select[name=evidence]').select_option(value=issue.locator('select[name=evidence] option', has_text='buu_applicant_review_channel_e2e.pdf').get_attribute('value'))
        issue.locator('input[name=page]').fill('1')
        issue.locator('textarea[name=note]').first.fill('ประกาศระบุช่องทางและกรอบเวลา และมีบันทึกคำร้องจริง')
        submit(page, 'ยืนยันการปิดประเด็น')
        check('issue closed', page.locator('.issue', has_text='HED-03').locator('.badge-s', has_text='ปิดแล้ว').count() == 1)
        rows = lambda: page.locator('section:has(#resHead) tbody tr').filter(has_text='วิกฤต').filter(has_text='ยังไม่ยืนยัน')
        guard = 0
        while rows().count() and guard < 30:
            guard += 1
            row = rows().first
            row.locator('details:has(form)').evaluate('d => { d.open = true; }')
            row.locator('select[name=judgement]').select_option('sufficient')
            row.locator('textarea[name=reason]').fill('กรรมการตรวจหลักฐานสาธิตแล้ว')
            with page.expect_navigation():
                row.get_by_role('button', name='บันทึก').click()
        check('every critical control has a committee result', rows().count() == 0, f'remaining={rows().count()}')
        submit(page, 'ยืนยันผลการประเมิน')
        check('status is confirmed', 'ยืนยันผลแล้ว' in page.locator('.wf-track li.cur').inner_text())
        page.screenshot(path=SHOTS / 'p06_confirmed.png', full_page=True)
        ctx.close()

        # 7. OPS-MHESI dashboard shows the outcome
        ctx, page = session('ops.coordinator@demo.invalid')
        page.goto(BASE + '/rounds')
        page.locator('tr', has_text='สถาบันอุดมศึกษา').get_by_role('link', name='Dashboard').click()
        page.wait_for_load_state()
        stats = page.locator('.stat-row').inner_text()
        check('dashboard denominator is 2 participating universities', 'หน่วยงานที่เข้าร่วม' in stats and page.locator('.stat b').first.inner_text().strip() == '2')
        check('dashboard counts one confirmed', '1' in page.locator('.stat', has_text='ยืนยันผลครบ').inner_text())
        check('dashboard shows overdue university', page.locator('tbody tr', has_text='ราชพฤกษ์').locator('.badge-s', has_text='เกินกำหนด').count() == 1)
        check('dashboard row shows confirmed status', page.locator('tbody tr', has_text='บูรพา').locator('text=ยืนยันผลแล้ว').count() == 1)
        page.screenshot(path=SHOTS / 'p07_ops_dashboard.png', full_page=True)
        ctx.close()

        ctx, page = session('mhesi.executive@demo.invalid')
        page.goto(BASE + '/rounds')
        page.locator('tr', has_text='สถาบันอุดมศึกษา').get_by_role('link', name='Dashboard').click()
        page.wait_for_load_state()
        check('executive sees summary-only dashboard', page.locator('text=ไม่รวมรายละเอียดประเด็นและเอกสารต้นฉบับ').count() == 1)
        page.screenshot(path=SHOTS / 'p08_executive_dashboard.png', full_page=True)
        ctx.close()
        check('no server errors or page errors', not errors, '; '.join(errors[:5]))
        browser.close()
    failed = [n for n, ok in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
