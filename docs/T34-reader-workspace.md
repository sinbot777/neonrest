# Reader views and focused workspace

Sandbox-only follow-up to the Advanced composition rollout, October 30, 2026.

- Single page, two-page spread and continuous-scroll views use the saved page renderer.
- Front and back covers stand alone. Interior pairs are 2–3, 4–5, etc.; odd interiors remain alone.
- Explicit reading mode stays in navigation links. Browser-local account preference supplies the default when no view is specified. Storage failure leaves explicit controls functional.
- Continuous scroll renders all authorized pages once, with page anchors for jump navigation.
- Sidebar thumbnails reuse the same safe saved-content macro. Sidebar can collapse without altering form data.
- Common composition actions remain above the canvas; layout starters, selection/grouping, arrange, library, checks, layers and portable JSON move into expandable inspector sections.
- Exact position and borders are collapsed by default. Saved-page comparison is available on demand instead of duplicating the canvas permanently.
- Existing elements, form fields, limits, authorization, revisions and PDF content are preserved. No schema migration or legacy conversion.

Validation: 54 component checks, 45 reader view checks (odd/even page counts, exact group membership, invalid views/pages, private access), 51 toolset checks, 40 geometry checks and 23 DOM event checks including moved controls and sidebar. Hosted acceptance and live browser verification are separate deployment gates.

This is the reader/workspace phase. Linked text flow, synchronized publication styles, shared master layouts, richer typography/wrapping, artwork credits, review workflows, professional print controls and accessible exports remain future work.
