# Sandbox retention and deletion

Implemented October 11, 2026. Automatic erasure is disabled until the owner approves the concrete preview.

## Operation

Preview: python /home/sinbot/neonrest_sandbox/retention.py

After approval, set RETENTION_ENABLED to True in app.py, reload the web app, and configure a daily PythonAnywhere scheduled task:

python /home/sinbot/neonrest_sandbox/retention.py --apply

The worker exits without erasure when activation is disabled. Preview is also shown in Site operations. Each applied run stores counts and numeric account IDs for 90 days. File removals are queued transactionally and retried until completed. Inspect file_errors and retention_file_queue after every failed run. Jobs must finish successfully before claiming a deletion completed.

## Periods

| Data | Rule |
| --- | --- |
| Requested account deletion | 30-day cancellation period; account is hidden immediately |
| Unverified registrations and pending friend requests | 30 days from recorded creation |
| Verification/reset tokens | 7 days after expiry |
| Sessions | 7 days after expiry, or revocation with last activity older than 7 days |
| Rate-limit counters | 1 day after last activity; old undated counters start at migration time |
| Operations events | 30 days |
| Abuse events and notifications | 90 days |
| Authorization form drafts | 1 day |
| Unreferenced avatar/media files | 30 days since modification |
| Unapproved consent documents | 30 days from submission |
| Approved consent documents | While documenting the approved relationship; removed with linked account erasure |
| Site operations backups | 30 days from file modification |
| Closed moderation cases | Review due after 365 days; protected evidence is NOT automatically purged |

## Scope and limits

Production is excluded. Managed backups are only neonrest-*.db files in the database's sandbox_backups folder. Legacy archives and hosting logs/backups require separate inventory and approval; do not promise a 30-day period for them. Undated registrations are not automatically removed. Administrator ID 1, accounts with staff_roles, and explicitly reserved helper accounts require manual deletion review.

Erasure removes profile/authentication rows, connections, owned and wall-targeted posts, replies, thread comments, post edit history, reactions, private settings, family links/contact permissions/consent documents, and owned uploaded files. Other users' surviving replies have erased parent references cleared. Shared upload files are retained while referenced. Shared themes can remain with creator linkage removed. Restricted reports, appeals, action records and case evidence remain for a documented safety/legal review. No fixed automatic purge for those records is claimed.

Before restoring an archive, reconcile account deletion requests and completed erasures from retention_runs in the current database, and apply them to the restored copy before making it accessible. Restoration is manual; the backup cleanup schedule is not a restore safeguard.

## Verification

python /home/sinbot/neonrest_sandbox/tests/verify_retention.py
python /home/sinbot/neonrest_sandbox/tests/verify_family_consent.py

Both suites use isolated databases. The retention suite uses temporary storage roots and never removes live uploads.

Staff disable flags are separate from bans, personal deactivation and pending deletion. Enabled disable flags block sign-in, revoke sessions, hide content from ordinary viewers and hold automated erasure for review. Restoration clears only this flag; prior sessions stay revoked. Staff actions require restrict_users permission, a reason, CSRF and current authorization, and are logged as account-disable/account-restore. Protected staff and owner accounts cannot be changed through this control.
