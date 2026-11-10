# Stripe and carrier-rate Sandbox pilot

Status: restricted Sandbox QA pilot mounted November 9, 2026 (Pacific). No public or live checkout. The current checkpoint below supersedes older dated observations.


## Current checkpoint — November 9, 2026 (Pacific)

The isolated restricted pilot is mounted at `/sandbox/marketplace/pilot/` for the explicitly approved seller and test buyer. A private revision-bound listing grant permits the QA draft only for those eligible testers; the grant does not publish it into the native public catalog. Current native adult, shop, Page and block/mute policy remains authoritative. No additional fresh-auth requirement was introduced.

The purchase database was provisioned from a copy of the previously approved shipping settings store. The old shipping and webhook stores were retained. The new signed Connect test endpoint and bounded recovery command use that same purchase store. Recovery is scheduled hourly at minute 15; manual execution of the identical worker command passed. Normal signed receipts attempt immediate DB-local settlement. An event arriving before payment binding is recovered by the scheduled worker or verified order refresh; immediate settlement is not guaranteed in that race. Existing retention and mail tasks remain intact.

The operator runtime is `marketplace_pilot_runtime`: `register(app, core, private_config_path)` returns the bridge and receiver; `mount(application, bridge['receiver'])` adds only `/sandbox/marketplace/pilot/provider-events`. The CLI takes that same private config path. Config requires `environment=test`, `worker_scheduled=true` only after a task actually exists, private database/vault/Stripe key/owner approval/hook paths, explicit `allowed_users`, one approved `sellers` mapping, and explicit `tax={kind: simulation_only, basis_points: 700}` for this QA run. Keep all config, keys, stores and recovery records outside source and served directories. Replace the old shipping-only registration rather than registering a duplicate blueprint.

Genuine provider/application acceptance completed:

- Two accepted 769-cent application orders used genuine Shippo test rates (11 returned; selected 619-cent shipping), 100-cent items and explicitly simulated 50-cent tax. Stripe's fictional Visa token created actual test-mode PaymentIntents on the approved connected account. Real signed events and canonical reads settled exactly those orders.
- The first event arrived before the creation response was bound. The worker recovered it and settled without a browser refresh. Repeating recovery did not add settlements or refund applications.
- The normal signed-in seller UI exercised queue, receipt, audited historical destination access, fictional manual tracking, a 50-cent partial refund and a 719-cent remainder. A second successful order proved deliberate lost payment/refund response recovery reused original provider identities, then fully refunded 769 cents.
- A genuine declined test card produced canonical failed status, no settlement and no fulfillment. Its original reservation deadline remains authoritative; failure does not grant a local early-cancel bypass.
- Final totals: two settlements, three applied refunds, all test ledger balances zero; SQLite quick_check is ok and foreign-key checks are empty. No live funds, payouts or labels were involved. Only published provider-example addresses were sent to Shippo.
- 360 component tests plus 38 money/shipping assertions pass locally and on the host. CodeQL and Python/JavaScript analyses pass on the reviewed application commit. Refund UI now uses unreserved component balances, hides an exhausted refund form, and displays refund/failure state consistently in queues and receipts.
- Actual seller queue, refunded/failed receipt and fulfillment screens were reviewed on desktop and at 390px; checked narrow layouts have a 375px document width. Visible fields have labels and keyboard focus reaches the next fulfillment control with a visible outline. Anonymous pilot requests return 401, new hook GET returns 405 and Production has no pilot route (404). Unsigned new and old hook requests remain rejected.

Remaining acceptance: a real separately signed-in approved buyer must complete the hosted buyer catalog/address/rate/quote/payment walkthrough, including narrow-screen and keyboard checks. Physical-device and assistive-technology review remain open. This is a QA pilot with provider-example addresses, provisional single-unit packing and simulated tax; actual shipping origin/measurements and a real tax/merchant responsibility model are still required for a real-goods pilot. Public merchant onboarding, live payment entry, fees/disputes, notifications/capacity/recovery operations, PayPal, digital delivery, commissions/memberships and controlled Production release remain separate unfinished scope. PR #124 remains draft/unmerged.

## Implemented

- Explicit allowlisted Sandbox blueprint (`marketplace_pilot_views.register`), real-session authorization callback, existing CSRF/rate-limit helpers, private/no-store receipts and seller queue.
- Published physical stock -> immutable reservation/order -> encrypted fictional destination -> explicit Shippo address-sharing consent -> selected carrier rate -> complete shipping/tax quote -> explicit total acceptance.
- Durable original payment terms before provider calls. Stripe test-card submission, signed-receipt/canonical reconciliation, full-total settlement and stock consumption. A browser return never settles an order.
- Lost payment/refund responses reuse original provider idempotency and durable identities. Early verified events can recover a lost creation response; conflicting/late payments stay in review.
- Original seller-only paid destination access from the winning quote's encrypted historical address version, with immutable fulfillment audit. Manual single-package tracking; no postage purchase or delivery verification.
- Partial/full component refund plans, canonical confirmation and balanced ledger reversal. No automatic restock.
- Seller-specific Shippo test rate adapter, fixed shipment endpoint only. Live keys/responses refused. Measured parcel profile binds rate/quote freshness; buyer/order/address/profile changes invalidate old rates.

