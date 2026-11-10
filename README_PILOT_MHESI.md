# Ei-GDA นำร่อง อว. / สป.อว.

ส่วนขยายของ V16 beta สำหรับการนำร่องกับกระทรวง อว. สำนักงานปลัดกระทรวง อว. (สป.อว.) และสถาบันอุดมศึกษาที่เข้าร่วม
ใช้ stack เดิม (Flask, SQLAlchemy, MySQL) และต่อยอดจาก scoring, Test Suite, Domain Pack, Evidence Mapping และ Committee Review ที่มีอยู่

เอกสารที่เกี่ยวข้อง:
- [คู่มือผู้ใช้ 3 บทบาท](docs/PILOT_USER_GUIDE.md)
- [ตาราง mapping ราย Control](docs/PILOT_CONTROL_MAPPING.md)
- [คู่มือ deploy การคุ้มครองเอกสาร และ retention](docs/PILOT_DEPLOY.md)
- [สรุปส่งมอบและรายการที่รออนุมัติ](docs/PILOT_HANDOFF.md)

## สิ่งที่เพิ่ม

| เรื่อง | ไฟล์หลัก |
|---|---|
| กติกาสิทธิ์กลางชุดเดียว (V16, Legacy, ไฟล์, export, API) | `services/access_policy.py` |
| หน่วยงาน สมาชิก รอบประเมิน ชุดเกณฑ์ ฉบับที่ส่ง ประเด็น แจ้งเตือน ทะเบียน AI | `models.py` (ท้ายไฟล์) |
| วงจรส่ง ทบทวน ส่งกลับ ปิดประเด็น พร้อม optimistic lock | `services/workflow.py` |
| สิทธิ์ส่งเอกสารให้โมเดล ค่าเริ่มต้นคือไม่อนุญาต | `services/model_gate.py` |
| ตรวจไฟล์แนบ PDF | `services/file_safety.py` |
| ชั้นเกณฑ์ร่วม, OPS-MHESI Pack, Higher Education Pack และทะเบียนอ้างอิง | `domain_packs/v16/{common_aidg,ops_mhesi,higher_education,regulatory_registry}.json` |
| หน้าใหม่ | `pilot_routes.py`, `templates/pilot/` |
| Migration ที่รันซ้ำได้ | `migrate_mhesi_pilot.py`, `services/schema_additions.py` |
| ข้อมูล DEMO | `seed_mhesi_pilot.py`, `services/pilot_demo.py` |
| Retention | `services/retention.py`, `purge_retention.py` |

## ติดตั้งและ migrate ฐานข้อมูลเดิม

```bash
source .venv/bin/activate
pip install -r requirements.txt

# 1. สำรองฐานก่อนทุกครั้ง (V15 และ V16 ใช้ฐาน tnagf_db ร่วมกัน คอลัมน์ที่เพิ่มเป็น nullable ทั้งหมด V15 จึงยังทำงานได้)
mysqldump -h 127.0.0.1 -u <user> -p tnagf_db > ../ei-gda-backups/tnagf_db_before_pilot_$(date +%Y%m%d_%H%M%S).sql

# 2. (แนะนำ) ซ้อม migration บนสำเนาจาก dump โดยไม่แตะ MySQL
python tools/verify_migration_on_dump.py ../ei-gda-backups/<dump>.sql /tmp/eigda-migration-copy

# 3. migrate ฐานจริง (รันซ้ำได้)
python migrate_v16_domain_engine.py     # ถ้ายังไม่เคยรัน
python migrate_mhesi_pilot.py
```

`python app.py` จะไม่ยอมเริ่มทำงานถ้าฐานข้อมูลยังไม่ได้รัน `migrate_mhesi_pilot.py` และจะแจ้งคำสั่งที่ต้องรัน
Docker (`AUTO_MIGRATE=True`) รัน migration นี้ให้อัตโนมัติ

