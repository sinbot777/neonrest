# Theme editor work — October 22, 2026 (Pacific)

Prepared source; not deployed or fully accepted.

## T19: separate unsaved edits from saved revisions

Undo/Redo track up to 50 form states, including shared logo/welcome fields,
nullable colors and CSS indentation. Discard unsaved changes restores the
entire form to its page-load state and can itself be undone. This is the reset
behavior: it does not replace a theme with factory defaults or write a revision.
Navigation away from dirty edits invokes the browser's normal unload warning.
Each Day/Night editor has independent local history; nothing is stored locally
after the page closes. Save explicitly persists edits.

Saved-version restoration retains its existing server implementation and
authorization/CSRF checks. Only the selected mode's style is restored; its
replaced style is kept in history. Shared Vibe identity remains unchanged.
Restoration now has visible feedback and mode/revision labels. Duplicate CSRF
fields were removed. The contrast checker now reads the editor form.

## T20: style JSON import/export

Version 1 uses `{format: "neonrest-theme", version: 1, mode, style}`. Supported
style fields are custom_css, bg_color, text_color, glow_color, background_layers,
blend_mode and font_stack. File size is limited to 128 KiB; individual fields
also have type/length limits. Colors accept hex or null. Unknown keys, wrong
mode/version, malformed JSON and HTML script/style/frame markup are rejected
before changing any field. Missing fields retain their current values; null
clears fields. The format excludes identifiers, credentials and shared identity.

Import reads a local file into unsaved edits as one undoable operation. It does
not submit the form or upload/publish the file. Export includes current unsaved
style values. This is style portability, not a gallery license or a claim that
arbitrary CSS is harmless. Existing editor permissions still govern publishing.

## T21: live preview and visual controls

The isolated current-mode preview updates from CSS and visual fields without a
save. It uses a sandboxed opaque-origin iframe, a restrictive CSP, static sample
content and escaping that prevents CSS from closing its style element. Remote
requests, scripts, forms and external fonts/images are blocked. It approximates
the Vibe classes/variables and is not an exact saved-page rendering. Existing
Day/Night editor links remain, with dirty-navigation warning. Empty font now has
an explicit inherited-font option. Seven semantic color controls cover panel, ink,
accent, glow, border, pill and pill text, with explicit inheritance. They update
a marked mode-scoped CSS block, so existing storage and import/export preserve
them. Custom CSS outside that block is retained. Live layout/visual acceptance
remains open.

## Validation and release boundary

Tests execute the actual edit route and template against fictional SQLite:
restoration permissions, CSRF, invalid/cross-mode revisions, null values,
preserved prior styles, unchanged identity and Day/Night isolation (16 checks).
The actual rendered editor runs in jsdom for Undo/Redo/Discard, Tab indentation,
Unset handling, navigation warning, contrast/CSRF, import/export, mode rejection,
single-operation import undo and isolated-preview updates. Separate tests cover
history bounds/branching, transfer validation and preview containment.

No live source or database was changed. Before deployment, run disposable-copy
full-app checks in both environments, inspect Day/Night and narrow layouts in
the connected browser, and perform normal backed-up installation/reload. T19
and T20 remain pending rollout/acceptance; T21 also remains pending live visual acceptance. T22 licensing,
attribution, inheritance and gallery approval are untouched. T48 remains in its
separate draft PR.
