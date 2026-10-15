## Production candidate rehearsal completed

An isolated candidate built from the actual Production source passed 43 privacy regressions, 17 baseline full-application checks and 24 intake/notice/signup/restore checks. Original copied records were preserved. Source is saved separately on privacy-production-candidate-2026-10-15 at 74d1d4b7bcea0b40346168a21a88b4d46d3c244d. It has not been deployed. Review environment settings, current rollback coverage and affected permission/security regressions before deployment; do post-deployment owner acceptance separately. Account erasure remains disabled. The older snapshot mismatch and preserved-case/legacy-copy review remain recorded in PRIVACY-RETENTION-READINESS.md.

## Owner acceptance and retention inventory follow-up — October 14, 2026

The private document walkthrough is complete, including successful request closure and the expected 30-day eligibility date. Actual removal was not performed. See PRIVACY-RETENTION-READINESS.md for verified backup metadata, the untrusted older snapshot and preserved case/disposition inventory. Production rollout preparation can proceed with erasure disabled; preserved-case decisions and legacy/provider copy review remain prerequisites to any later erasure activation.

## Current Sandbox status: private documents and retention (2026-10-14.7)

This update supersedes earlier statements below that unlinked document submission or a document/backup schedule is still unimplemented. Staff can now issue one-file, 24-hour private invitations without a requester account. Documents are encrypted outside public files, with staff-only fresh-authenticated downloads and separate identity/authority decisions. Uploads never grant export or guardian access.

Operating targets are 30 days for reviewed documents after final request/appeal resolution, 90 days for request records after final resolution, and 30 days for managed rolling backups. Preservation blockers and later related hold releases prevent or extend disposal. Document removal is staff-confirmed; managed backup rotation is an operator task. The combined retention job and permanent account erasure remain disabled. These periods are operating choices, not statutory minimums. Legacy consent evidence, provider copies and old downloaded archives need their own review.

See PRIVACY-DOCUMENT-RETENTION.md and the in-app Privacy and Family guides for the full process, minimal collection, key recovery, weekly review and offline restore. Restore preflight invalidates restored invitations, grants, sessions and email tokens on an explicitly selected offline copy; human reconciliation of later preservation/deletion decisions and private files remains required.

Verification: 43 privacy tests, 23 actual-application intake/notice/signup checks, 17 baseline application privacy checks, and 41 retention compatibility checks passed using disposable data with SMTP disabled. Production source is unchanged. This closes implementation of these two Sandbox prerequisites, not Production rollout or final v0.8.0 acceptance.

---

# Privacy workflow release readiness

Status: Sandbox implementation and walkthrough completed; Production source unchanged. This is not the final v0.8.0 release sign-off.

## Completed

- Owner walked through requesting more verification, reviewing/redacting the exact export, and approving it.
- Owner verified that a hidden deletion-requested account was preserved, reviewed/retained the hold, and released it after a fictional final decision.
- Owner recorded a fictional appeal and denial, including reviewer explanation and simulated notice delivery.
- Queue displays appeal outcomes, decision explanations, reviewer, recording date and original deadline; pending appeals show response deadlines and overdue status.
- Both staff screens link to field-by-field guides with AI drafting prompts.
- Duplicate complaint instructions are no longer appended when the standard complaint URL is already present. The delivery attestation remains required.
- 25 isolated privacy regressions passed, including missing/provided complaint notices and delivery attestation. The 17-check full-app integration suite passed again.
- 10 requester acceptance checks passed using a disposable copy of current Sandbox data: requester-visible decisions, approved/redacted download, cache restrictions, exclusion of authentication fields, frozen content, account ownership, freshness, changed authority and expiry. No real credentials or factors were changed.
- Two practice requests closed; practice export grant revoked, deletion cancelled and simulated link revoked. Three fictional accounts remain hidden with sign-in disabled. Audit history and private pre-closure evidence retained. One duplicated notice in the fictional response was corrected; no real response was rewritten.

## Verification documents: current controls

Existing linked-guardian uploads require an adult account, a pending/approved family link, CSRF and recent authentication. Uploads are bounded to 5 MiB and accepted PDF/PNG/JPEG formats; images are decoded and re-encoded. Files are stored outside public static directories with restricted file permissions. Downloads require the submitter or authorized staff, recent authentication, attachment delivery and private cache/security headers. The deployed source matches the inspected module. These technical controls do not themselves establish identity or authority.

## Outstanding before Production handoff

1. Establish a secure submission method for requesters without linked accounts. Assisted email intake records requests but is not an identity-document upload channel; ordinary email must not be presented as one.
2. Adopt the verification-document retention schedule and staff recordkeeping procedure. The 1-365-day scheduling control is not a policy decision or a legal retention rule. Retention and preservation must also cover backup copies and restored data.
3. Review moderation evidence snapshots and backup/restore handling before enabling permanent erasure. Keep erasure disabled in the meantime.
4. Complete a Production deployment and environment-specific smoke check only after the operating decisions are settled; record the remaining overall v0.8.0 acceptance separately.

No new automatic outbound responses, deadline notifications, under-13 onboarding, or permanent erasure were enabled.