Migration นี้ไม่ลบหรือเปลี่ยนข้อมูลเดิม และไม่ใส่ `organization_id` ให้งานเก่า งานเก่าจึงเปิดได้ตามสิทธิ์เดิม (เจ้าของ ผู้ดูแลระบบ และกรรมการที่ได้รับมอบหมาย) จนกว่าจะมีการยืนยันการผูกหน่วยงาน ระบบไม่อนุมานสมาชิกภาพจากชื่อองค์กรที่พิมพ์ไว้

## รัน DEMO (ฐานข้อมูลแยก)

```bash
python seed_mhesi_pilot.py --reset                    # สร้าง demo/pilot_demo.db และ demo/uploads
python seed_mhesi_pilot.py --reset --complete-case-b  # หรือให้กรณี B เดินจนยืนยันผลไว้แล้ว

DATABASE_URL=sqlite:///$(pwd)/demo/pilot_demo.db UPLOAD_FOLDER=demo/uploads REPORT_FOLDER=demo/reports \
DEMO_MODE=True GEMINI_API_KEY= LOCAL_MODEL_API_URL= python app.py
```

บัญชีทั้งหมดเป็น `<ชื่อ>@demo.invalid` รหัสผ่าน `Demo-Pilot-2569` (เปลี่ยนด้วย `--password`)

| บัญชี | บทบาท |
|---|---|
| `ops.coordinator` | ผู้ประสานรอบ สป.อว. (ดูสถานะ มอบหมายกรรมการ ไม่ได้รับสิทธิ์อ่านต้นฉบับ) |
| `ops.staff` | เจ้าหน้าที่ สป.อว. เจ้าของกรณี A |
| `mhesi.executive` | ผู้บริหาร อว. (ดูสรุปเท่านั้น) |
| `criteria.approver` | ผู้อนุมัติชุดเกณฑ์ |
| `buu.coordinator`, `buu.staff` | ผู้ประสานงานและเจ้าหน้าที่ มหาวิทยาลัยบูรพา (สถาบันตัวอย่าง ข้อมูลสมมติ) เจ้าของกรณี B |
| `rpu.coordinator` | มหาวิทยาลัยราชพฤกษ์ (สมมติ) ใช้ทดสอบว่าเห็นงานของหน่วยงานอื่นไม่ได้ |
| `committee1`, `committee2` | กรรมการ |
| `admin` | ผู้ดูแลระบบ (จัดการบัญชีและสิทธิ์ ไม่อ่านหลักฐานของหน่วยงาน) |

- **กรณี A:** สป.อว. ใช้ AI ตอบคำถามจากเอกสารเผยแพร่ ส่งงานแล้ว รอมอบหมายกรรมการ
- **กรณี B:** มหาวิทยาลัยส่งร่างนโยบาย AI/Data Governance พร้อมกรณี AI ช่วยคัดกรองผู้สมัคร

ข้อมูล DEMO ทุกรายการมีป้าย DEMO และไม่ใช่การรับรองจาก อว. หรือ สป.อว.
DEMO ไม่เรียกโมเดล ผลของระบบจึงมาจากหลักฐานที่พบ (`method = evidence_only`) แยกจากผลที่กรรมการยืนยัน

## ทดสอบ

```bash
python -m unittest discover -s tests -p 'test_*.py'      # 99 tests รวม 29 tests ของนำร่อง (tests/test_mhesi_pilot.py)

# Browser E2E ของกรณี B (ใช้ Chrome ในเครื่อง ฐาน SQLite ชั่วคราว ไม่แตะ MySQL หรือโมเดล)
pip install -r requirements-dev.txt
python tests/e2e/serve_pilot_demo.py /tmp/pilot-e2e 5117 &
python tests/e2e/run_pilot_e2e.py http://127.0.0.1:5117 /tmp/pilot-e2e/shots
```

หลังแก้ Domain Pack ให้รัน `python tools/export_control_mapping.py` เพื่อสร้างตาราง mapping ใหม่
