# Resource failure recovery

SQLite BUSY and LOCKED errors return HTTP 503 with a Retry-After hint. SQLite FULL and filesystem ENOSPC/EDQUOT return HTTP 507. Existing SQLite wait limits remain unchanged. Known resource failures roll back uncommitted primary-database work and render without database-backed templates, notifications, flash messages, or database error-event writes. Responses are private/no-store and do not expose exception text or internal paths. Unrelated database and filesystem errors retain the existing error path.

Comment/reaction requests receive structured JSON. Their controls show the server message, preserve drafts, and never silently resubmit a write. HTML responses tell users to keep their text and check whether a change appeared before retrying, because an error can occur after a commit. A full storage device still needs space restored; this change does not automatically remove user data or claim that writes can succeed without storage.

Post-image, avatar, legacy-image, and Circle-icon code propagates storage failures instead of calling them invalid images. Failed image generation removes only newly allocated files, preserving existing uploads. Existing avatars are kept when temporary-file serialization fails. Invalid/oversized image validation and all permission checks remain unchanged. No schema, journal-mode, authentication, or Afterglow changes are required.

Validation: tests/verify_resource_recovery.py PACKAGE STAGE uses disposable copied databases, real short/prolonged SQLite locks, real page-quota exhaustion, filesystem quota/no-space injection, upload partial-file cleanup, rollback/recovery, and unrelated-error classification. It forbids SMTP. tests/verify_resource_clients.js STAGE checks error messages, draft preservation and absence of automatic retries using Node's built-in assertion/VM modules; no browser or network is used. Full permission, navigation, pagination, video, statistics, Circle and sharing suites should also pass.

Rollback restores source files only. Do not rewind databases or uploaded content. Actual failure testing must stay in disposable fixtures rather than locking or filling the active databases.
