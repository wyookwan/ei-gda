# V16 domain taxonomy

**Status: pilot draft. Every control awaits domain-expert review.** Control names and suite mappings start from `EI-GDA-Domain-Taxonomy-4Slides.pptx`.

## Hierarchy

`Domain → Organization Type → Functional Area → AI Use Case → Governance Dimension → Control → (Regulation | Evidence | Rubric | Test Suite)`

Relationships are many-to-many edges in `taxonomy_edges`. All nodes have stable IDs such as `EMS.UC1`, `JUS-03`, `REG.TH-PDPA-2562`. Display names are not keys.

## Current content

| Domain | Org types | Controls | Rubric | Critical minimum |
|---|---|---|---|---|
| Justice | 3 | 6 | `RUBRIC.JUSTICE` | 3 |
| Education | 3 | 8 | `RUBRIC.EDUCATION` | 2 |
| Healthcare & EMS | 3 | 13 | `RUBRIC.HEALTHCARE` | 3 |
| Local Government | 3 | 7 | `RUBRIC.LOCALGOV` | 2 |
| General (shared core, inherited by all) | 3 | 8 | `RUBRIC.GENERAL` | 2 |

## EMS is provisional

No EMS final report, TOR, use-case specification, or official protocol was found in the workspace. The 8 stages, 3 use cases, and `EMS-01` to `EMS-08` are marked `provisional` and shown as such. No NIEMS regulation or validated outcome was invented. `TH-NIEMS-SUBORDINATE` is an explicit placeholder. The system assesses governance readiness, not diagnostic accuracy. A system is treated as a medical device only when the user answers yes to `medical_device_scope`.

## Editing a pack

Edit `domain_packs/v16/<slug>.json`, raise `pack_version`, then run `python migrate_v16_domain_engine.py`. Records removed from a pack become inactive and are never deleted. Each distinct pack is stored in `domain_pack_versions`.

Control rule example:

```json
{"id": "EDU-05", "suites": ["TS04", "TS08"], "references": ["TH-CHILD-PROTECT-2546"], "evidence": ["EV.EDU.GUARDIAN"],
 "critical": true, "applies_when": {"flags": {"involves_minors": true}}}
```

Selectors: `org_types`, `functional_areas`, `use_cases`, `data_categories_any`, `data_categories_min_sensitivity`, `min_risk`, `flags`. A mismatch excludes the control. A missing answer makes it conditional. `critical_when` can raise a control to critical in a given context.

The V15 packs in `domain_packs/*.json` remain for the older per-check Domain Evidence Review page.
