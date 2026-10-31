# Compact Zine tools and issue sizes - October 31, 2026 (Sandbox)

The Zine composer now groups tools under Insert, Text, Layout, Arrange and Review, with selection controls in one inspector and Save alongside common actions. A single Toolset dropdown replaces mode buttons. Custom reveals Customize with a modal of draft choices, Save and Cancel. Page size lives under Layout: business card, postcard, A6, A5, half-letter, Letter, A4 and custom inch/mm dimensions, orientation, a preview and scale/keep behavior. Minimum trim size is 3.5 × 2 inches in either orientation; maximum is 18 inches per side. Sizes apply to an entire draft issue and persist through an additive size table with editor/CSRF/revision checks. Existing issues retain their previous behavior until configured. Compositions remain on the existing logical board, scaled proportionally and centered; different page shapes can leave blank space. Full-page freeform coordinate changes, margins and bleed controls remain future work. Exact-size reading-order and double-width booklet PDF sheets are available alongside Letter/A4 fitting.

Local validation passed 21 new size/PDF checks and 17 compact workspace/overlay checks, plus the existing component, image-flow, composer, style and toolset regressions. Hosted and signed-in browser acceptance are recorded separately. Sandbox only.

# Zine style explanations - October 30, 2026 (Sandbox)

Style & graphic elements now shows an updating native-renderer example for Classic, Punk or the current composition, with explanatory text for every graphic field. Front/interior/back contexts identify unused controls; empty fields use labeled example copy. Enlarge example provides a closer view. Previews never submit or rewrite page content. Local checks passed three native page contexts and fifteen DOM-event cases plus the existing component suite; hosted acceptance and live visual verification remain separate gates.

# Anchored Zine artwork - October 30, 2026 (Sandbox)

Sandbox text frames now support anchored inline images, left/right text wrapping and full-width images between paragraphs, with image descriptions, sizing, spacing, captions and credits. Text edits move the anchors; undo, duplication, mode changes and portable layouts preserve them. Reusable layouts clear private artwork references. The artwork library also accepts pasted PNG/JPEG/WebP images through the ordinary upload form. Reader and selectable-text PDF exports use the saved anchors; print overflow is rejected explicitly. Reflow is within the containing frame; linked text across frames/pages remains future work.

Hosted acceptance passed 470 actual-app checks, 26 design/PDF checks, 54 component checks and 50 anchored-image/print checks. Local DOM suites passed 23 existing editor, 13 anchored-image and six paste-event checks; reader, geometry and toolset regressions passed 45, 40 and 51. Four-page PDF proofs were rendered and reviewed. Connected-browser file uploads require the extension's file-URL permission, and media/navigation calls timed out; the live signed-in image walkthrough and narrow-screen image-flow check remain uncompleted. No permissions were changed. No schema migration or Production deployment.

# Zine reading views and focused workspace - October 30, 2026 (Sandbox)

Reader views now offer Single page, Two-page spread and Continuous scroll. Covers stay separate and interior pages pair correctly; the reading choice is remembered in this browser. Editing gains collapsible page thumbnails, a larger central canvas and an inspector with expandable secondary controls. Saved-page comparison is optional. Hosted acceptance passed 447 actual-app and 26 design/PDF checks; local validation passed 213 component, reader, geometry, toolset and DOM checks. No schema migration. Linked text flow, publication-wide styles and master layouts remain future work.

# Advanced Zine workspace - October 30, 2026 (Sandbox)

Advanced Zine composition is deployed in Sandbox: multi-select, saved groups, alignment/distribution, rotation, opacity, named elements, crop focus, page-level artwork replacement, browser-local reusable layouts, text presets and detailed page checks. The saved-page organizer provides thumbnails, facing spreads, interior-page reordering and bulk duplication. Custom exposes selected Advanced groups. Reader and selectable-text PDFs share rotation, transparency and crop focus. Hosted acceptance: 436 application checks plus 26 design/PDF checks; local checks: 40 geometry, 51 toolset, 54 component and 19 DOM event checks. Live private-demo saving/reload, grouping, copy/paste/undo, mode preservation, Custom preferences, layout saving, four-page reordering/duplication and 390px overflow checks passed. Production source is unchanged. No schema migration; live acceptance edits were limited to the private Composition Studio Demo. Linked text flow, master pages, synchronized publication styles, advanced text wrapping, editorial review and professional print/color controls remain future work; physical print and broader accessibility/device acceptance remain open.

# Visual Zine studio - October 29, 2026 (Sandbox)

