# สรุปส่งมอบ: นำร่อง อว. / สป.อว. (2026-11-10)

สำรองโค้ดก่อนแก้ไว้ที่ `ei-gda-backups/V16-beta-before-mhesi-pilot-20261110.tgz`
ไม่ได้ migrate ฐาน MySQL จริง (`tnagf_db` ใช้ร่วมกับ V15) เจ้าของระบบต้องสำรองฐานแล้วรัน `python migrate_mhesi_pilot.py` เอง

## ผลทดสอบ

| ชุดทดสอบ | คำสั่ง | ผล |
|---|---|---|
| Unit/integration ทั้งหมด | `python -m unittest discover -s tests -p 'test_*.py'` | **99/99 ผ่าน** (เดิม 70 + นำร่อง 29) |
| Browser E2E กรณี B (Chrome) | `tests/e2e/serve_pilot_demo.py` + `tests/e2e/run_pilot_e2e.py` | **27/27 ผ่าน** ไม่มี error ฝั่ง server หรือหน้าเว็บ |
| Browser E2E เดิมของ V16 (regression) | `tests/e2e/serve_e2e.py` + `tests/e2e/run_e2e.py` | **54/54 ผ่าน** |
| Migration บนสำเนาฐานเดิม | `python tools/verify_migration_on_dump.py ../ei-gda-backups/tnagf_db_before_v16_20261105_004504.sql <tmp>` | **ผ่าน** จำนวนแถวเท่าเดิมทุกตาราง, รันซ้ำไม่มีอะไรเพิ่ม, งานเดิม 0 รายการถูกผูกหน่วยงาน, เจ้าของเดิม 4/4 ยังเปิดได้ |
| Migration ฐานใหม่และฐาน schema เดิม | `tests/test_mhesi_pilot.py::Migration` | ผ่าน |

ชุดทดสอบเดิมที่ปรับ 4 จุด (ไม่ได้ลดสิ่งที่ตรวจ):
- `test_v16_domain.py`: จำนวน Domain 5 → 7 (เพิ่ม ops_mhesi และ higher_education)
- `test_v16_domain.py`: จำนวนคอลัมน์/ดัชนีที่ migration เพิ่ม 4 → 9 (เพิ่มคอลัมน์คุ้มครองเอกสาร 5 คอลัมน์)
- `test_provider_routing.py`: fixture ใส่กฎอนุญาตเริ่มต้นของโมเดล ซึ่งทุกฐานที่ migrate แล้วมีอยู่ ส่วน assertion ไม่เปลี่ยน
- `tests/e2e/run_e2e.py`: จำนวนการ์ด Domain 5 → 7

## เกณฑ์ผ่านขั้นต่ำ → test ที่พิสูจน์

| เกณฑ์ | ทดสอบ |
|---|---|
| มหาวิทยาลัย A เปิด ดู ค้น หรือส่งออกหลักฐานของ B ไม่ได้ แม้ใช้ลิงก์ตรง | `CrossOrganizationIsolation` (ตรวจ 13 เส้นทาง, ค้นหา, คลังหลักฐาน, นำไฟล์มาใช้ซ้ำ) และ E2E |
| กรรมการตรวจได้เฉพาะงานที่ได้รับมอบหมาย และสิทธิ์สิ้นสุดเมื่อถูกถอน | `CommitteeScope` |
| ผู้ประสานรอบหรือผู้บริหารเห็นข้อมูลตามขอบเขต | `OversightScope` (รวมผู้ดูแลระบบไม่อ่านหลักฐานของหน่วยงาน) และ E2E |
| เปลี่ยนชุดเกณฑ์แล้วงานเดิมยังแสดงเวอร์ชันและหลักฐานเดิม | `CriteriaVersionPinning` |
| เก็บฉบับแรก ฉบับแก้ไข และหลักฐานที่ใช้ปิดประเด็น | `FullLoopAndRevisions` และ E2E |
| เอกสารที่ไม่มีสิทธิ์ส่งเข้าโมเดลถูกบล็อกทั้งทางหลัก ทาง Legacy และการรันซ้ำ | `ModelGate` |
| การส่งซ้ำหรือเปลี่ยนสถานะพร้อมกันไม่ทำให้ข้อมูลหรือ audit trail ขัดกัน | `ConcurrentTransitions` (รวม 4 thread พร้อมกัน) |
| งานเก่าที่ไม่มี organization_id ยังเปิดได้ตามสิทธิ์เดิม | `LegacyCompatibility`, E2E เดิม 54/54 และการตรวจบนสำเนาฐาน |
| Migration ผ่านทั้งฐานใหม่และฐานที่มีข้อมูลเดิม | `Migration` และ `tools/verify_migration_on_dump.py` |
| ชุดทดสอบเดิมผ่าน | 70/70 ผ่าน ปรับตัวเลขตามรายการด้านบน |

## ไฟล์หลักที่เปลี่ยน

**ไฟล์ใหม่**
- `services/access_policy.py`, `services/workflow.py`, `services/model_gate.py`, `services/file_safety.py`, `services/retention.py`, `services/pilot_demo.py`
- `pilot_routes.py`, `templates/pilot/*`
- `domain_packs/v16/common_aidg.json`, `ops_mhesi.json`, `higher_education.json`
- `migrate_mhesi_pilot.py`, `seed_mhesi_pilot.py`, `purge_retention.py`
- `tools/verify_migration_on_dump.py`, `tools/export_control_mapping.py`
- `tests/test_mhesi_pilot.py`, `tests/fixtures/legacy_v16_schema.sql`, `tests/e2e/serve_pilot_demo.py`, `tests/e2e/run_pilot_e2e.py`
- `README_PILOT_MHESI.md`, `docs/PILOT_*.md`

