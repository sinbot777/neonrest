# Circle appearance and shared accessibility

October 21, 2026 Pacific. T13 and T18 implementation scope.

Circle owners can open Manage Circle → Circle appearance to save independent
day/night palettes, select System/Serif/Monospace fonts and square/soft/round
corners. Visitors choose Day theme or Night theme on the Circle page. Search
and page links preserve that choice. Reset theme restores the defaults without
removing the cover. Management and site navigation retain their own styles.

Only six-digit hex colors and listed font/corner values are accepted. Text and
links must contrast at least 4.5:1 against both the page and panel backgrounds;
button text is automatically black or white. Values become scoped custom
properties, never arbitrary CSS, selectors, remote URLs or HTML. Malformed
stored palettes fall back to defaults.

Covers accept JPEG/PNG/WebP up to 5 MiB and 16 million pixels. The server
applies orientation, fits the image within 1,600 × 600, flattens transparency,
and re-encodes JPEG without camera metadata. The original is not retained.
An optional, escaped image description supports meaningful or decorative
covers. Files use random names in the private instance/circle_covers directory.
Delivery rechecks the same Circle introduction/visibility guard as the icon,
including hidden/invited/public status, age, account, block and archive checks.
Responses use private, no-store caching. A discoverable Circle's introduction
and cover can be visible to eligible nonmembers; they are not post attachments.

Replacement/removal retires only the previous cover after the new database
reference commits. Failed image writes and failed database commits keep the
old reference and remove newly allocated files. Storage failures retain the
existing recoverable 507 response. Unknown, missing or malformed filenames
return 404. Archive preserves the cover for restoration. Schema changes add
three empty-default columns; old Circle metadata and content are not rewritten.
Include private instance/circle_covers alongside circle_icons in operational
instance backups. Covers follow existing Circle preservation; this change does
not enable account erasure or an automatic retention sweep.

Shared accessibility changes provide a keyboard-visible Skip to content link,
a focusable destination and a main landmark where a child template does not
already supply one. Post/comment option buttons have names and expansion
state. Arrow Down opens a disclosure and focuses its first action; Escape
closes it and restores the trigger. Outside clicks and leaving the group close
it. Comment editing focuses its labeled editor and returns to the options
button after cancellation or saving. Reply uses a real button. Avatars linking
to profiles and comment fields have accessible names.

Account labels are correctly bound to their fields. The profile quick composer has visible labels, expansion state, editor focus and Escape/focus return; its older post-menu override now preserves expansion state. Profile action buttons and sharing notices use paired readable colors.

Flash messages remain available instead of vanishing after three seconds.
Footer rotation has a saved pause control and pauses for reduced motion and
background tabs. Reduced-motion and forced-color styles, visible focus,
image-viewer button contrast, wrapped dropdowns and touch-sized Circle actions
round out the shared review. Profile content IDs are unique, and long post text wraps within the desktop feed column instead of forcing horizontal overflow. Existing native image/share dialogs and explicitly
loaded provider players retain their close/focus behavior.

Validation uses disposable database copies with SMTP disabled, owner/member/
moderator/outsider/teen cases, public and hidden cover delivery, CSRF/origin
checks, contrast/CSS-injection cases, metadata stripping, image limits, missing
files, replacement/removal, block/removal/archive revocation, and simulated
filesystem-full/database-full failures. Existing reading, following, recovery,
network-security, statistics, pagination, video, Circle, sharing and Sandbox
messaging/Afterglow regressions cover shared-template interactions.

Browser review uses exported fictional pages with form submissions and fetch
writes blocked. It covers Circle day/night/management at 320, 390, 768 and
1,280 CSS pixels, plus profile, composer, account and guide at narrow/tablet
widths. Keyboard opening/Escape, comment Edit/Cancel, skip navigation and footer
pause are checked in the browser. A separate JavaScript harness exercises
reduced-motion changes, saved choices, background tabs and landmark selection.
These are engineering checks, not a claim of independent WCAG certification or
every browser/assistive-technology combination. Owner acceptance remains a
separate walkthrough. Events/calendar remain T26; Afterglow remains Sandbox-only.
