# V16 changelog

## Unreleased

### Changed
- `/domains` is one page that opens up as you choose, in one bordered white frame with a soft shadow, filling the width of the page with the standard 32px side margins and no fixed maximum (so zooming the browser out never leaves empty bands on both sides; text lines are still limited to 72 characters; the pack page `/domains/<slug>` does the same, while other pages keep the standard 1360px maximum), with no step bar. First "งานของคุณอยู่ในด้านไหน?": the fields (Justice, Education, Health, Public administration, "other / not sure") are side by side as tiles; the chosen one is highlighted with a ring and a check in its group colour (`aria-pressed`). If the field has several kinds of organization (Justice 2, Education 3), cards for them appear below ("หน่วยงานของคุณคือแบบไหน?") and the chosen card is highlighted the same way; a field with one pack goes straight to the check card. The check card "ตรวจก่อนเริ่มประเมิน" appears below the choice. Top row: a chip with the field ("ด้านยุติธรรม · Justice"; the "other" field has no "ด้าน" in front), a version chip (`v…`, shown only to admin and committee because people who assess do not need it) and a "ฉบับร่างนำร่อง" chip for draft packs, with the one big start button on the right. Then the Thai name, the English name in capitals, and the summary in a soft tinted box (the draft note sits inside it). Three wide buttons, each with a tinted icon square (blue, navy, green), a label and a count with its unit, open more detail on demand, one at a time: "เตรียมอะไรไว้ก่อน" (N รายการ: the evidence documents with why each is needed), "จะถูกประเมินเรื่องอะไร" (N ประเด็น: the criteria with their Test Suites and the critical mark, plus the shared core criteria in a fold) and "กฎหมายและมาตรฐานที่อ้างอิง" (N ฉบับ: laws and requirements, then guidelines and standards, with the same status labels as elsewhere, so unverified states stay unshown). Below are two soft boxes with no divider lines: "ตัวอย่างงานที่ประเมินได้" (chips with an accent dot) and "เหมาะสำหรับ" (chips with a green dot; an organization type that another pack covers is a grey chip that jumps to that pack's card, with the note "สีเทา = หน่วยงานที่มีชุดประเมินของตัวเอง"). Panels start closed and close again when the card is replaced. Choosing another field or kind replaces what is below it. The address hash (`#education/higher_education`) keeps the choice, so the back button and shared links work. A strip offers "continue" for the person's most recent unfinished assessment. Users who may not start assessments (admin, committee) get the same page; pressing the start button explains why. The card has no "see everything" button; the pack pages (`/domains/<slug>`) stay as they were and are reached by address or, without JavaScript, from a plain list of links. Names, summaries, counts and examples come from the packs; the Thai name of a pack drops a trailing "(... Pack)", and the general pack is shown as "องค์กรทั่วไป".
- Groups: `domain_packs/v16/domain_groups.json` (validated on catalog sync) says which packs belong to which field, their icon, accent colour and example organizations, and marks an org type as covered by another pack, for display only (`ศาลปกครอง` under the justice pack is shown as a grey chip that jumps to the administrative court pack; the key is `covered_org_types`, checked on sync: the org type must exist and the target must be another pack). The pack pages and their URLs (`/domains/<slug>`) are unchanged.

### Added
- Collapsible sidebar. On screens 992px and wider, the menu button in the top bar folds the sidebar to a 72px icon rail and back. The choice is remembered in the browser (`localStorage` key `eigda.sidebar`) and applied from the page head before first paint, so a folded menu does not flash open. The motion keeps icons still (the rail width puts them at the centre already, and no padding or alignment changes between the two states) and fades labels while the sidebar clips them so they never wrap or pop. Menu labels stay in the page for screen readers. On the folded rail, hovering or keyboard-focusing an icon shows its name at once in a dark label beside it (one floating element made by `app.js`, so the sidebar's clipping cannot cut it). The button reports `aria-expanded`. On narrower screens the menu is still the slide-in drawer and the saved choice is ignored. `app.js` sends `eigda:layout-start` and `eigda:layout-end` around the width change, for pages that need to re-align after it.
- Spacing, border and radius standard (see `docs/V16_UI_SPACING.md`): a 4px-based scale (`--sp-1` to `--sp-7`), one border width, three radii and fixed sizes as tokens at the top of `v16.css`, applied to the app shell and the sidebar. Visible effects: top bar 72px high with the same side padding as the page (it was 28 against 32), page padding 24 / 32 / 48 (was 28 / 32 / 64), 40px logo, 24px menu icons. A test fails when the covered CSS uses a raw pixel value for padding, margin, gap or radius.

## 16.0-beta.1 (2026-11-05)

### Added
- Domain engine: applicability rules with reasons, inherent risk, configuration snapshots.
- Domain packs v2: 42 controls across 5 domains, each with evidence requirements and its own rubric. EMS taxonomy marked provisional.
- Regulatory Registry with 35 references, class and verification status, admin verification, and audit log.
- Taxonomy Explorer with tree, search, 7 filters, breadcrumb, and node details.
- 7-step guided assessment with save and resume.
- Rubric scoring with critical gates, human review, and five separate measures.
- Domain-aware KG export and finding traces.
- Portal, domain pages, assessments, evidence library, registry, reports, global search, notifications.
- Print report, CSV, and JSON exports. E2E suite using system Chrome.

### Changed
- Navigation and shell redesigned. The default landing page is `/overview`.
- Default `DEBUG` is False. Registration needs 10 or more characters. The `adminbuu` alias is now opt-in.
- The local model client splits a batch that returns no content. `LOCAL_MODEL_TOKEN_CAP` makes the former fixed 3500 cap configurable.
- `.env` for V16 leaves `LOCAL_MODEL_NAME` empty. The endpoint now reports a different model from the Gemma name configured before.

### Fixed
- Plaintext passwords shown on `/admin/users`.
- Thai text missing from generated PDFs.
- CSRF protection missing on most forms.
- Reloading `run-compliance` resending documents to a model.

### Removed
- V15 templates `user/domains.html` and `user/domain_workspace.html`, replaced by the new pages. The warning box you asked to remove from the Domain page stays removed.

### Unchanged by design
- The V14 hybrid formula and all historical scores.
