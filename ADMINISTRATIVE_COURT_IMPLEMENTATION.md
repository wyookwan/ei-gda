# Administrative Court Domain (ศาลปกครอง)

เพิ่มเมื่อ 2026-11-10 ในรูปแบบ Domain Pack เดียวกับที่ใช้เพิ่ม `ops_mhesi` และ `higher_education`
การเพิ่มนี้ไม่เปลี่ยน schema ไม่เปลี่ยนสูตรคะแนนของ Domain เดิม และไม่แตะ Domain `justice` ที่มีอยู่

- Domain ID: `administrative_court`
- ชื่อไทย: ศาลปกครอง
- ชื่ออังกฤษ: Administrative Court
- Category: Administrative Justice
- คำอธิบาย: การประเมินธรรมาภิบาล ความพร้อม และความน่าเชื่อถือของระบบ AI ที่ใช้ในงานศาลปกครอง

## สถาปัตยกรรมที่ใช้

| เรื่อง | วิธีในระบบนี้ |
|---|---|
| Domain Registry | `domain_packs/v16/administrative_court.json` ซึ่ง `sync_catalog` อ่านเข้าตาราง `domain_profiles`, `domain_controls`, `taxonomy_*` แบบ idempotent |
| Domain Selector, การสร้าง Assessment, Domain dropdown, การ์ด Domain | อ่านจาก Registry อัตโนมัติ ไม่มีเงื่อนไขเฉพาะ Domain ในโค้ด |
| Control ร่วมข้าม Domain | ใช้ชั้นเกณฑ์ร่วม `common_aidg` (CMN-01..08) ผลของแต่ละ Assessment แยกกันตาม `assessment_id` จึงไม่ปนข้าม Domain |
| Test Suite JUD-01..08 | **Domain overlay** (`domain_suites` ใน pack) จัดกลุ่ม Control เป็น Section และคำนวณผลแยก ซ้อนบน TS01–TS08 กลางที่ระบบมีอยู่ จึงไม่สร้าง Test Suite ซ้ำ และไม่กระทบคะแนน Domain อื่น |
| Assessment Item | ในเครื่องมือประเมินตาม Domain ของระบบนี้ หน่วยที่ถูกประเมินคือ Control (finding ราย Control) |
| ระดับคะแนน | ใช้ระดับ 0–3 ตาม rubric ของ Domain engine เดิม ไม่ใช่ 0–5 ของ Hybrid KG รุ่นเก่า |
| Knowledge Graph | เพิ่ม node `domain_suite` (`DSUITE.JUD-xx`) และ `test_case` (`SILA.JUD-SILA-xxx`) พร้อม edge ต่อไปนี้ ส่วน Control → กฎหมาย และ Control → หลักฐาน ใช้ edge เดิม |

Edge ที่เพิ่มใน Knowledge Graph:
- `HAS_DOMAIN_SUITE`: Domain → Domain Suite
- `GROUPS`: Domain Suite → Control
- `VALIDATED_BY`: Control → SILA Test Case

## สิ่งที่เพิ่ม

1. **Domain Pack** มีองค์ประกอบดังนี้:
   - ประเภทองค์กร 3 ประเภท: ศาลปกครองสูงสุด, ศาลปกครองชั้นต้น, สำนักงานศาลปกครอง
   - ภารกิจ 5 ด้าน และ Use Case 5 กรณี ได้แก่ ค้นคว้ากฎหมาย, สรุปสำนวน, ช่วยร่าง, คัดแยกคำฟ้อง, ตอบคำถามประชาชน
   - ประเภทข้อมูล 4 ประเภท และคำถามโปรไฟล์ 4 ข้อ
   - หลักฐาน 19 รายการ โดยแยกเป็นหลักฐานนโยบายกับหลักฐานการปฏิบัติจริง
2. **Control 10 ข้อ** ทุกข้อมีสถานะ `proposed`:
   - JUD-CTRL-001..005 ตามที่กำหนด
   - JUD-CTRL-006: ฐานอำนาจและการใช้บังคับของกฎหมาย
   - JUD-CTRL-007: ความโปร่งใส
   - JUD-CTRL-008: การตรวจทานผลลัพธ์
   - JUD-CTRL-009: ความเสี่ยงและเหตุการณ์ผิดปกติ
   - JUD-CTRL-010: ความถูกต้องของข้อมูลกระบวนพิจารณาต่อประชาชน

   ผมไม่ได้กำหนดจำนวนเพื่อให้ดูครบ แต่ละ JUD Suite มี Control ที่ผูกกับข้อกำหนดหรือข้อเสนอที่ระบุที่มาได้อย่างน้อย 1 ข้อ
   Control ที่เป็นข้อเสนอของโครงการใช้ประเภท `project_criteria` และอ้างแหล่ง `EIGDA-PILOT-CRITERIA`
