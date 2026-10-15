# Neonrest v0.8.0 final release reconciliation

Updated October 15, 2026 (Pacific). This supersedes the October 14 checkpoint and historical pending-owner notes in the privacy readiness documents.

**Status: owner acceptance complete; final source release v0.8.0.**

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

## Final owner acceptance

- [x] Owner reports MailerSend API-token list empty and confirms deletion of the retired SMTP user after initially pausing it. Neonrest uses Purelymail. Earlier access-log review had limited coverage; no claim of complete historical incident visibility or absence of misuse is made.
- [x] Production authenticator replacement enabled successfully; owner logged in with the new factor.
- [x] Owner used a new recovery code successfully once and confirmed that reuse was rejected.
- [x] Owner confirmed the corrected login-page redirect to the profile.

## Final release artifacts

Production and Sandbox display Version 0.8.0. Final release notes and owner outcomes are recorded without credentials. The final source commit is credential-scanned and published on the existing audited branch, preserving its two-environment layout and main. A new annotated `v0.8.0` tag identifies that verified commit; existing tags must never be overwritten. Live verification and remote commit/tag read-back are required before reporting publication complete.

## Deliberate release limitations

Permanent account erasure and combined automatic retention remain disabled. Preservation/appeal blockers remain enforceable. Staff-managed removal/backup rotation, documented preserved-case decisions, review of legacy/provider copies and reconciliation of the untrusted older snapshot are prerequisites to any future erasure activation, not claims completed by this release. The runtime Last.fm key remains local and is excluded from sanitized Git source; the tag must not be described as an environment-complete or credential-bearing backup.
