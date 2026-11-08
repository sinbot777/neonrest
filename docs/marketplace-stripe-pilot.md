# Stripe and carrier-rate Sandbox pilot

Status: implementation candidate; not mounted on either running site. No public or live checkout.

## Implemented

- Explicit allowlisted Sandbox blueprint (`marketplace_pilot_views.register`), real-session authorization callback, existing CSRF/rate-limit helpers, private/no-store receipts and seller queue.
- Published physical stock -> immutable reservation/order -> encrypted fictional destination -> explicit Shippo address-sharing consent -> selected carrier rate -> complete shipping/tax quote -> explicit total acceptance.
- Durable original payment terms before provider calls. Stripe test-card submission, signed-receipt/canonical reconciliation, full-total settlement and stock consumption. A browser return never settles an order.
- Lost payment/refund responses reuse original provider idempotency and durable identities. Early verified events can recover a lost creation response; conflicting/late payments stay in review.
- Original seller-only paid destination access from the winning quote's encrypted historical address version, with immutable fulfillment audit. Manual single-package tracking; no postage purchase or delivery verification.
- Partial/full component refund plans, canonical confirmation and balanced ledger reversal. No automatic restock.
- Seller-specific Shippo test rate adapter, fixed shipment endpoint only. Live keys/responses refused. Measured parcel profile binds rate/quote freshness; buyer/order/address/profile changes invalidate old rates.

## Boundaries

The Flask integration tests use deterministic provider HTTP, fictional addresses and an explicit fixture policy. These prove request/database integration, not real Stripe/Shippo acceptance or visual browser quality. The older provider-only Stripe test payment/refund proof is separate and does not establish this application flow.

The first shipping pilot supports domestic USD, one shop and one package per order, a measured package and uniform per-unit item weight with a maximum quantity. It is not a general bin-packing or per-variant-weight implementation. Actual seller measurements must be supplied; fixture dimensions are not production defaults. No Shippo transaction/label API exists.

The isolated database marker is an additional deployment guard, not authorization. Host wiring must use actual site session, age, moderation, block/mute, publication, Page ownership and seller policy. Do not use test policy fixtures in a hosted authenticated pilot or claim a seller account by accepting a browser-supplied provider ID.

## Required host setup before activation

1. Reconcile this draft branch with current main; preserve subsequent Page features. Do not deploy this branch's old complete app tree.
2. Preserve the existing mounted webhook runtime and its DB. Provision an isolated pilot DB deliberately, with FK enforcement and native catalog/user fixture copies appropriate to approved testers. Never initialize a live application DB automatically. Initialize native checkout, addresses, quotes, payments, settlement, refunds, carrier, purchase-flow, order/audit schemas and marker in dependency order.
3. Configure an explicit adult tester allowlist and real-session `authorize(uid)`. Set `MARKETPLACE_TEST_PILOT=True` only in Sandbox. Register the blueprint only after service factories, templates and existing CSRF/rate limiting are available. No fresh-auth demand is added to ordinary pilot operations.
4. Retain encryption keys outside source/web roots. Configure owner-bound Stripe test account through trusted onboarding state and canonical owner/onboarding metadata, plus exact signed webhook scope. Do not fake account metadata to force an association.
5. Supply seller-specific Shippo test token privately, owned origin address, measured package dimensions, empty packaging weight, per-item weight and maximum units. At the 2026-11-08 inspection the Sandbox private directory contained Stripe/PayPal onboarding/webhook configs but no Marketplace Shippo configuration. No Shippo secret was requested or printed.
6. Supply a real configured tax calculator/responsibility model. `tax=None` refuses checkout. The 90-cent fixture calculation is not a tax rule. Never silently use zero or infer obligations from the seller's home state.
7. Wire signed events and periodic recovery into the same isolated order DB. Request-triggered refresh is a recovery aid, not the only worker schedule. Refund canonical polling is present; broader signed refund/PayPal event processing remains separate work.
8. Run genuine provider test purchase, lost-response recovery, fulfillment-address access and refund against bound application orders; verify fees, provider objects, stock and journals. Review mobile/desktop appearance and keyboard operation on hosted Sandbox.

## Live release gates still open

- Approved live charge model, platform fee collection, provider fees, disputes, tax, refund policy and merchant responsibilities.
- Hosted/Elements customer payment collection and required authentication flows (this adapter accepts fictional tokens only).
- Genuine seller onboarding association and webhook/worker operational wiring; PayPal is not checkout-ready.
- Product-specific dimensions/weight data and packing rules beyond the restricted first pilot.
- Buyer/seller notifications, fulfillment correction workflow, customer help, monitoring and operational recovery/review queues.
- Explicit live activation approval and owner-performed real purchase/refund acceptance.

## Validation

Run individual `verify_marketplace_purchase_flow.py` (12), `verify_marketplace_carrier_rates.py` (9), `verify_marketplace_pilot_views.py` (8). The component suite adds 29 tests to the previous 275-test baseline: 304 tests plus 38 script money/shipping assertions. Four legacy host-stage CLI scripts are not unittest discovery modules; the guarded rehearsal manifest deliberately excludes them. Tests contact no external financial or shipping provider.
