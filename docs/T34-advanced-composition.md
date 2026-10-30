# Advanced Zine workspace expansion — prepared candidate

Sandbox target only. Prepared October 29, 2026 (Pacific). Not deployed.
Baseline: b30b26f5a79e1accf6b30b044f3331fd05b08421.

## Implemented in this candidate

- Saved-page thumbnail overview and facing-spread view.
- Drag or keyboard-accessible button ordering of interior pages; explicit Save order.
- Duplicate selected interior pages atomically while preserving author attribution.
- Multi-select and saved groups; group movement and keyboard movement.
- Alignment to selection bounds or page margins, equal-gap distribution.
- Copy/paste selections with fresh element and group IDs; undo and redo.
- Rotation with transformed page-bound checks, opacity, and element names.
- Artwork crop focus and replacement of matching artwork on the current page.
- Named layout library for the current account in this browser (up to twelve),
  with artwork references removed for reuse and portable JSON available separately.
- Headline, subheading, body, caption and quote text presets.
- Detailed page checks: browser text overflow, simple contrast, missing artwork and
  descriptions, approximate logical print DPI and an 18 pt text safe area.
- Custom mode includes selectable groups for the additional Advanced tools.
- Reader and vector/selectable-text PDF rendering apply rotation, opacity and crop focus.

No schema migration, automatic legacy conversion, or live content changes.
Existing caps of 32 elements/page, 64 pages/issue and 6000 composition text characters/page remain.

## Validation

- 40 pure composition geometry checks.
- 51 toolset preference and visibility checks.
- 54 local Flask/SQLite/template/PDF component checks. Identity, age and CSRF
  adapters are fixture-only; these checks do not replace hosted application acceptance.
- 19 DOM event checks against actual rendered Jinja markup, using jsdom.
- Python compile, JavaScript syntax, and Jinja parsing pass.
- Hosted full-app acceptance suite extended for Advanced fields and page operations;
  not yet run against this candidate.
- Signed-in browser acceptance, responsive checks and physical print pending.

Local checks:

    node tests/verify_zines_geometry.cjs
    node tests/verify_zines_toolsets.cjs
    python tests/verify_zines_advanced_local.py --dom-fixture
    NODE_PATH=<jsdom-node_modules> node tests/verify_zines_composer_dom.cjs /tmp/zine-dom-fixture.html

## Remaining professional publishing scope

Linked text flow across columns/pages; master pages and automatic running headers;
publication-wide durable styles/templates; richer typography and text wrapping;
full artwork credit/metadata and issue-wide replacement; page comments and review
status; generated contents/navigation; print bleed/crop/creep and color management;
accessible PDF tagging/reading order; larger document budgets after profiling.

The current local layout library is browser-specific, not synchronized publication
storage. Preflight is advisory and cannot model overlapping backgrounds or every
printer. PDF font metrics and browser text fit still require separate checks.

## Next release gate

Review source-only changes, upload to sinbot777/neonrest with explicit approval,
run the isolated hosted full-app suites, then install exact reviewed files into
Sandbox with rollback copies. Verify unchanged Production hashes, reload normally,
and complete the signed-in walkthrough. The GitHub upload was rejected by automatic
approval review for missing explicit source-upload authorization in this conversation.
