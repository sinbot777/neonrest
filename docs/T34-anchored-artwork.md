# Anchored artwork in text

Sandbox-only extension of the composition editor. No database migration.

Text frames accept up to six structured image anchors, at most sixteen on a page. An anchor includes a Unicode code-point position, publication artwork ID, description, placement (inline, wrap left/right or full width), width percentage, logical height, spacing, caption and credit. Source is plain text plus validated fields, never arbitrary HTML/CSS or an external image URL. Caption/credit text counts toward the 6000-character page text budget.

Select a text frame, open Images in this text, place the cursor in its Text field and insert artwork. Inline figures move with the text. Wrapped and full-width insertions attach to the selected paragraph's beginning. Choose an attached image to update, move or remove it. Image fit preserves the source aspect ratio within the chosen dimensions. Text edits adjust anchors, including deletions across an anchor and Unicode characters. Undo, duplicate, group copy/paste, mode changes and portable JSON retain the content. Reusable browser layouts clear nested artwork references, descriptions and credit.

The reader renders escaped source-order text and figures using native browser wrapping. PDF output uses bounded word wrapping, inline figures and float exclusions, retains selectable text/captions/credits, includes nested artwork in image budgets and rejects print overflow. Browser and print font metrics can differ; preview both before publication. No automatic continuation to another frame or page exists yet. Linked stories/frames remain a separate publishing phase; this release reflows inside the containing frame.

All nested references use existing publication/uploader/contact authorization, image access and print visibility checks. A block by an artwork uploader revokes reader/PDF access. No authentication or rate limits are relaxed.

Validation: schema limits, finite geometry, foreign artwork/atomic revision checks, exact asset enumeration, four placement modes, captions and credits in Letter/A4 reading/booklet PDFs, overflow rejection, CRLF/Unicode anchors and actual DOM editing events. Physical printing, tagged PDF and broader accessibility/device certification remain separate.