## Boundaries

The component integration tests use deterministic provider HTTP and fixture policy. Genuine provider/native-policy and signed-in seller acceptance are separately recorded above; component results alone do not establish them.

The first shipping pilot supports domestic USD, one shop and one package per order, explicit package presets and per-SKU/variant weights with a maximum quantity. It is not a general bin-packing implementation. Actual seller measurements must be supplied; fixture dimensions are not production defaults. No Shippo transaction/label API exists.

The isolated database marker is an additional deployment guard, not authorization. Host wiring must use actual site session, age, moderation, block/mute, publication, Page ownership and seller policy. Do not use test policy fixtures in a hosted authenticated pilot or claim a seller account by accepting a browser-supplied provider ID.

## Host setup checklist (initial design; current QA completion above)

1. DONE November 9: current main was merged into this draft with both parents retained; Page and Service releases are preserved. Deploy only the reviewed pilot package, never replace the running Sandbox app wholesale.
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
- Public/live seller onboarding and production-grade webhook/worker operations; the isolated QA association and hourly worker are already installed. PayPal is not checkout-ready.
- Product-specific dimensions/weight data and packing rules beyond the restricted first pilot.
- Buyer/seller notifications, fulfillment correction workflow, customer help, monitoring and operational recovery/review queues.
- Explicit live activation approval and owner-performed real purchase/refund acceptance.

## Validation

Run individual `verify_marketplace_purchase_flow.py` (12), `verify_marketplace_carrier_rates.py` (9), `verify_marketplace_pilot_views.py` (8). The component suite adds 29 tests to the previous 275-test baseline: 304 tests plus 38 script money/shipping assertions. Four legacy host-stage CLI scripts are not unittest discovery modules; the guarded rehearsal manifest deliberately excludes them. Tests contact no external financial or shipping provider.

## Historical November 9 integration checkpoint (before QA mount)

PR #124 now contains main `0e53b4c27c24845e5acc214e92de379ce59c6f57` as an ancestor. Main's Page and Service changes are preserved. The draft remains unmerged; Production and the running Sandbox purchase scope are unchanged.

`marketplace_purchase_sandbox.register` provides an explicit host bridge for the existing Sandbox application. It refuses Production, the application database, missing purchase marker, missing configured tax/test providers, a missing recovery scheduling assertion, and unbound fixture policy. Its allowlisted native policy consults current adult eligibility, shop ownership, Page state, blocks/mutes, publication and exact listing contents. Only minimal IDs/catalog metadata are mirrored. Old buyers retain their own historical receipts after blocking a seller; blocks deny new checkout.

The bridge exports a signature-verified webhook receiver and a scheduled worker function using exactly the same private order store and native policy. Operator provisioning must actually mount/schedule these; the functions do not install themselves. Recovery scans bounded rotating receipt batches, settles only signed/canonical successes, preserves review states, and retries already-authorized refund dispatches with their original identities. It never creates a payment automatically. A same-revision mirror refresh no longer resets consumed test inventory. A changed listing with previously consumed stock is deactivated until explicit stock reconciliation, rather than importing its original quantity again. No refund restock is inferred.

Validation:

- 345 component unittests and 38 money/shipping assertions pass locally. Thirteen new host-policy/recovery tests cover allowlists, current content, inventory refresh, exact-once worker settlement, missing signatures, lost payment/refund responses and bounded cursor progress.
- 27 hosted checks pass against an isolated copy of the actual Sandbox application and a disposable database. The complete route/session/CSRF/native-age flow covers reservation, fictional carrier/tax quote, explicit total acceptance, fictional payment creation, same-store signed WSGI receipt and duplicate delivery, unsigned rejection, scheduled settlement without browser refresh, seller queue, encrypted historical address, tracking, full refund, no stock replenishment and actual block denial of new checkout. Provider HTTP is deliberately fictional: this is not genuine provider acceptance.
- Seven Node unit-conversion checks and five provider-readiness tests pass after fixing both CodeQL test-helper findings (case-insensitive script matching and parsed exact hostname comparison). Alerts were not dismissed.
- The actual shipping-settings preview passes a 390px layout check (375px document width), programmatic label inspection and initial keyboard Skip to content focus. This does not complete purchase-screen visual, physical-device or assistive-technology acceptance.
- Staging initially exhausted the hosting quota. Only this task's temporary copied stage was removed and replaced by read-only source links plus private candidate files. Existing releases, recovery records, application data and uploads were retained.

Read-only provider inspection confirms the existing Stripe test account has charges/payouts enabled but lacks canonical Neonrest owner/onboarding metadata. An arbitrary account ID or newly invented metadata must not establish merchant authority. A private Shippo test configuration exists, but the QA shop remains disconnected; no other shop's token was copied. Genuine bound purchase/refund remains blocked on trusted seller onboarding, the shop's explicitly verified test connection, actual origin/measured packing, an explicit tax/responsibility model, same-store provider endpoint provisioning and scheduled recovery. Live commerce remains disabled.

Operational evidence is retained privately on the host; no database, credential, customer payload, signing secret or private configuration is part of this PR.
