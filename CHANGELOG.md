# P1 closeout — October 22, 2026 (Pacific)

T40: four owner-authorized HelpLine guidance posts prepared as ordinary public Fresh Starts content; Production publication awaits HelpLine age setup, with existing age/audience checks and no role changes. The shared guide remains available to younger members. Publication uses an audited, idempotent maintenance batch; no sessions or factors are forged.

T44 engineering: separate four-card/one-banner rotation avoids banner starvation; bounded campaign identifiers, destination checks and existing local raster validation fail closed. Staff acknowledge sponsor standards on save/activation, with audit records. Links carry sponsored/no-referrer protections, long copy wraps, and public sponsor/privacy disclosures are linked. /ads.txt authorizes the verified publisher on Production only; no third-party ad scripts are installed or activated. Google site review is still Getting ready (requested October 17); provider approval, actual sponsored inventory and delivery acceptance remain open. No paid campaign or fake sponsor was created.

# T40–T43 — October 22, 2026 (Pacific)

Signed seek pagination for Feed/Vibe/Circle timelines and profile All/authored/guestbook selectors, preserving access checks, filters and appearance. Legacy numbered URLs remain compatible and may still perform offset work. Welcome setup skips unavailable founders; canonical Vibe aliases redirect with appearance preserved. T40 onboarding and T41 distinct-author promotion are covered by focused disposable-data tests. HelpLine guidance remains an unpublished proposal in docs/T40-helpline-guidance-drafts.md. T42 specification is in docs/T42-vibe-engine.md; no location collection is enabled. Large reaction aggregation remains T48. Permanent erasure remains disabled; Afterglow remains Sandbox-only.

# T17 reading tools — October 21, 2026 (Pacific)

## October 21, 2026 — T13 and T18

Circle owner day/night palettes, safe typography/corners and protected resized covers; shared keyboard/focus, persistent feedback, reduced-motion controls and responsive/accessibility fixes. See docs/T13-T18-appearance-accessibility.md for scope, validation and limits. T26 events remain separate; Afterglow stays Sandbox-only.

Production and Sandbox: chronological feed views, a saved default, selected Vibes, private live-reference bookmarks and explicit private drafts. Current visibility applies on every view; pagination keeps the grouping. Draft revisions prevent lost updates and duplicate publishing; a successful post consumes the draft atomically. Limits: 50 drafts and 2,000 bookmarks per account. Attachments and staff-announcement status are not saved in drafts. Existing muting and notification preferences are retained. Passed 119 focused checks per environment plus applicable regression suites on disposable copies. Permanent erasure remains disabled; Afterglow remains Sandbox-only.

# T16 following and private friend labels — October 21, 2026 (Pacific)

Production and Sandbox: optional one-way following, incoming-follower controls, explicit Friends and followers posts, private labels for accepted Friends, label post audiences and bounded connection lists. Existing post audiences retain their rules; migration does not rewrite existing records. Current safety checks, CSRF and account restrictions apply. Archived labels fail closed; blocking and unfriending clear assignments. Permanent erasure remains disabled.

Validation: 91 focused Production fixture checks and the recovery, privacy, Circle, sharing, network security, statistics, pagination, video and deletion-return suites on separate database copies. Afterglow remains Sandbox-only.

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
