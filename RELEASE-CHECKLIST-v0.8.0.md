# Neonrest v0.8.0 final release reconciliation

Updated October 15, 2026 (Pacific). This supersedes the October 14 checkpoint and historical pending-owner notes in the privacy readiness documents.

**Status: release prepared; final sign-off, displayed-version change and v0.8.0 tag are blocked by the two owner items below.**

## Completed

- [x] Actual deployed source baseline and subsequent source-only checkpoints preserved on `sandbox-baseline-2026-10-13`; unrelated history and main preserved.
- [x] Five real email deliveries reviewed with SPF, DKIM and DMARC passing; verification, reset and email-change invalidation checks recorded.
- [x] Diagnostic fixture cleanup verified with 11 read-only checks.
- [x] Specific Production password/factor confirmation messages deployed; owner confirmed login and Vibe-management 2FA.
- [x] Automated QR, authenticator replacement, recovery, replay and session-security checks passed in isolated application copies. This does not substitute for the owner browser walkthrough below.
- [x] Preservation and guardian-request policy decisions implemented with reviewed exports, appeals, holds, case dispositions and staff instructions.
- [x] Fictional Sandbox walkthroughs completed: reviewed export, appeal denial, hold retain/release and private document submission/review/closure.
- [x] Private document submission and document/backup retention rules implemented and documented. Actual removal and rotation remain staff-managed.
- [x] Storage cleanup completed after owner-verified local archive download.
- [x] Production candidate review and rollback rehearsal completed; deployment preserved existing records and separate cookie scopes.
- [x] Owner confirmed Production Privacy requests, Private verification documents and Family request review open after reauthorization.
- [x] Account/Management frame, navigation, top-bar shortcuts and post-link styling deployed to both environments and accepted by owner.
- [x] October 15 source audit compared 301 tracked deployed files against the source checkpoint. Runtime presentation/application files match, except the two documented sanitized Last.fm exports. One older deployed test differs and six repository-only regression files are test assets, not runtime discrepancies.
- [x] Application source in both environments references `smtp.purelymail.com`; mail supervisor heartbeat is fresh. This establishes current configuration, not old-provider revocation.
- [x] Known live credentials and private data are excluded from publication; the complete resulting Git tree is scanned before every push.

## Two owner items required before final sign-off

- [ ] Confirm that the MailerSend API tokens and SMTP users implicated in the credential incident have been revoked. Moving delivery to Purelymail does not itself revoke credentials at MailerSend. Limited earlier access-log review is recorded; provider-side incident review/revocation remains unconfirmed. Record the action/date and provider-log coverage without any credential values. Do not claim that no misuse occurred when logs are unavailable.
- [ ] Complete the actual Production owner browser acceptance for authenticator replacement and recovery-code use/reuse rejection. Keep credentials and recovery codes out of chat and release records. Record only the outcome and date; automated fixture coverage is already complete.

## Finalization once both owner items close

- [ ] Update both deployed base-template footers from 0.7.4e to 0.8.0, finalize release notes and current dev-log status, and reload the PythonAnywhere web app.
- [ ] Verify the displayed version in Production and Sandbox, current route/asset health and disabled erasure configuration.
- [ ] Create a source-only final commit on the existing audited branch, preserving the two-environment repository layout. Scan the entire resulting tree for credentials and private artifacts, push and verify its remote object ID.
- [ ] Create and push a new annotated `v0.8.0` tag at that verified commit; fail rather than overwrite any existing tag. Main remains unchanged.

## Deliberate release limitations

Permanent account erasure and combined automatic retention remain disabled. Preservation/appeal blockers remain enforceable. Staff-managed removal/backup rotation, documented preserved-case decisions, review of legacy/provider copies and reconciliation of the untrusted older snapshot are prerequisites to any future erasure activation, not claims completed by this release. The runtime Last.fm key remains local and is excluded from sanitized Git source; the tag must not be described as an environment-complete or credential-bearing backup.
