# V16 regulatory model

Registry file: `domain_packs/v16/regulatory_registry.json`. It loads into `regulatory_references`. **This registry is not legal advice and has not had legal review.**

## Classes

`binding_legislation`, `mandated_standard`, `voluntary_standard`, `non_binding_guideline`. ISO, NIST, WHO, UNESCO, CEPEJ, and ASEAN entries are never binding, even once verified.

## Verification status

| Status | Meaning | Shipped entries |
|---|---|---|
| `expert_verified` | An admin confirmed the source and scope in the app, with a logged note | 0 |
| `source_confirmed` | Official publisher page responded on 2026-11-05. Scope not reviewed | 3 (NIST AI RMF, 2 WHO) |
| `source_indexed` | Found through search or the existing catalog. Automated access was blocked, so not opened | 11 |
| `pending_verification` | Official text not opened. Often only the authority's home page or secondary sources were reached | 20 |
| `draft` | Internal concept deck only, no source found | 1 (`TH-COURT-AI-RULE-2568`) |

Publication dates in the registry are years or gazette dates from secondary sources unless the note says otherwise. Effective dates are left empty rather than guessed, and no statutory section is asserted as a requirement.

## When a compliance conclusion is allowed

All of these must hold, otherwise the result is "not determined":

1. The reference is binding class.
2. An admin marked it `expert_verified` at `/regulations`.
3. An admin or assigned committee member confirmed it for this assessment in step 3.
4. A person reviewed the finding.

With the shipped data, every result reads "not determined". That is intentional.

## Applicability status

`applicable`, `conditional`, `not_applicable`, `pending_verification`. Each comes with a Thai reason. Overrides need a reason of at least 8 characters and are written to the audit log. Re-syncing the registry never overwrites `expert_verified`.

## Link to the V14 catalog

`standard_code` links a registry entry to `standards.code`. Those standards feed the optional Hybrid KG run.