3. **Critical Control** ที่สำคัญเสมอมี 4 ข้อ:

   | Control | ความเสี่ยงที่ครอบคลุม |
   |---|---|
   | JUD-CTRL-001 | AI ตัดสินคดีแทนผู้มีอำนาจ |
   | JUD-CTRL-002 | การอ้างคำพิพากษาที่ไม่มีอยู่จริง |
   | JUD-CTRL-003 | การเปิดเผยสำนวน หรือการขาดการควบคุมสิทธิ์ |
   | JUD-CTRL-010 | การให้ข้อมูลกระบวนพิจารณาที่ผิดพลาด |

   Control ที่สำคัญตามเงื่อนไข:
   - JUD-CTRL-005: เมื่อความเสี่ยงระดับสูง
   - JUD-CTRL-008: เมื่อผลลัพธ์ใช้ประกอบการวินิจฉัย
4. **Test Suite JUD-01..08** ทุกชุดมีรายละเอียดครบ ได้แก่ description, objective, sections, criticality, maturity mapping, assessment criteria และ SILA mapping
5. **ผลคะแนนที่เพิ่ม** (`services/domain_rubric.domain_suite_rollup`) คำนวณเฉพาะ pack ที่มี overlay:
   - ระดับ ความครบของหลักฐาน และความถูกต้องของหลักฐานที่กรรมการยืนยัน ราย Suite และราย Section
   - Critical Findings แสดงแยกจากคะแนนเฉลี่ย
   - Deployment Gate สถานะ `proposed` ซึ่งรอผู้มีอำนาจอนุมัติ
   - ความครอบคลุมแหล่งอ้างอิง
6. **Dashboard ราย Domain** `/domains/<slug>/dashboard` เป็นหน้าเดียวที่ใช้ได้กับทุก Domain แสดงข้อมูลต่อไปนี้:
   - Maturity เฉลี่ย และความครอบคลุมหลักฐาน
   - Critical Findings และหลักฐานที่ขาดบ่อย
   - กราฟ Radar ราย JUD Suite
   - ความครอบคลุมแหล่งอ้างอิง และสถานะ SILA

   นับเฉพาะงานที่ผู้ใช้มีสิทธิ์ดู ถ้ายังไม่มีผลจะแสดง "ยังไม่มีผลการประเมินสำหรับศาลปกครอง"
7. **หน้าผลประเมินและ Export** แสดงหัวข้อ "ชุดทดสอบเฉพาะ Domain" CSV เพิ่มคอลัมน์ `domain_suites`, `judgement`, `control_status` ส่วน JSON ได้ผล overlay มาใน `summary`
   ทั้งสองอย่างเพิ่มเฉพาะ Domain ที่มี overlay
8. **ตัวกรอง Domain** ในหน้ารายการการประเมิน (`/assessments?domain=...`)
9. **SILA:** ไม่มี SILA อยู่ใน repository จึงทำเฉพาะส่วนต่อไปนี้:
   - ข้อกำหนดชุดทดสอบ `domain_packs/v16/sila/administrative_court_redteam.json` จำนวน 8 กรณี ครบ 8 หมวด รวม JUD-SILA-001 ตามตัวอย่างที่ให้มา
   - `result_contract` ที่กำหนดรูปแบบผลที่ SILA ต้องส่งกลับ
   - API อ่านอย่างเดียว `/api/sila/test-packs/administrative_court` ซึ่งตอบ `integration_status: not_connected` และ `results: []`

   ทุกกรณีมีคำตอบอ้างอิงเป็น `null` และสถานะ `pending_expert_review` ระบบไม่สร้างผลทดสอบจำลอง

## แหล่งอ้างอิง (Registry)