**ไฟล์ที่แก้**
- `models.py`: ตารางใหม่ และคอลัมน์ nullable
- `app.py`: เส้นทาง Legacy ใช้กติกาสิทธิ์กลาง, model gate, log การเปิดไฟล์และดาวน์โหลด, ตรวจ schema ก่อนเริ่มทำงาน
- `governance_routes.py`: ใช้กติกาสิทธิ์กลาง, ล็อกงานระหว่างทบทวน, ป้ายกำกับเอกสาร
- `services/domain_orchestrator.py`: ชั้นเกณฑ์และการต่อยอด pack, ตรึงชุดเกณฑ์, model gate
- `services/domain_catalog.py`: layer pack, ตรวจการใช้แหล่งอ้างอิงผิด use case, seed กฎโมเดล
- `services/applicability.py`: excluded use case และการระงับการบังคับใช้
- `services/schema_additions.py`, `config.py`, `regulatory_registry.json`
- `templates/base.html`, `templates/gov/{wizard,results,_macros}.html`, `static/css/v16.css`, `docker/entrypoint.sh`, `.env.example`, `.gitignore`

## รายการที่รอการอนุมัติหรือข้อมูลจากหน่วยงาน

**เจ้าของเกณฑ์ (สป.อว. / อว.)**
1. ยืนยันฉบับ วันที่มีผล และข้อ/มาตราของแหล่งอ้างอิงที่เพิ่มทั้ง 15 รายการ
   - ตอนนี้ทุกรายการเป็น `pending_verification`
   - เข้าเว็บไซต์ อว. จากเครื่องพัฒนาไม่ได้ ส่วนราชกิจจานุเบกษาปฏิเสธการตรวจอัตโนมัติ (HTTP 403) จึงยังไม่ได้เปิดตัวบท
   - ข้อ/มาตราในตาราง mapping เป็นข้อเสนอที่รอตรวจ
2. ระบุชื่อ ฉบับ และปีของแนวปฏิบัติธรรมาภิบาลฉบับเดิมที่ถูกยกเลิกตามข้อ 3 ของประกาศ 5 มี.ค. 2569 (`MHESI-GOVERNANCE-PREV`)
3. ตัดสินว่าประกาศการเปิดเผยผลการดำเนินงาน พ.ศ. 2565 ใช้ร่วมกับฉบับ 2569 ได้หรือไม่
   ตอนนี้ระบบระงับการใช้เป็นเกณฑ์บังคับไว้
4. ระบุชื่อทางการและ URL ของประกาศ TUC เรื่องเอกสารอิเล็กทรอนิกส์และลายมือชื่อดิจิทัล
5. ส่งเอกสารภายในของ สป.อว. ได้แก่ นโยบายธรรมาภิบาลข้อมูล นโยบายคุ้มครองข้อมูลส่วนบุคคล แนวปฏิบัติข้อมูลข่าวสารลับอิเล็กทรอนิกส์ และกรอบไซเบอร์ 2569 พร้อมฉบับและข้อ
6. อนุมัติชุดเกณฑ์จริงในระบบจริง ชุดเกณฑ์ใน DEMO อนุมัติในสภาพแวดล้อมสาธิตเท่านั้น
7. อนุมัติกฎการส่งเอกสารให้โมเดลและระยะเวลา retention

**ข้อมูลเชื่อมต่อ (ยังเป็นสถานะ "เตรียมเชื่อมต่อ" ทั้งหมด)**
- **Digital Single View:** API contract และ schema, credentials, ขอบเขตข้อมูลที่อนุญาตให้ส่ง และการยืนยันรหัสอ้างอิงสถาบัน
  ตอนนี้ endpoint `/rounds/<id>/export/dsv.json` เตรียมข้อมูลที่ตรวจสิทธิ์แล้ว แต่ไม่ได้ส่งออกไปที่ใด
- **MHESI e-Office:** API contract, endpoint, credentials และรูปแบบเลขที่หนังสือ
- **ลายมือชื่อดิจิทัล TUC:** บริการลงนาม ใบรับรองของสถาบัน และขั้นตอนตรวจลายมือชื่อ
  ตอนนี้รายงานทุกฉบับแสดงสถานะ "ยังไม่ได้ลงนามดิจิทัล"

**การติดตั้ง**
- ยืนยันการเข้ารหัสที่พักของเครื่องจริงก่อนรับเอกสารที่ไม่ใช่เอกสารเผยแพร่ (ดู PILOT_DEPLOY.md)
- ยังไม่มีการสแกนมัลแวร์ของไฟล์แนบ
- ยังไม่ได้ทดสอบกับโมเดลจริงในงานนี้
  - DEMO และชุดทดสอบใช้ผลประเมินจากตำแหน่งหลักฐาน (`evidence_only`) ส่วน test ที่ต้องเรียกโมเดลใช้ mock
  - ผลเหล่านี้จึงไม่ใช่ผลประเมินจริงของโมเดล

## ข้อจำกัดที่ทราบ

- บทบาทระดับระบบ (`user` / `committee` / `admin`) ยังเป็นตัวกำหนดว่าใครเป็นกรรมการ สิทธิ์ระดับหน่วยงานเพิ่มผ่าน membership
- ผู้บริหารมีสิทธิ์ทั้งที่กระทรวงและหน่วยงานลูกหนึ่งระดับ (กระทรวง → สป.อว.)
- การยืนยันผลต้องให้กรรมการบันทึกผลครบเฉพาะ Control วิกฤตและ Control ที่มีประเด็น Control อื่นแสดงเป็น "ยังไม่ยืนยัน" แยกจากผลของระบบ
- การประเมินยังทำแบบ synchronous เหมือน V16 การส่งงานจึงประเมินเบื้องต้นใหม่ภายในคำขอเดียว
