# Anchored artwork in text

Sandbox-only extension of the composition editor. No database migration.

Text frames accept up to six structured image anchors, at most sixteen on a page. An anchor includes a Unicode code-point position, publication artwork ID, description, placement (inline, wrap left/right or full width), width percentage, logical height, spacing, caption and credit. Source is plain text plus validated fields, never arbitrary HTML/CSS or an external image URL. Caption/credit text counts toward the 6000-character page text budget.

Select a text frame, open Images in this text, place the cursor in its Text field and insert artwork. Inline figures move with the text. Wrapped and full-width insertions attach to the selected paragraph's beginning. Choose an attached image to update, move or remove it. Image fit preserves the source aspect ratio within the chosen dimensions. Text edits adjust anchors, including deletions across an anchor and Unicode characters. Undo, duplicate, group copy/paste, mode changes and portable JSON retain the content. Reusable browser layouts clear nested artwork references, descriptions and credit.

The reader renders escaped source-order text and figures using native browser wrapping. PDF output uses bounded word wrapping, inline figures and float exclusions, retains selectable text/captions/credits, includes nested artwork in image budgets and rejects print overflow. Browser and print font metrics can differ; preview both before publication. No automatic continuation to another frame or page exists yet. Linked stories/frames remain a separate publishing phase; this release reflows inside the containing frame.

All nested references use existing publication/uploader/contact authorization, image access and print visibility checks. A block by an artwork uploader revokes reader/PDF access. No authentication or rate limits are relaxed.

Validation: schema limits, finite geometry, foreign artwork/atomic revision checks, exact asset enumeration, four placement modes, captions and credits in Letter/A4 reading/booklet PDFs, overflow rejection, CRLF/Unicode anchors and actual DOM editing events. Physical printing, tagged PDF and broader accessibility/device certification remain separate.

The publication artwork library also accepts a pasted PNG/JPEG/WebP via a labeled paste area. Pasting selects a file; Upload artwork performs the ordinary authenticated upload. The same two-MiB input limit and server-side processing/authorization apply. No automatic upload or clipboard polling.

## Sandbox deployment evidence

Installed after 470 isolated actual-app checks, 26 design/PDF checks and the hosted component/flow suite (54 existing component plus 50 anchored-image/print checks). Local DOM suites passed 23 existing editor, 13 anchored-image and six paste-event checks; reader, geometry and toolset regressions passed 45, 40 and 51 checks. Four-page PDF proofs were rendered and reviewed for inline, left/right wrapping and full-width artwork.

The connected browser file picker requires the extension's file-URL permission; no permission was changed. Media-download and later navigation calls timed out. Consequently the live signed-in upload/insertion walkthrough and narrow-screen image-flow check remain uncompleted. These are not represented as passed tests. The feature is installed in Sandbox; Production source remains unchanged. Broad assistive-technology and physical printer acceptance remain open.