Sandbox now has Standard beginner tools, Custom with user-selected Advanced tool groups remembered per account in this browser, and Advanced with all implemented controls. A structured live canvas supports text, artwork, shapes, layers, type, resizing, exact geometry and layout JSON; saved compositions drive reader and PDF output. Existing presets remain available. Validation: 374 isolated actual-app checks, 26 design/PDF checks and 35 toolset checks; signed-in browser saved/reloaded a private demo, checked Custom choices, Advanced precision, mode-switch preservation and desktop/390px overflow. Corrected a site day/night data-mode event collision during the walkthrough. Production source unchanged. Physical print and broader device/assistive technology acceptance remain open.

# Zine authentication - October 29, 2026 (Sandbox)

Sandbox Zine authentication update - October 29, 2026: Owner confirmed activation. Zine writing uses normal login, authorization, CSRF and throttling without an extra fresh-auth challenge. Staff confirmation lasts 24 hours; account-security confirmation remains 30 minutes. Login 2FA is retained. The isolated actual-app and design/PDF suites pass. Production source and data are unchanged.

# Zine workspace - October 28, 2026 (Sandbox)

- Add focused page outline, selected-page editing and saved preview, plus separate settings, submissions and publishing views.
- Add per-page accent, body size, image width and alignment with reader/PDF parity.
- Add interior-page duplicate/remove actions with role checks and retained revision snapshots.
- Add grouped controls, artwork thumbnails, publication navigation and unsaved-change warnings.
- Pass 323 actual-app acceptance checks and 26 design/PDF checks.

# Zine directory and cover uploads - October 28, 2026 (Sandbox)

- Show three desktop columns and twelve publications per directory page, with responsive two/one-column layouts.
- Show cover artwork or a title placeholder on each directory card.
- Add owner-only upload-and-set cover control beside publication settings, including revision conflict protection.
- Pass 294 actual-app checks and 26 visual/PDF checks.

# Native Zine visual design - October 28, 2026 (Sandbox)

- Add shared Punk reader/vector-PDF styles, editable graphic metadata and deterministic waveform art.
- Preserve Classic defaults and all existing saved content; normalize browser line endings on future saves.
- Pass 26 design checks plus the existing 287 focused Zine checks.

# Collaborative Zines — October 28, 2026 (Pacific; Sandbox)

- Add independent publications, issues, owner/editor/contributor collaboration, structured pages and responsive reading.
- Add editor-controlled Letter/A4 reading-order PDFs and correctly padded saddle-stitch imposition with sheet previews.
- Preserve current account/privacy controls, CSRF/fresh authentication, revision conflicts and uploader-attributed storage/exports.
- Generate bounded PDFs on demand; keep Production rollout and advanced publishing/commerce separate.
- Technical and test documentation: docs/T34-zines.md.

# Attachment storage allowances — October 26, 2026 (Pacific)

- Deploy cumulative ordinary-media admission: 16 MiB/account, 24 MiB shared across environments, plus separate provider headroom.
- Account and freshly authorized staff storage summaries are private; own exports include only the member's usage summary.
- Reserve complete output batches, retain uncertain crash charges, preserve earlier avatars and return recoverable escaped post text on failed uploads.
- Include all current media roots, including the legacy Sandbox instance location, in verified accounting and media backup coverage.
- Pass 42 app assertions per environment, 39 independent checks, related regressions and final recovery reruns. Backups and restores verified; account/content/settings records and existing media preserved.
- Hosted audio/video and object storage remain future scope. No media pruning or automatic erasure activation.

# Pages, events and test billing — October 24, 2026 (Pacific)

- Add page discovery and search, follows and a dedicated followed-page update feed with current visibility and account restrictions.
- Creative-page owners can invite editors/managers and offer ownership transfer; recipients must accept, and revoked access stops immediately. Business transfers remain unavailable while billing ownership policy is pending.
- Add events and calendar, private Circle events, private Going/Interested responses, calendar downloads and staff report review. Current membership and access rules apply on every request.
- Stripe business billing is test-only in Sandbox at $5 USD every three calendar months. Hosted checkout, signed notifications and period-end cancellation are implemented; Production charges and business publication remain disabled pending complete payment acceptance.
- 115 disposable app checks per environment, related regressions, and migration/restore rehearsals pass. Repair the obsolete post mapping reference without deleting rows; 12 pre-existing orphan references remain for separate review.

# Creative pages — October 23, 2026 (Pacific)

- Free `_handle` page creation, drafts, publication, text updates and archiving; preserve `@handle` personal identity and separate `$handle` private business drafts. URLs are case-insensitive.
- Add private page/update reports, immutable evidence snapshots, staff permission/2FA/fresh-auth review, hide/restore decisions and review history. Retain existing account, age, consent, block and author restrictions.
- Own-data exports include pages and authored updates; future erasure refuses orphaned page dependencies. Permanent erasure remains disabled.
- 28 focused tests and 55 real-app disposable checks per environment passed. Additive migration/restore rehearsal preserves existing tables and starts seven empty page tables. No real charge, business activation, new release version or live fixture content is introduced.
- Following, wider feed/search, delegate invitations/transfer and recurring payment integration remain separate.

