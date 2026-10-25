# Business billing launch checkpoint — October 24, 2026 (Pacific)

Live billing is disabled. Stripe's live account status shows Payments and Payouts active with no active account tasks. A live Neonrest Business Page product at USD $5 every three calendar months is prepared; no live subscription or charge was created.

PR #78 contains Production candidate code; PR #79 contains the Sandbox counterpart. Sandbox candidate installed with source rollback files and a verified online database backup. Production source remains unchanged.

Changes: restart checkout after a canceled subscription's paid period ends; Stripe-hosted payment-method/invoice management bound to the authenticated page owner's customer; no duplicate cancellation control after renewal stops; review holds block new subscription checkout; replace stale checkout-unavailable text.

Validation: 80 checks per environment (including 55 baseline page checks) plus 115-check page/social/calendar regression suites pass using disposable database copies. Mocked live entitlement checks prove canceled renewal retains paid time and expiry removes it; they are not actual live payment acceptance.

Remaining: adult Sandbox sign-in for browser checkout success/decline/abandon/retry and customer portal acceptance; live public support details and policy links review; private Production credential and signed-webhook configuration; final launch and actual payment handoff. The current Sandbox browser account is a teen, correctly barred from business-page creation. Do not alter age or bypass eligibility to finish acceptance.

## Browser acceptance completed

An owner-authorized fictional adult Sandbox account completed actual hosted Stripe test checkout. Verified abandonment without entitlement, retry reusing the same session, declined-card recovery, successful payment with signed-webhook paid-through confirmation, invoice display, adding a replacement default test payment method, and period-end renewal cancellation preserving paid time. The business page remained unpublishable in test mode. The provider test subscription was canceled after acceptance and the test page archived. No live charge occurred.

Remaining launch work: Production private credentials and signed webhook, customer-facing support/policy details, Production deployment and controlled live acceptance. Browser checkout is no longer awaiting an adult account.
