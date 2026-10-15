# Privacy workflows: Sandbox implementation

Sandbox source and additive schema installed 2026-10-15 UTC. Web-worker reload verified: unauthenticated privacy management returns 403 with revision 2026-10-14.6. Production source is unchanged. Permanent retention is disabled in both configurations.

## Staff workflow
Open /sandbox/manage/privacy after recent authentication as staff with manage_roles permission. Record requests received by email without requiring the requester to create an account. Preserve the original receipt time; assign a reviewer and track the 45-day response date. Record an extension only after its notice has actually been delivered. Recording a response does not send email. Record responses, appeals and independent review.

At /sandbox/manage/family/requests, separately verify identity, authority and legal disclosure basis. Examples may include relevant portions of birth/adoption records, custody orders or guardianship appointments; an identity document alone does not prove parental authority. Accept redaction of unrelated information. Do not collect credentials or request documents by ordinary email. Staff review and redact the exact export JSON before approval. Downloads expire after 24 hours and fail closed after authority changes. Exports exclude authentication material, private messages, internal moderation notes and raw identity documents. A separate reviewed legal basis is required for disclosures outside that scope.

## Preservation
Deletion requests still hide accounts. Unresolved moderation involvement and manual holds block permanent erasure, including shared records whose removal would affect another held account. Closed cases need an explicit final preservation disposition after outstanding linked reports and appeals are resolved. Reopening a case invalidates the disposition. Holds require a reason, reviewer and review date; passing the review date does not silently release a hold. Reviewed evidence-document cleanup must be scheduled explicitly and respects holds.

## Verification and remaining work
23 isolated privacy tests, 17 full-app integration checks and 41 existing retention compatibility checks passed. Existing QR (40), authenticator replacement (61) and recovery-form-origin (62) checks also passed against the candidate. Fixtures use disposable databases and mocked mail; real factors were not changed.

Owner confirmed Production Vibe-management 2FA acceptance. Broader owner acceptance remains open. Before Production rollout: owner-review the Sandbox UI, review policies and operational evidence retention/backup practices, agree document-retention schedules, and rehearse the staff process. No automatic outbound responses or automatic deadline notifications are implemented. These controls support the policy; they do not constitute a legal compliance certification.
