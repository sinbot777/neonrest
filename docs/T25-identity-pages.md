# T25 identity pages — first implementation increment

Status: creative-page rollout candidate. T25 remains incomplete because business billing and broader social integration remain separate. The candidate now registers its routes in the app and links Your pages from account navigation.

## Confirmed product rules

- Personal signup creates an `@handle` account; pages belong to a registered personal account and never gain login credentials.
- Creative `_handle` pages are free. All eligible existing members may own them, including children whose existing parental approval remains valid. This does not reopen under-13 signup.
- Business `$handle` pages require adult ownership (18+) and a recurring subscription. The owner selected this model on October 23, 2026 Pacific. Approved launch terms: $5 USD per business page every three calendar months, no setup fee; cancellation stops renewal and preserves access through the paid period. Creative pages stay free; advertising placements are separate. The payment provider is not yet selected.
- Each prefix has its own case-insensitive namespace. Canonical page URLs are `/_handle` and `/$handle`, or their `/sandbox` equivalents. No existing personal handle is renamed.

## Implemented in this draft

Additive page, delegate and action tables; opaque page IDs; lowercase handle validation; private draft creation; plain escaped name/description editing; creative publish/archive/restore; owner-only visibility control; revision conflicts; fresh-auth/CSRF gates; responsive templates and prefix-aware routes. Caller transactions serialize creation and preserve rollback. Archived handles stay reserved. Initial resource bounds: 20 owned pages, 20 delegates per page, 80 name characters, 4,000 description characters.

Owner eligibility checks verified personal identity, current age/parental readiness, deactivation, account disabling and posting restrictions. Page delegation requires current contact permission; blocks, revoked consent and account restrictions are checked again at use. Creative page readers retain owner-based age/block rules. Business publishing is rejected server-side even if submitted form fields claim payment succeeded. Business drafts incur no charge. No checkout, subscriptions, payment webhook or charges exist in this increment. Published creative pages support escaped text updates (5,000 characters), immutable personal authorship, owner/author removal and bounded cursor navigation. The current owner and each post author retain age, consent, block and moderation checks.

A page-scoped export function includes only owned pages, the account's delegations and its own actions. It is wired into the authenticated account export. Future erasure is blocked when page ownership, delegation, authorship or audit dependencies need reviewed transfer/disposal; permanent erasure remains globally disabled. No current account/post rows are rewritten.

## Validation boundaries

Nineteen policy/state tests and nine additional isolated Flask route/template tests pass (28 unique tests). A separate full-app harness passed 55 checks against each currently deployed Production and Sandbox baseline, staged with this candidate and disposable online-backup databases. It exercised the real active-session, origin, CSRF, fresh-auth, verification, birthday/consent, blocking and posting-restriction guards, plus namespace routes, text updates, archiving, own-data export and future-erasure dependencies. External provider calls were forbidden; no live account/content/subscription was created.

The full-app fixtures include actual global application guards; the smaller policy harness still uses mocked age/contact callbacks. Browser review of the actual rendered templates covered dashboard, creation, editing and public page at 390px and 1,280px (eight page/viewport combinations), with no horizontal overflow, 16px body text, labeled controls, readable links/buttons and a visible keyboard focus outline. Temporary fictional preview files were removed after review. Broader social integration and provider subscription lifecycle remain outside this initial frontend/backend increment.

## Remaining before rollout

1. Hosted full-app validation passed 55 checks per baseline. Initial desktop/narrow layout and keyboard focus checks passed. Rehearse additive live migration/backup before deployment; broader device/assistive-technology acceptance remains separate. Page/update reporting, private immutable evidence snapshots, staff 2FA/fresh-auth review, hide/restore and recorded decisions are implemented. Owners cannot override staff restrictions; reporters can privately track decisions.
2. Delegate invitation/acceptance and ownership-transfer flows. This draft's delegate storage API is not a public invitation endpoint. No invitations are sent and users do not receive page permissions on either live site.
3. Extend the implemented page update identity/attribution/audits into follow/unfollow, search/feed integration. Page/update report and staff hide/restore flows are included in the creative rollout. Pages must never bypass the underlying actor's restrictions or expose a private owner's personal information. Initial page text updates are implemented in separate storage; feed/search/social integration, and richer media remain pending. Neither the private actor ID nor the owner's personal profile is displayed publicly.
4. Connect a payment provider to the approved $5 USD / three-calendar-month recurring plan (500 USD cents; interval month, count 3; no setup fee). Disclose the full recurring amount before purchase; cancel at period end, retain paid access until then, and do not grant unpaid future periods. Advertising is separate. Add disclosed checkout, provider-verified entitlement, idempotent event processing, cancellation/renewal/failure/refund behavior, account closure handling and reconciliation. Browser return URLs must never grant paid access. Decide whether public business pages follow owner age rules or a separately reviewed business-content policy before exposing them to minors.
5. Account navigation and app registration are implemented in this candidate. Merge/deploy only after the remaining integration and acceptance work. Candidate source is not a claim of live availability.

No business activation, real charge, live fixture account, notification, or change to existing personal social behavior is performed by this draft.


## Creative rollout boundary

Creative pages include creation, publishing, text updates, report submission and private tracking, staff-factor-protected review with immutable evidence and hide/restore decisions. Reporting does not require fresh login, but staff review does. Existing account disabling and age/consent protections remain authoritative. Business pages stay private drafts; no payment provider, subscription, charge or business activation is enabled. Page follows, cross-feed/search discovery, delegate invitations/transfer and richer media remain follow-up scope. No new release version is declared.
