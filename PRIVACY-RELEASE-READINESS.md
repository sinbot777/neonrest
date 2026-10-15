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