ใช้ฉบับที่มีอยู่แล้วและเพิ่ม `administrative_court` ใน `domains` ได้แก่:
- พ.ร.บ.จัดตั้งศาลปกครองฯ 2542
- พ.ร.บ.ข้อมูลข่าวสารฯ 2540
- PDPA 2562
- พ.ร.บ.ไซเบอร์ 2562
- ISO/IEC 42001 และ 23894
- CEPEJ Charter 2018, CEPEJ GenAI 2025 และ UNESCO Courts 2025

เพิ่มใหม่ 12 ฉบับ:
- รัฐธรรมนูญ 2560
- ระเบียบที่ประชุมใหญ่ตุลาการฯ 2543
- พ.ร.บ.วิธีปฏิบัติราชการทางปกครอง 2539
- พ.ร.บ.ธุรกรรมทางอิเล็กทรอนิกส์ 2544
- พ.ร.บ.การปฏิบัติราชการทางอิเล็กทรอนิกส์ 2565
- ISO/IEC 27001, 27701, 38507, 22989, 5259 (ชุด), 25059 และ 5338

กติกาความถูกต้องของข้อมูลที่ใช้:
- **ทุกฉบับที่เพิ่มใหม่เป็น `pending_verification`** ไม่มีฉบับใดถูกบันทึกเป็น verified
- เว็บไซต์ศาลปกครองเข้าได้ (HTTP 200) แต่ยังไม่ได้เปิดตัวบท ส่วนราชกิจจานุเบกษาและ ISO ปฏิเสธการตรวจอัตโนมัติ (HTTP 403)
- ไม่สร้างเลขมาตราขึ้นเอง กฎหมายไทยทุกฉบับใช้ข้อความ "รอระบุมาตรา/ข้อจากตัวบทที่ตรวจแล้ว" ซึ่งมี test ตรวจไว้แล้ว
- ไม่คัดลอกข้อความมาตรฐาน ISO
- แยกประเภทเป็นกฎหมาย (binding), มาตรฐานที่เกี่ยวข้อง, แนวทางระหว่างประเทศ และเกณฑ์ที่โครงการเสนอ
- พ.ร.บ.วิธีปฏิบัติราชการทางปกครอง และ พ.ร.บ.การปฏิบัติราชการทางอิเล็กทรอนิกส์ ระบุชัดว่า "ต้องตรวจการใช้บังคับ ไม่ถือว่าใช้กับทุกกิจกรรมของศาลอัตโนมัติ"
- แหล่งที่ยังไม่ยืนยันไม่ถูกใช้สรุปการปฏิบัติตามกฎหมาย ผลจะเป็น `not_determined` ซึ่งมี test ตรวจไว้แล้ว

## Database และ Migration

- ไม่มีตารางหรือคอลัมน์ใหม่ Domain ใหม่เป็นข้อมูลใน pack ที่ sync เข้าตารางเดิม
- รันได้ด้วย `python migrate_administrative_court.py [--database-url ...]` ซึ่งเป็น idempotent และรายงานว่าจำนวนแถวไม่เปลี่ยน
  ฐานจริงต้องรัน `migrate_mhesi_pilot.py` ก่อน
- **Rollback:** ตั้ง `EIGDA_DISABLED_DOMAINS=administrative_court` แล้วรัน migrate อีกครั้ง Domain จะหายจากตัวเลือก แต่ข้อมูลไม่ถูกลบ และงานที่มีอยู่ยังเปิดได้ตามลิงก์
  เอาค่าออกแล้วรันใหม่เพื่อเปิดกลับ
- ไม่มีคำสั่ง drop, truncate หรือ reset

## ไฟล์ที่แก้

**ไฟล์ใหม่**
- `domain_packs/v16/administrative_court.json`, `domain_packs/v16/sila/administrative_court_redteam.json`
- `templates/gov/_domain_suites.html`, `templates/gov/domain_dashboard.html`
- `migrate_administrative_court.py`, `tests/test_administrative_court.py`, `ADMINISTRATIVE_COURT_IMPLEMENTATION.md`

**ไฟล์ที่แก้**

