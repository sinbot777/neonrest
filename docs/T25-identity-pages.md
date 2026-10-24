# T25 identity pages — first implementation increment

Status: draft foundation; not registered or deployed. T25 remains incomplete.

## Confirmed product rules

- Personal signup creates an `@handle` account; pages belong to a registered personal account and never gain login credentials.
- Creative `_handle` pages are free. All eligible existing members may own them, including children whose existing parental approval remains valid. This does not reopen under-13 signup.
- Business `$handle` pages require adult ownership (18+) and a recurring subscription. The owner selected this model on October 23, 2026 Pacific. Approved launch terms: $5 USD per business page every three calendar months, no setup fee; cancellation stops renewal and preserves access through the paid period. Creative pages stay free; advertising placements are separate. The payment provider is not yet selected.
- Each prefix has its own case-insensitive namespace. Canonical page URLs are `/_handle` and `/$handle`, or their `/sandbox` equivalents. No existing personal handle is renamed.

## Implemented in this draft

Additive page, delegate and action tables; opaque page IDs; lowercase handle validation; private draft creation; plain escaped name/description editing; creative publish/archive/restore; owner-only visibility control; revision conflicts; fresh-auth/CSRF gates; responsive templates and prefix-aware routes. Caller transactions serialize creation and preserve rollback. Archived handles stay reserved. Initial resource bounds: 20 owned pages, 20 delegates per page, 80 name characters, 4,000 description characters.

Owner eligibility checks verified personal identity, current age/parental readiness, deactivation, account disabling and posting restrictions. Page delegation requires current contact permission; blocks, revoked consent and account restrictions are checked again at use. Creative page readers retain owner-based age/block rules. Business publishing is rejected server-side even if submitted form fields claim payment succeeded. Business drafts incur no charge. No checkout, subscriptions, payment webhook or charges exist in this increment.

A page-scoped export function includes only owned pages, the account's delegations and its own actions. It still needs wiring into account export and preservation/retention discovery. No current account/post rows are rewritten.

## Validation boundaries

Fourteen offline SQLite policy/state tests and nine additional isolated Flask route/template tests passed under the hosted Python 3.13 virtualenv (23 unique tests). They exercise namespaces, ownership spoofing, age/consent, delegate revocation, block checks, private drafts, subscription bypass attempts, archive handle reservation, stale edits, rollback, CSRF, fresh auth, template escaping and Sandbox URL generation. The harness uses mocked age/contact callbacks and a minimal base template. It does not certify the actual global application guards or deployed appearance.

## Remaining before rollout

1. Full-app testing against current Production and Sandbox copies, additive migration/backup rehearsal, existing privacy/moderation/export/retention integration and browser layout/keyboard acceptance.
2. Delegate invitation/acceptance and ownership-transfer flows. This draft's delegate storage API is not a public invitation endpoint. No invitations are sent and users do not receive page permissions on either live site.
3. Explicit page acting identity for posts, attribution/audits, follow/unfollow, reporting, moderation and search/feed integration. Pages must never bypass the underlying actor's restrictions or expose a private owner's personal information. Page posts/media are not part of this increment.
4. Connect a payment provider to the approved $5 USD / three-calendar-month recurring plan (500 USD cents; interval month, count 3; no setup fee). Disclose the full recurring amount before purchase; cancel at period end, retain paid access until then, and do not grant unpaid future periods. Advertising is separate. Add disclosed checkout, provider-verified entitlement, idempotent event processing, cancellation/renewal/failure/refund behavior, account closure handling and reconciliation. Browser return URLs must never grant paid access. Decide whether public business pages follow owner age rules or a separately reviewed business-content policy before exposing them to minors.
5. Add account navigation and register the module only after those integration checks. The HTML files are previewable/testable source, not a claim of live availability.

No business activation, real charge, live fixture account, notification, or change to existing personal social behavior is performed by this draft.
