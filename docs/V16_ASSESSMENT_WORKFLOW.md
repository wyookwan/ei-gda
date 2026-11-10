# V16 assessment workflow

| Step | What happens | Who |
|---|---|---|
| 1 Organization & Domain | Name, organization, domain, organization type | Owner |
| 2 AI Use Case | Function, use case or custom, purpose, users, affected persons, data categories, impact, lifecycle, domain questions | Owner |
| 3 Regulations | Candidates grouped by class, with reason and verification status | Reviewer confirms or excludes |
| 4 Test Suites | All 8 suites, controls with reasons | Reviewer overrides with a reason. Owner freezes |
| 5 Evidence | Classification, upload, reuse, located and missing items, manual mapping | Owner |
| 6 AI assessment | Readiness check, then run | Owner |
| 7 Results | Five measures, critical gate, findings, traces, export | Reviewer confirms findings |

Every step saves on submit. `/assessments/<id>` resumes where the user left off.

## Inherent risk

The higher of the user's impact answer and the use-case floor (which cannot be lowered), combined with data sensitivity: `safety_critical` gives critical, `significant` or sensitive data gives high, personal data gives medium. Minors raise it to at least high.

## Data protection during a run

- Open goes to Gemini. Confidential goes to the local model only. There is no fallback between them.
- Sensitive data forces Confidential.
- Evidence from a Confidential assessment cannot be reused in an Open one.
- If the model fails, findings stay at an evidence-only provisional level and wait for review.

## Rubric

Levels 0 to 3. States: `scored`, `human_reviewed`, `not_applicable`, `not_assessed`, `insufficient_evidence`, `pending_human_review`.

```
no located evidence  -> insufficient_evidence, level 0, no model score used
no model answer      -> pending_human_review, level min(cap, 1)
model answer         -> level = min(evidence cap, model level)
reviewer decision    -> human_reviewed, level as decided (kept across re-runs)
```

Evidence caps and the critical minimum vary by domain. Healthcare needs every requirement located to reach level 3.

Evidence location uses keywords. A hit shows where to read and is not proof, which is why the reviewer step exists.

## Exports

Print view (browser Save as PDF keeps Thai), CSV with neutralized spreadsheet formulas, JSON, and KG JSON.