# Security maintenance — October 23, 2026 (Pacific)

- Pillow 13.0.0 addresses five image-processing advisories reported in both dependency manifests (GHSA-8g5g-8vmr-9782, GHSA-58r4-6rv3-gfh8, GHSA-pchr-8j38-3x4p, GHSA-65qm-jvmh-6pqg, GHSA-462x-pgg6-55fp).
- certifi 2026.10.19 removes the compromised emSign ECC Root CA - G3 chain (GHSA-6q48-6c7w-9gw2). Pin it in both manifests, verify the bad root is absent, and verify requests/urllib HTTPS using the patched bundle.
- Theme downloads use a fixed token pattern with literal source/target comparisons instead of constructing regexes from stored fields (CodeQL #28). Exact class boundaries, Day/Night isolation, Unicode/metacharacter and replacement-backreference cases are covered.
- Hosted candidates passed 78 gallery and 49 atmosphere checks per environment, Circle/recovery/network/Vibe-case regressions, 52 full-app disposable checks per environment, and 16 real image/QR checks per environment. Official wheel hashes are verified against PyPI metadata; runtime changes have offline rollback wheels and private source/database checkpoints. No user content or authentication changes are part of this maintenance.

# T19–T23 — October 23, 2026 (Pacific)

Deployed Vibe Studio unsaved Undo/Redo/Discard, style-only JSON transfer, isolated current-mode preview, inherited fonts and semantic colors; free approved-only theme gallery with explicit versioned sharing agreement, attribution-preserving independent remixes, withdrawal/review audit and own-data exports; local Day/Night logo variants, gentle motion and visitor controls, and Vibe-owned MIDI using existing default-silent playback.

Production PRs #56/#58/#60 and Sandbox PRs #57/#59/#61 merged separately. Final Production CodeQL and both language analyses pass with no new alerts after adding safe_join and retaining resolved static-boundary checks. Hosted full-app checks passed 52 per environment, all 14 legacy regression runs passed, and atmosphere validation/access/failure tests passed 49 per baseline. Edge covered editing/preview, gallery credits, unchecked sharing acceptance, phone-width forms, logo pause and MIDI Play/Stop. Device audio output is not certified by playback status.

Installed 41 reviewed files per app after fresh online database/source backups; five additive tables start empty. Rehearsed migration twice and restore against all original rows in 119 Production/124 Sandbox tables. Shared Web reload and live gallery, case-insensitive Vibe, asset and authentication checks passed. Post-install comparison found only routine active_sessions and mail_worker_health changes; account/content/theme/preference records remain unchanged. Temporary fictional browser pages were retired. Live Studio still requires owner fresh password/authenticator confirmation. No real agreement or Vibe setting was changed. T48 and earlier account/provider/device acceptance remain separate; no new release tag.

# P1 closeout — October 22, 2026 (Pacific)

T40: four owner-authorized HelpLine guidance posts prepared as ordinary public Fresh Starts content; Production publication awaits HelpLine age setup, with existing age/audience checks and no role changes. The shared guide remains available to younger members. Publication uses an audited, idempotent maintenance batch; no sessions or factors are forged.

T44 engineering: separate four-card/one-banner rotation avoids banner starvation; bounded campaign identifiers, destination checks and existing local raster validation fail closed. Staff acknowledge sponsor standards on save/activation, with audit records. Links carry sponsored/no-referrer protections, long copy wraps, and public sponsor/privacy disclosures are linked. /ads.txt authorizes the verified publisher on Production only; no third-party ad scripts are installed or activated. Google site review is still Getting ready (requested October 17); provider approval, actual sponsored inventory and delivery acceptance remain open. No paid campaign or fake sponsor was created.

# T40–T43 — October 22, 2026 (Pacific)

Signed seek pagination for Feed/Vibe/Circle timelines and profile All/authored/guestbook selectors, preserving access checks, filters and appearance. Legacy numbered URLs remain compatible and may still perform offset work. Welcome setup skips unavailable founders; canonical Vibe aliases redirect with appearance preserved. T40 onboarding and T41 distinct-author promotion are covered by focused disposable-data tests. HelpLine guidance remains an unpublished proposal in docs/T40-helpline-guidance-drafts.md. T42 specification is in docs/T42-vibe-engine.md; no location collection is enabled. Large reaction aggregation remains T48. Permanent erasure remains disabled; Afterglow remains Sandbox-only.

# T17 reading tools — October 21, 2026 (Pacific)

## October 21, 2026 — T13 and T18

Circle owner day/night palettes, safe typography/corners and protected resized covers; shared keyboard/focus, persistent feedback, reduced-motion controls and responsive/accessibility fixes. See docs/T13-T18-appearance-accessibility.md for scope, validation and limits. T26 events remain separate; Afterglow stays Sandbox-only.

Production and Sandbox: chronological feed views, a saved default, selected Vibes, private live-reference bookmarks and explicit private drafts. Current visibility applies on every view; pagination keeps the grouping. Draft revisions prevent lost updates and duplicate publishing; a successful post consumes the draft atomically. Limits: 50 drafts and 2,000 bookmarks per account. Attachments and staff-announcement status are not saved in drafts. Existing muting and notification preferences are retained. Passed 119 focused checks per environment plus applicable regression suites on disposable copies. Permanent erasure remains disabled; Afterglow remains Sandbox-only.

# October 21, 2026 — T16: following and private friend labels — Sandbox

Following now has its own opt-out and individual follower removal/allow-again controls. Re-following after voluntary unfollow works with legacy schemas. Friends and followers is an explicit post audience; Friends excludes follower-only access and existing audiences stay unchanged. Private, custom friend labels organize current accepted Friends and can target a post audience without granting Circle membership. Label names and assignments stay owner-only; removal, blocking, archiving and changing safety eligibility revoke access. Connection lists are bounded and paginated. Export, preservation discovery and future erasure cleanup include the new records. Production rollout completed separately through PR #40 after all ten Production suites and three GitHub checks passed. Existing core records were preserved. Afterglow remains Sandbox-only and permanent erasure stays disabled.

---

# Development update — October 20, 2026 (Pacific)

The public development log is available at /dev (Production) and /sandbox/dev (Sandbox). Environment labels distinguish deployed features.

## Database and upload recovery · Production and Sandbox

Prolonged SQLite BUSY/LOCKED failures now return HTTP 503 with retry guidance; SQLite FULL and filesystem no-space/quota failures return HTTP 507. Uncommitted work rolls back. Upload validation preserves the real storage error, removes only newly allocated partial files and keeps existing images. Comment and reaction controls show the server message, preserve comment drafts and never automatically repeat a write. Storage exhaustion still requires space to be restored.

## Stress testing and remaining growth work

Disposable database copies exercised concurrent writes, prolonged locks, database page-limit exhaustion, invalid and oversized images, large reaction tables and deep timeline pages. Each app passed 47 resource-recovery checks, and 12 JavaScript recovery checks passed; privacy, sharing, Circle, statistics, security, pagination, video and deletion-navigation regression suites also passed. Active databases were never deliberately locked or filled. Large reaction aggregates and deep offset pagination remain performance work; these checks do not establish unlimited hosting capacity.

## Bounded timelines and comment navigation · Production

Feed, Vibe and Circle timelines use a bounded page window and lookahead rather than counting an entire matching history on each request. Timeline previews bound comment loading; individual post pages use comment windows with navigation. Public comment links and older numeric comment targets resolve to the correct window. Navigation controls remain readable in inherited themes.

## Profile pages and deletion return · Production

Profiles load 20 posts per page with signed cursor navigation rather than fetching an entire post history. Post deletion returns to a validated same-site profile or timeline destination, preserving profile context instead of always sending the author to Feed.

## Linked video players · Production

YouTube links support an explicitly loaded inline player with a close control and styled external link. Facebook and Instagram links have supported provider embeds or external-link fallbacks subject to provider availability and privacy restrictions. Third-party players load only after the visitor chooses to load them; protected post access remains checked.

## Storage housekeeping and public artwork

Removed completed statistics-test fixtures and verified redundant release assets in the earlier cleanup; retained audit records and rollback sources. Production uses smaller public artwork and content-versioned asset URLs. Recent tests use disposable copies and managed temporary directories. No user posts, accounts or uploads were removed by this maintenance.

## Source and rollout status

Production and Sandbox retain separate source checkpoints. Afterglow is Sandbox-only and paused for rollout. Runtime configuration, credentials, databases, private records and uploaded user media are excluded from source exports. The resource-recovery fix is merged in PR #37; documentation sync does not declare a new release tag. See earlier RELEASE-NOTES documents for v0.8.0 and v0.8.1.

---

# Changelog

## [0.4.2] – 2025-04-21
### Added
- Support for guestbook-style posts on user profiles
- Author attribution block including avatar, handle, codename, and timestamp
- Visual styling for guestbook posts authored *to others* when shown on your own profile

### Fixed
- Posts previously excluded or misattributed due to missing `target_user_id` logic are now visible
- Markdown content rendering restored on `/user_test/<id>` view
- Top 9 Friends sorting and drag-and-drop saving now working reliably via Sortable.js

### UI / Styling
- Posts authored to other users now show with `.guestbook-outbound` styling (subtle highlight and indentation)
- Top 9 grid supports placeholder states and empty slots for drag assignment
# Changelog
