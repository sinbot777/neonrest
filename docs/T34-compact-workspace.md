# Compact Zine workspace and issue trim sizes

The editor uses one Toolset select. Custom reveals Customize, a native modal with draft tool-group checkboxes and explicit Save/Cancel; Escape discards the draft because opening reloads saved choices. Preferences never rewrite page content or mark its form dirty.

Insert, Text, Layout, Arrange and Review task tabs organize the actual existing control nodes. Selection properties remain in one inspector. Layout contains starters, saved layouts, portable JSON, style guidance and Issue page size. No composition feature is removed.

Owner/editor draft issues support business card, postcard, A6, A5, half-letter, Letter, A4 and custom inch/mm trim dimensions. Minimum short side 2 inches, long side 3.5 inches; maximum either side 18 inches. Page size is stored separately in additive zine_issue_sizes; existing issues are unconfigured and retain previous rendering. Revision/CSRF/role/draft checks and transactional rollback apply. Revision snapshots include the prior size. Save page changes before opening issue size.

The underlying composition remains a 396 × 612 logical board. Scale content to fit preserves proportions and centers that board on the chosen trim page, leaving blank space for different aspect ratios. Keep current content size preserves its physical scale and rejects clipping. This is not a new freeform coordinate model or automatic paragraph reflow across an expanded page. Exact issue-size PDFs and double-width booklet sheets are supported; Letter/A4 fit the entire trim page onto the chosen paper. Margin/bleed and print-safe guide customization remain future work.

Validation: existing 54 component, 50 anchored-image, 23 composer DOM, 13 image-flow DOM, 15 style DOM, 51 toolset policy checks; added 21 issue size/PDF and 17 compact workspace/overlay DOM checks. Hosted full-app and live browser acceptance are separate deployment gates.