| ไฟล์ | สิ่งที่แก้ |
|---|---|
| `services/domain_catalog.py` | เพิ่ม Domain, overlay และ SILA ใน taxonomy, ตรวจความถูกต้องของ pack, rollback ด้วยการตั้งค่า, `get_pack(include_inactive)` |
| `services/domain_orchestrator.py` | ส่ง overlay ใน config เฉพาะ pack ที่มี |
| `services/domain_rubric.py` | `domain_suite_rollup` |
| `governance_routes.py` | Dashboard, SILA API, ตัวกรอง Domain, คอลัมน์ export |
| `templates/gov/{results,domain_detail,assessments,_macros}.html` | แสดงผล overlay, ส่วนชุดทดสอบเฉพาะ Domain, ตัวกรอง, ลิงก์ Dashboard |
| `static/js/taxonomy.js` | ป้ายชนิด node ใหม่ |
| `domain_packs/v16/regulatory_registry.json` | แหล่งอ้างอิงใหม่และการเพิ่ม Domain |
| `tools/export_control_mapping.py`, `docs/PILOT_CONTROL_MAPPING.md` | เพิ่มศาลปกครองในตาราง mapping |

นอกจากนี้แก้บั๊กเล็กจากรอบก่อน: การ์ด OPS-MHESI และ Higher Education เคยแสดงป้าย "EMS ฉบับชั่วคราว" ผิด ตอนนี้แสดงเป็น "เกณฑ์ที่เสนอ รอตรวจ"

## ผลทดสอบจริง (2026-11-10)

| ชุดทดสอบ | ผล |
|---|---|
| `python -m unittest discover -s tests -p 'test_*.py'` | **108/108 ผ่าน** (เดิม 99 + ศาลปกครอง 9) |
| Browser E2E นำร่อง อว. (`tests/e2e/run_pilot_e2e.py`) | **27/27 ผ่าน** ระบบ อว./สป.อว. ไม่ได้รับผลกระทบ |
| Browser E2E เดิมของ V16 (`tests/e2e/run_e2e.py`) | **54/54 ผ่าน** |
| Migration บนฐาน DEMO | ผ่าน ได้ 8 Domain, 70 Control, จำนวนแถวไม่เปลี่ยน |
| หน้า Domain, Dashboard และ Taxonomy ในเบราว์เซอร์ | ไม่มี error ฝั่งหน้าเว็บ Taxonomy แสดง 32 แถว |

`tests/test_administrative_court.py` ครอบคลุมเรื่องต่อไปนี้:
- ความครบของ pack และกติกาไม่สร้างเลขมาตรา
- Knowledge Graph (overlay → Control → SILA)
- SILA เป็นข้อกำหนดที่ไม่มีผลทดสอบ
- สร้างและประเมินผ่าน route จริง
- export CSV/JSON/KG
- Critical Control ไม่ถูกกลบด้วยค่าเฉลี่ย (ระดับเฉลี่ยมากกว่า 90% แต่ Gate ยัง blocked)
- Dashboard empty state และการแยกสิทธิ์ (ผู้ใช้อื่นไม่เห็นงานและได้ 403 ทั้งผลและ export)
- ตัวกรอง Domain และการ redirect ผู้ที่ยังไม่ล็อกอิน
- Domain อื่นมีโครงสร้าง summary เท่าเดิมทุกคีย์
- Rollback ด้วยการตั้งค่า

Assertion เดิมที่ปรับ (จำนวน Domain 7 → 8):
- `tests/test_v16_domain.py`
- `tests/test_mhesi_pilot.py`
- `tests/e2e/run_e2e.py`

## รายการที่รอการตรวจสอบ

- แหล่งอ้างอิงใหม่ 12 ฉบับ และข้อ/มาตราของทุก Control รอผู้เชี่ยวชาญตรวจกับตัวบทหรือฉบับมาตรฐานที่หน่วยงานถือ
  ยืนยันได้ที่หน้า "กฎหมายและมาตรฐาน" ด้วยบัญชีผู้ดูแล
- Control ทั้ง 10 ข้อ ชุด JUD-01..08 และ Deployment Gate ยังเป็น `proposed` จนกว่าผู้มีอำนาจของศาลปกครองจะอนุมัติ
- ชุดทดสอบ SILA ต้องให้ผู้เชี่ยวชาญกำหนดคำถาม คำตอบอ้างอิง แหล่งที่มา และวันที่มีผล (JUD-SILA-003 และ 004 รอคำถามจริง)

## ข้อจำกัด

