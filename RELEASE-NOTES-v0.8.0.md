# Neonrest v0.8.0

Released October 15, 2026 (Pacific), for Production and Sandbox.

This milestone consolidates account security, moderation, privacy and family-request workflows, with the final navigation and presentation updates.

- Account security: verified email changes and recovery safeguards, authenticator setup/replacement, one-use recovery codes, session controls and clearer confirmation errors. Authenticated visits to the login page now land on the account profile; inactive and restricted-account gates remain enforced.
- Moderation and privacy: case evidence, request deadlines and delivered-response records, appeals, preservation holds, final case dispositions, reviewed family exports, staff guides and private verification-document invitations.
- Operations: documented document/backup retention targets, restore preflight, deployment review and rollback rehearsal, with distinct Production/Sandbox mail and session boundaries.
- Presentation: consistent Account-style frames, grouped navigation with active states, mobile collapse/wrapping, Feed/Profile shortcuts in the top account bar and readable post-content links.

Owner acceptance includes Production login, Vibe-management 2FA, Production privacy staff pages, the Sandbox privacy walkthrough, authenticator replacement, successful login with the new factor, recovery-code acceptance once and rejection on reuse, the corrected login landing and final styling. The owner confirmed deletion of the retired MailerSend SMTP user and an empty API-token list. Both application sources reference Purelymail; historical provider-log coverage remains limited and this release does not certify that no prior misuse occurred.

Permanent account erasure and combined automatic retention remain disabled. Document removal and backup rotation are staff-managed. Preserved-case decisions, legacy/provider-copy review and reconciliation of the documented untrusted older snapshot remain prerequisites to enabling future erasure.

The annotated v0.8.0 tag preserves the git@github.com:sinbot777/neonrest.gital two-environment release snapshot. Main presents its Production package at the repository root; Sandbox source is maintained separately. Known live credentials and private runtime data are excluded. This is a source release, not a complete operational backup.
