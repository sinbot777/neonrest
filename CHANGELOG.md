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