- ยังไม่มีระบบ SILA ใน repository จึงยังไม่มีการรันชุดทดสอบหรือรับผลกลับ
- ยังไม่ได้ทดสอบกับโมเดลจริง ผลในการทดสอบมาจากตำแหน่งหลักฐาน (`evidence_only`)
- Domain `justice` เดิมยังมีประเภทองค์กร "ศาลปกครอง" อยู่ ระบบไม่ย้ายงานเดิมของ justice มาที่ Domain ใหม่โดยอัตโนมัติ
- ถ้าปิด Domain ด้วย rollback งานที่ยังไม่ยืนยันขอบเขต (ยังไม่ freeze) จะแก้ขั้นตอนตั้งค่าต่อไม่ได้จนกว่าจะเปิด Domain กลับ

## วิธีรันและตรวจสอบ

```bash
python migrate_administrative_court.py --database-url sqlite:///$(pwd)/demo/pilot_demo.db   # หรือฐานจริงหลังสำรองและ migrate นำร่องแล้ว
python -m unittest discover -s tests -p 'test_*.py'
```

จากนั้นเปิดหน้าต่อไปนี้:
- `/domains/administrative_court`: Test Suite JUD-01..08 และ Control
- `/domains/administrative_court/dashboard`: Dashboard
- `/domains/administrative_court/taxonomy`: Knowledge Graph
- `/api/sila/test-packs/administrative_court`: ข้อกำหนด SILA

เริ่มประเมินได้จาก "เริ่มประเมิน Domain นี้"

## ปรับปรุง 2026-11-10 (รอบที่ 2)

- **นำป้ายสถานะที่ยังไม่ยืนยันออกจากทุกหน้า** ได้แก่ "รอตรวจสอบ", "พบจากการค้นหา ยังไม่เปิดอ่าน", "พบแหล่งทางการ", "ร่าง ไม่พบแหล่ง", "Proposed" และ "เกณฑ์ที่เสนอ รอตรวจ"
  - แก้จุดเดียวที่ `status_badge` ใน `templates/gov/_macros.html`
  - ยังแสดงป้าย "ยืนยันโดยผู้ดูแล" เมื่อแหล่งได้รับการยืนยันจริง
  - คอลัมน์สถานะการตรวจสอบในทะเบียนแหล่งอ้างอิงแสดงเฉพาะผู้ดูแลระบบ เพราะเป็นผู้ยืนยันแหล่ง
  - กติกาไม่เปลี่ยน: แหล่งที่ยังไม่ยืนยันยังไม่ถูกใช้สรุปการปฏิบัติตามกฎหมาย
  - ป้าย DEMO และสถานะของงาน (ส่งแล้ว/ทบทวน/ยืนยันผล) ยังคงไว้ เพราะเป็นข้อมูลที่ผู้ใช้ต้องรู้
- **Export รายงานผลประเมินเป็น PDF:** `/assessments/<id>/report.pdf` (`services/assessment_pdf.py`)
  - เข้าถึงได้จากเมนู "ส่งออก" ในหน้าผล, ปุ่ม "ดาวน์โหลด PDF" ในหน้ารายงาน และลิงก์ในหน้ารายงานรวม
  - ใช้สิทธิ์ export เดียวกับ CSV/JSON และบันทึก audit
  - ใช้ฟอนต์ Sarabun ที่มีในระบบ ภาษาไทยวางวรรณยุกต์และสระถูกต้อง
  - เนื้อหาประกอบด้วย:
    - ข้อมูลงาน ชุดเกณฑ์ และ snapshot
    - สรุปผล
    - Test Suite (และชุด JUD-01..08 สำหรับศาลปกครอง)
    - ผลระบบเทียบกับผลผู้ตรวจราย Control
    - หลักฐานที่พบ (ชื่อไฟล์และหน้า)
    - ช่องว่างและข้อเสนอแนะ
    - แหล่งอ้างอิง
    - หมายเหตุว่ายังไม่ได้ลงนามดิจิทัล
- **ข้อจำกัด:** ข้อความไทยบางตัวใน PDF เมื่อคัดลอกหรือค้นหาออกมาอาจได้อักขระเพี้ยน (เช่น ไม้เอก) แต่การแสดงผลและการพิมพ์ถูกต้อง
- **ผลทดสอบ:**

  | ชุดทดสอบ | ผล |
  |---|---|
  | Unit/integration | 110/110 ผ่าน |
  | E2E นำร่อง | 27/27 ผ่าน |
  | E2E เดิมของ V16 | 54/54 ผ่าน |

  E2E เดิมปรับ 1 ข้อ: เดิมตรวจว่าทะเบียนแสดงป้าย "รอตรวจสอบ" ตอนนี้ตรวจว่าไม่แสดงแล้ว
