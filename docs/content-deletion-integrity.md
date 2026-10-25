# Content deletion and legacy reference repair

## Runtime deletion

Post and comment removal retains the existing authenticated owner, public-ID and CSRF checks. The database transaction takes an immediate write lock and rechecks ownership before changing records. A failure rolls back the entire operation.

Deleting an ordinary comment keeps other authors' replies. Direct replies move to the nearest surviving direct ancestor in the same post, or become top-level replies when no valid ancestor remains. Their content and public IDs remain unchanged. Cross-post links require staff review. A moderated, protected-age or Circle-removed parent with replies cannot be removed in a way that would promote replies out of that restriction.

Deleting a post removes its thread and live metadata, including reactions, Vibe mappings, bookmarks, media references and Circle pins. Other authors' share wrappers remain and use the existing unavailable-source presentation. No media bytes are unlinked by this operation. Immutable moderation evidence, reports, case history and audit records remain. Current preservation holds and unresolved cases block removal. Automatic account erasure remains disabled.

## Reviewed legacy orphan archive

The operations-only archive function accepts an explicit reviewed set, refuses valid comments and unreviewed dependent replies, and rechecks preservation requirements. Within the caller's transaction, it stores complete original rows, hashes, ID/alias records and the original Vibe-mapping row ID in `reference_repair_archive` before active cleanup. There is no public archive endpoint. Archives and backups contain private data and must remain restricted; never commit their contents to GitHub.

The October 25 Production rehearsal covers eleven old test comments and one missing-post Vibe mapping: twelve foreign-key violations and forty-five archived records including identifier metadata. A disposable online database copy reaches zero violations without modifying surviving comments or unrelated table counts. Replaying the archived original rows reproduces the original comments, counts and all twelve original reference violations, demonstrating restoration fidelity. Sandbox requires no legacy cleanup.

Before applying, take a fresh private online backup, verify its integrity, acquire an immediate write lock, and compare the exact reviewed violation set again. Apply only that set, require zero remaining violations and a passing integrity check before commit, and retain the backup and private operation report. Restoration is a reviewed maintenance operation: use transactional inserts that refuse collisions; do not overwrite newer live data with an older database wholesale.

Validation includes real routes in disposable Production/Sandbox copies with foreign-key enforcement on and off, ownership/CSRF checks, reply preservation, held and moderated threads, rollback after an induced failure, dependent cleanup, preserved shares/case evidence, and archive/restoration rehearsal. Source and data rollout outcomes are recorded in the associated PRs and private operational checkpoint.
