# Neonrest v0.8.0 — draft pending final sign-off

This release consolidates the account-security, moderation, privacy and family-request work, together with the final account-navigation and post-link styling updates.

- Account security: email verification/change/recovery safeguards; authenticator setup and replacement; recovery-code and session controls; clearer confirmation errors.
- Moderation and privacy: reviewed family exports, request deadlines and delivered-response records, appeals, preservation holds, final case dispositions, staff guides and private verification-document invitations.
- Operations: documented document/backup retention targets, restore preflight, deployment review and rollback rehearsal, and separate Production/Sandbox mail and session boundaries.
- Presentation: consistent Account-style frames, grouped navigation with active states, mobile collapse/wrapping, Feed/Profile shortcuts in the shared top bar, and readable post-content links.

The owner has accepted Production login, Vibe-management 2FA, the Production privacy staff pages, the Sandbox privacy walkthrough and the final styling. The separate owner recovery/replacement walkthrough and old MailerSend credential revocation are not yet confirmed. The release tag and displayed-version change have therefore not been issued.

Permanent erasure remains disabled. Document removal and backup rotation are staff-managed; preserved-case and legacy-copy review remain prerequisites to enabling future erasure. Private databases, uploads, keys, credentials and test receipts are excluded from the Git release. These source snapshots are not complete operational backups.
