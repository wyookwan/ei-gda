# EI-GDA V16 architecture

**One shared core + eight Test Suites + domain packs + evidence-grounded assessment.** No domain has its own application or its own suite tables.

```
domain_packs/v16/*.json ──sync──▶ profiles, taxonomy, controls, rubrics, registry (MySQL)
                                        │
Organization + AI use-case profile ─────▶ Applicability engine ─▶ configuration ─freeze─▶ snapshot
                                                                                            │
PDF evidence ─▶ page extraction ─▶ requirement location ─▶ model (routed by classification) ┤
                                                                                            ▼
                                     rubric scoring ─▶ findings ─▶ human review ─▶ summary, report, KG
```

## Modules

| File | Responsibility |
|---|---|
| `services/domain_catalog.py` | Loads packs and registry into tables, builds taxonomy, explorer payload |
| `services/applicability.py` | Pure rule engine: control and regulation status with reasons, inherent risk |
| `services/domain_orchestrator.py` | Builds and freezes configuration, locates evidence, calls the model, stores findings |
| `services/domain_rubric.py` | Pure scoring: evidence caps, states, critical gate, five separate measures |
| `services/domain_kg.py` | Namespaced assessment graph with provenance, and finding traces |
| `services/schema_additions.py` | Additive columns shared by migrations |
| `governance_routes.py` | Blueprint `gov`: portal, domains, taxonomy, wizard, evidence, registry, reports, search |
| `static/js/taxonomy.js` | Explorer with no framework or added dependency |

Names follow the brief's concepts: `DomainProfileService` and `TaxonomyService` are `domain_catalog`, `ApplicabilityEngine` is `applicability`, `DomainRubricService` is `domain_rubric`, `DomainAssessmentOrchestrator` is `domain_orchestrator`.

## Reused without change in logic

`kg_service`, `build_evidence_map`, `run_hybrid_compliance`, `pdf_service`, and the classic `/dashboard` flow. The Gemini and local clients gained an optional `instruction` argument. Calls that omit it behave as before.

A `DomainAssessment` owns a `DocumentCheck`, so evidence files, source-PDF access, committee assignment, and the optional V14 Hybrid run keep working.

## Design rules

- **Applicability is rules, never LLM.** Only people can confirm a legal scope.
- **The model cannot add evidence.** Only controls with located evidence are sent. Located evidence caps the level. Unknown control IDs in a model answer are dropped.
- **Five results stay separate:** risk status, evidence coverage, governance maturity, compliance, confidence. There is no combined score.
- **Critical gaps cannot be averaged away.** The gate reports each open critical control.
- **Frozen configuration.** Pack edits do not affect a frozen assessment. Once findings exist, the scope cannot be unlocked.
- **An owner cannot certify their own work.** Review needs an admin or an assigned committee member, enforced on the server.

## Domain-aware KG

Node types: `Domain`, `Organization`, `OrganizationType`, `FunctionalArea`, `AIUseCase`, `Regulation`, `Requirement`, `GovernanceControl`, `Evidence`, `AssessmentFinding`. Relations: `IN_DOMAIN`, `OPERATES`, `APPLIES_TO`, `DERIVED_FROM`, `REQUIRES_EVIDENCE`, `SUPPORTED_BY`, `CONTRADICTED_BY`, `ASSESSED_USING`.

The graph is computed from stored records and exported at `/assessments/<id>/kg.json`. It is not a separate graph store. `CONTRADICTED_BY` appears only when a reviewer records it. `Requirement` text is pack wording, not statutory text, and the provenance field says so.

## Access model

Lists and records are limited to owner, active assigned committee member, or admin. This is per user. Sharing evidence across one organization and true tenant isolation are not implemented.
