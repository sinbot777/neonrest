# Privacy deployment review and rollback rehearsal

Reviewed October 14, 2026 (Pacific). This is a candidate and an isolated rehearsal, not a Production deployment or final v0.8.0 acceptance.

## Reviewed scope

The candidate starts from actual deployed Production source. Runtime changes are limited to `app.py`, `family_data.py`, `retention.py`, new `privacy_workflows.py` and `privacy_submissions.py`, and the privacy/family templates listed in its source manifest. The app change updates new-signup privacy acknowledgement to `2026-10-14-production`; Terms remains `2026-10-13-production`. Existing acknowledgement records are preserved. Existing authentication, mail-worker and cookie configuration are retained.

Review found and corrected the copied retention defaults: consent uses `neonrest_production/family_consent`, and managed backups use `production_backups`. Separate environment tests cover retention and private-document roots. The authenticator replacement suite expected an obsolete generic error; its candidate assertion now checks the current rejection message and verifies authorization timestamps and pending replacement state remain unchanged on rejection. Authentication implementation was not modified.

Permanent account erasure and the combined retention job remain disabled. No role grants, real account factors, preservation decisions, mail settings or live Production source/database were changed by the review.

## Verification

- 43 privacy regression tests.
- 17 baseline full-application privacy checks and 24 intake/notice/signup/offline-restore checks.
- 2 Production storage-isolation tests.
- 40 authenticator QR checks, 63 replacement checks, and 62 recovery/email-form checks. These suites overlap in their setup scenarios; do not present their sum as unique coverage.
- 26 rollback checks, including opening the migrated database with older source, retaining post-migration activity and a newer preservation hold, invalidating copied grants/sessions/invitations, and rejecting GET/POST access to paused tools.
- Original inspected live Production source hashes remained unchanged through the drill.

Application test writes use separate database copies. Mail is disabled or mocked; no real factor is enrolled or replaced. Rollback sanitation intentionally changes only its offline copy. The independent invitation receipt ledger used in the drill is also isolated.

A fresh private Production database checkpoint was captured with SQLite backup, integrity-checked and fingerprinted. A private media inventory records uploaded files without copying or changing them. This checkpoint and inventory are excluded from source control. They are not an unconditional authorization to restore old data. Verify a fresh checkpoint again at deployment time; preserve a separately secured current document key and receipt ledger once Production has documents.

## Controlled deployment procedure

1. Recheck candidate runtime hashes and deployed baseline hashes against the private manifests. Stop on unexpected drift. Recheck Production's root cookies, secure-cookie settings, database, private instance/media, consent, submission/key/receipt and backup paths. Sandbox paths must not be substituted. Do not replace WSGI, worker or authentication configuration with Sandbox copies.
2. Capture and verify a current private database rollback checkpoint and original versions of every existing runtime file to be replaced. Keep current media, keys and ledgers. File fingerprints alone are not a media backup. Review any new activity since the previous rehearsal.
3. Pause incoming writes for the short file/migration window; coordinate the Production mail worker using its existing supervisor/lock procedure. Do not accept requests while only part of the source set is installed. Do not overwrite a current database with a fixture or rehearsal copy.
4. Install only the reviewed runtime allowlist and run the additive migration against the Production database under the maintenance window. Check integrity and preservation of existing records. Keep automatic erasure/combined retention disabled. Do not change account roles or verification status as part of deployment.
5. Reload the Production app and perform public route/header, cookie and environment-isolation checks. Staff must check actual recent-authenticated access, invitation/upload/review, reviewed export scope and stale/foreign/revoked access. Check Sandbox isolation separately. No real identity documents are needed for acceptance.
6. Resume traffic and the existing worker only after the checks pass. Record the installed hashes, time, rollback point and post-deployment results. Production deployment and owner acceptance remain separate from this completed rehearsal.

## Preferred rollback: older source, current database and files

Do not blindly restore the pre-deployment database after new activity. The drill proved that older source can open the migrated database while newer records and holds remain present. Additive privacy tables may remain; do not drop them to make the schema look old.

Older family export code lacks the new reviewed-snapshot safeguards. A bare source rollback is therefore insufficient. During a reviewed rollback:

1. Pause writes and coordinate the Production worker. Keep the upgraded privacy implementation available while invalidating privacy/export/upload grants and copied sessions/recovery tokens using the reviewed sanitation logic. The rehearsal uses `restore_preflight` on an offline copy; its CLI rejects the configured live database. An actual rollout rollback needs a maintenance-controlled copy/reconciliation procedure, not a bypass of that CLI guard.
2. Preserve current holds, final decisions, user activity, raw-file removal decisions, document keys and independent invitation receipts. Reconcile all activity made while the maintenance copy was prepared. Keep current files; never restore removed documents or an older receipt ledger. Use the mail system's existing restore/invalidation procedure whenever restoring a database; retain its independent delivery ledger and keys.
3. Before older source serves requests, attach `PrivacyRollbackGuard` to the **Production child app**. Keep it in a trusted source location outside the files being replaced, and preserve the currently published privacy notice. The guard pauses privacy/family request tools, private submission and signup. Signup stays paused so older code cannot record an outdated privacy acknowledgement against the current notice.

```python
from privacy_rollback_guard import PrivacyRollbackGuard
production_app.wsgi_app = PrivacyRollbackGuard(production_app.wsgi_app)
```

This is an explicit maintenance wrapper, not a default startup setting. Do not wrap the shared Sandbox dispatcher by accident. It returns uncached 503 responses before older routes run; normal sign-in and the current privacy notice remain available. The guard itself does not revoke grants, stop workers, reconcile decisions or restore data.

4. Restore the original existing source files from the reviewed allowlist. Leave unused new modules inert rather than deleting records/files. Retain the current notice and guard. Confirm erasure is still disabled, paused routes return 503 for both GET and POST, normal sign-in works, current data/holds remain, and no outstanding grant can disclose data.
5. Keep privacy tools/signup paused until a forward repair restores reviewed disclosure controls and current policy acknowledgement. Do not remove the guard merely because older code starts successfully. Reopen only after separate acceptance.

The rehearsal does not establish a zero-downtime rollback, mail-worker operational rollback, arbitrary database disaster recovery or complete media restore. Those broader actions retain their own reconciliation requirements. Preserved-case dispositions and legacy/provider/operator backup copies still need review before any later erasure activation.
