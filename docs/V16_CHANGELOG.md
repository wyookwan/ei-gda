# V16 changelog

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
