# October 21, 2026 — T16: following and private friend labels — Sandbox

Following now has its own opt-out and individual follower removal/allow-again controls. Re-following after voluntary unfollow works with legacy schemas. Friends and followers is an explicit post audience; Friends excludes follower-only access and existing audiences stay unchanged. Private, custom friend labels organize current accepted Friends and can target a post audience without granting Circle membership. Label names and assignments stay owner-only; removal, blocking, archiving and changing safety eligibility revoke access. Connection lists are bounded and paginated. Export, preservation discovery and future erasure cleanup include the new records. Production rollout is separate; Afterglow remains Sandbox-only and permanent erasure stays disabled.

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
