# Marketplace foundations — implementation increments 1–6

Prepared November 5, 2026 (Pacific). This is an inactive, provider-independent
increment toward MP-03/MP-06/MP-07, not a finished checkout or commerce release.

## Source and hosted inventory (MP-01)

Repository baseline: `f6cbb241fbca2511219d8154a1e54356c49e86b3`.
Existing modules provide seller/shop drafts and permissions (`seller_studio`),
managed artwork/files (`marketplace_assets`), trusted public preview grants and
owner fee benefits (`marketplace_catalog`), fee/shipping calculations
(`marketplace_core`), and private unpaid test orders (`marketplace_orders`).
The test-order tables and flows are retained unchanged. No real payment adapter,
provider-event processor, completed real-order lifecycle or fulfillment engine
is included in these increments. The second increment adds test-only immutable
order rehearsals, described below; these are not payable real orders.

Read-only hosted inspection found both Production and Sandbox have the same
SHA-256 values for the three audited modules:

| File | SHA-256 in both deployed trees |
| --- | --- |
| marketplace_core.py | 7b07d35a5af8a430bd619e784406bf999a084fd49c605f06fa5c34709489fbdc |
| marketplace_orders.py | a82b4ad91344943ed99fa98ba18ed2c2200216a1b8d85e630ce55ff1ebc54d31 |
| seller_studio.py | be4418bca0318b75033d6c7aa7e692a7a3f43523b5dc259671a30938e717aea3 |

Both live databases contain seller shops/listings/events/assets, public preview
grants, owner benefits, test quotes and test orders. Neither has the new ledger
or inventory tables. This inspection did not copy customer records or inspect
provider credentials. Filesystem free space is not PythonAnywhere account quota;
a fresh account-quota check is still required before deployment packaging.

## Implemented, inactive modules

`marketplace_inventory.py`: explicitly provisioned stock, atomic multi-SKU holds
for one seller, a 15-minute maximum lifetime, idempotent replay, conflicting-key
rejection, buyer-scoped release and separate test/live inventory. Listing edits
cannot clear reservations because stock is not derived from presentation revisions.
An absolute stock adjustment cannot reduce quantity below active holds.

`marketplace_ledger.py`: USD integer-cent double-entry journals, balanced postings,
append-only sealed entries, immutable account identity, transactional rollback,
idempotency conflicts and environment isolation. Corrections/refunds are new
journals. SQL triggers reject changes to sealed entries and unbalanced sealing.
Only posted journals appear in balance queries. Every API posting is transactional;
direct SQL writes that leave an open journal must be detected by future operational
reconciliation. This is not a tamper-proof audit system against a database admin.

Neither module is imported into app startup, initialized on a live database or
exposed through HTTP. Their identifiers are opaque internal references, not an
authorization mechanism. Future adapters must resolve eligible users, trusted
shops and stable variants before calling them. Use a dedicated SQLite connection
with foreign keys enabled; operations reject nested transactions. No secret,
customer address, payment token or bank detail belongs in these records.

## Provider prerequisites (MP-02) still requiring verification

| Integration | Required before real use |
| --- | --- |
| Stripe Connect | Owner-controlled platform account and supported connected-account model; approved seller onboarding, capability/payout checks, test/live credentials, signed webhook endpoint and replay/reconciliation tests. Existing Page billing is not evidence of Connect readiness. |
| PayPal marketplace | Approved platform/partner capability, seller consent/onboarding, correct payment/payout model, sandbox/live separation and verified webhook handling. A personal PayPal account alone is insufficient evidence. |
| Google Pay | Capability through a supported configured processor; only display when the processor actually reports support. |
| Shippo | Confirm the agreed platform account model, seller label billing and carrier access; complete address/rate/label/refund sandbox tests. |
| Pirate Ship | Keep the existing safe CSV contract; add authorized real-order export and tracking import. Do not claim an API integration. |

Provider account approval, credentials and commercial agreements were not verified
by this source audit. No provider calls, agreements, charges or payouts occurred.

## Next implementation dependencies

1. Seller onboarding and protected integration into Sandbox. Test-only stock mapping,
   eligibility/owner checks and owner-benefit binding now exist, but publishing and
   live seller/payment account capabilities remain unavailable.
2. Complete immutable payable quotes/order terms, payment attempt IDs and real-order
   activation. Test-only snapshots and reservation binding now exist. Stock consumption
   must be atomic with the verified payment transition;
   late payment after expiry needs an explicit refund/manual-review policy.
3. Complete provider transports, PayPal verification, durable event retry jobs,
   reconciliation and seller-scoped journal rules. A test-only Stripe signature
   verifier and minimal durable inbox now exist, as described in increment 3.
   A generic journal balances numerically; it does not authorize a seller transfer.
4. Listing fees/expiry/opt-in renewals, taxes/shipping and commission-refund policies
   wired to snapshots. Six percent excludes shipping/tax; owner exemption is trusted
   and owner-bound. Never trust a browser-supplied fee-waiver flag.
5. Purchases, fulfillment, refunds/disputes, downloads, memberships, support,
   accessibility and release gates remain tracked in the 24-package completion plan.

No existing test order may become a real sale. No payment-success endpoint is
introduced. The catalog and public purchasing availability remain unchanged.

## Validation

Run `python -m unittest discover -s tests -p verify_marketplace_foundations.py -v`.
Tests use temporary databases only and include last-unit contention from separate
SQLite connections, rollback, buyer/seller/environment isolation, expiry boundaries,
idempotency, immutable journal SQL guards, reversal accounting and proportional
refund rounding. Also run the existing `python tests/verify_marketplace_core.py`.

## Increment 2: order/reservation rehearsal

`marketplace_checkout.py` adds opt-in `marketplace_checkout_skus` and
`marketplace_checkout_orders` tables. Only `test` environment records are accepted,
both by the API and SQL constraints. They cannot be relabeled as live orders.
There is no `paid` state, application registration, public endpoint or provider call.
Existing `seller_test_orders` and `seller_test_quotes` remain untouched.

Owner-authorized synchronization gives each listing option an opaque stable SKU.
Because the current editor identifies variations by row position, this adapter
matches existing variations by case-insensitive label. Reordering preserves IDs;
renaming creates a new ID and deactivates the old one. Changing the set of variation
identities is rejected while the listing has active reservations, preventing a
renamed option from duplicating stock. Explicit editor-level immutable variation
IDs and editor integration remain future work. Provisioning is a test operation,
not a fulfilled-stock reconciliation mechanism.

Checkout accepts SKU, quantity and expected listing revision; it reads prices,
descriptions, policies and owner-bound fee benefits on the server. Orders preserve
that snapshot after later edits. Reservation and order insertion share one SQLite
transaction; a failed order write rolls back its hold. SQL triggers protect order
identity/snapshot and synchronize cancellation/expiry when a hold is released.
Bounded internal expiry maintenance closes timed-out rehearsals. Request retries
return the existing order without new stock or repricing; conflicting reuse fails.

The default policy adapter reuses existing `seller_studio` eligibility/owner checks
and `marketplace_catalog` visibility/fee policy. Buyers and shop owners must be
eligible adults; blocked/muted/hidden or ownership-transferred contexts are rejected.
Stock provisioning and seller-side order reads require actual shop ownership;
Page listing-edit authority does not grant order access. Buyers retain their own
snapshot access if a shop later freezes, subject to their own current eligibility.

Shipping, tax and payable total are explicitly `null`, payment is disabled, and
digital file versions are explicitly unbound. These orders cannot authorize a
purchase or grant a digital entitlement. US eligibility, shipping/tax quotation,
listing publication, immutable digital manifests, provider capability checks,
signed event handling, stock consumption and financial posting remain prerequisites
for a real checkout. No address is collected in this increment.

Validation: `python -m unittest discover -s tests -p 'verify_marketplace_*.py' -v`
passes 48 tests plus the existing 38 money/shipping checks. The new checkout tests
cover rollback after order-write failure, simultaneous duplicate checkout, last-unit
contention, stale revisions, cross-seller rejection, snapshots, fee exemptions,
privacy, cancellation, expiry and variation identity changes. Five tests exercise
the existing seller/Page/catalog policy modules with controlled age/contact service
inputs. This does not establish full Flask/session or hosted acceptance. Tests
use temporary databases; neither hosted application/database was changed.

## Increment 3: account bindings and Stripe event reconciliation

`marketplace_payments.py` adds opt-in, test-only records for owner-bound onboarding
requests, provider accounts, shop/account links, synthetic payment expectations and
minimal event receipts. All records are separate from the old test-order tables.
Both schema and service reject live mode. It is not registered with Flask or any
hosted application, and no provider credentials are included.

Only eligible shop owners can begin a bound onboarding request. Completion calls
a configured server-side resolver with that opaque request ID, then rechecks owner
authority after the resolver returns. The resolver must establish provider-side
ownership/consent using authenticated platform calls and the server-created request;
browser-return parameters or merchant-entered IDs cannot serve as that proof.
Actual provider account creation, consent URLs and those authenticated resolvers
are **not implemented or tested against provider APIs** in this increment. Tests
use explicit synthetic resolver fixtures. An onboarding completion record is not
evidence that the site's Stripe/PayPal platform has been approved for live commerce.

Account identity, owner and provider/platform/environment binding cannot change
through an update. Multiple shops belonging to one owner can share an account;
another owner cannot claim it. Shop relinking requires a future explicit support
workflow. Capability refreshes validate the original identity, reject older server
observations and retain restrictions when another shop is linked. Request, account
and receipt identifiers are opaque references; secrets and identity documents are
not stored in these tables.

`StripeTestWebhookAdapter` supports **v1 connected-account snapshot events** only.
It verifies HMAC-SHA256 over the exact raw body, a five-minute signing-time window,
multiple v1 signatures and configured signing-secret rotation. It rejects live
payloads, duplicate JSON keys, invalid/nonfinite JSON and oversized input. These
direct-charge test fixtures do not select the Production charge/responsibility
model. Thin events, platform-scoped destination charges and PayPal verification
are not implemented here.

Receipt identity is unique by environment/provider/platform/event, with account,
event type, payment object, creation time and a semantic fingerprint retained.
The first body hash is retained, but raw bodies, signatures, API exceptions,
client secrets and customer fields are discarded. Validly re-signed redeliveries
may differ in incidental delivery fields without creating a second receipt; a
conflicting event identity is rejected.

Known payment references are reconciled through a configured canonical
PaymentIntent resolver, outside a database write transaction. That resolver must
use the pinned platform's test credentials and the exact connected-account context;
the authenticated network implementation is still absent. Reconciliation checks
canonical object/test mode, order reference, currency, amount, linked owner,
capabilities, current permissions and active reservation. It uses canonical status,
rather than trusting the event label; terminal success/cancellation observations
cannot regress. Provider outages produce a durable `retry` receipt, while unknown
payments, mismatches and late success need review. A future endpoint must have a
working retry worker or appropriate provider redelivery behavior; recording a
receipt alone does not justify returning success and abandoning reconciliation.

The expectation API is deliberately named `track_test_payment`: it matches a
synthetic object to the existing rehearsal's **item subtotal**, which remains
nonpayable. An `observed_test` result does not pay an order, consume stock, post a
journal, send a receipt, purchase postage or grant downloads. Real attempts must
instead bind a final immutable shipping/tax quote, with one winning settlement per
order across processors and the full refund/reconciliation path. Expired/canceled
reservations and changed ownership/capabilities never acquire fulfillment rights.

Validation: all **76 tests plus 38 existing money/shipping checks** pass locally.
The 28 new tests cover signature forgery/body changes/rotation/replay windows,
test/live separation, duplicate concurrent receipts, canonical mismatches/outages,
out-of-order events, late success, redacted receipt storage, owner-bound onboarding,
capability refresh and cross-owner/relink rejection. Test signatures are generated
fixtures, and API resolvers are simulated. Provider sandbox, SDK interoperability,
actual account consent/capabilities, request/session and hosted acceptance remain
unverified. No live configuration or database changed, and no provider API call,
payment, payout, postage or commercial agreement occurred.

Provider references checked November 5, 2026 (Pacific):

- Stripe webhooks: https://docs.stripe.com/webhooks
- Connect event/account scopes: https://docs.stripe.com/connect/webhooks
- Signature and delivery guidance: https://docs.stripe.com/events/manage-webhook-endpoints
- PayPal's separate verification/registered-webhook requirements: https://developer.paypal.com/api/rest/webhooks/rest/

## Increment 4: complete test quotes and authenticated provider reads

`marketplace_quotes.py` adds immutable, expiring complete test totals and explicit
buyer acceptance. Owned/versioned location lookup and shipping/tax calculations
are configured service boundaries. Actual address storage, shipping rates and tax
calculation/remittance policy are not implemented by those boundaries. Tests use
fictional reference-only locations and explicit assessment fixtures. A missing
calculator or response never becomes an assumed zero tax/shipping amount.

Each quote binds order terms, buyer, shop, address reference/version and assessment
context hashes. The tax calculator receives the selected shipping assessment, so
its shipping-taxability decision can be explicit. Amounts are bounded integer USD
cents, the platform commission remains item-only, and complete totals expire at
the earliest of five minutes, reservation expiry and either assessment's expiry.
Order/listing/shop/fee-policy changes, hidden/transferred ownership, canceled holds,
address-version changes and mismatched evidence invalidate use. Raw addresses are
not persisted in quote records. A future address store must preserve the accepted
immutable version for delivery/retention rather than reusing a mutable current address.

An accepted quote can be bound to a new synthetic test-payment expectation using
the complete amount, including shipping/tax. Canonical Stripe metadata must match
both order and quote. Quote expiry or stale terms route the observation to review.
Unquoted subtotal-only expectations cannot be upgraded or downgraded into a quoted
attempt; test records still cannot become live orders. Even a matching full-total
observation leaves the order unpaid and creates no entitlement or financial posting.
The snapshot explicitly keeps commercial payment authorization disabled, publication
eligibility unestablished and purchased digital versions unbound.

`marketplace_provider_api.py` now supplies real HTTPS request code for:

- Stripe test-key reads: verify the key's configured platform identity, retrieve
  connected-account capability/owner-binding metadata, and retrieve canonical
  PaymentIntents using an explicit `Stripe-Account` context. Requests pin API version
  `2026-10-28.endive`. Onboarding resolution also requires a trusted server-created
  account/request association; account metadata alone or a browser-return ID is
  insufficient. No account creation/consent URL or charge model is selected here.
- PayPal sandbox OAuth and remote signature verification using the registered
  sandbox app webhook ID. It validates verification headers, rejects untrusted
  certificate scopes, never downloads the certificate URL, and requires an explicit
  `SUCCESS` response. PayPal simulator mock events cannot use the postback method.
  Durable PayPal receipt processing and canonical order/capture reconciliation
  remain unfinished; verification alone grants no order rights.

The default HTTP implementation pins provider HTTPS origins and an endpoint/method
allowlist, disables redirects and environment proxies, uses certificate verification,
sets ten-second network timeouts, bounds response sizes and redacts provider errors.
Stripe live keys and PayPal live origins are rejected. No automatic credential
discovery occurs. The allowed operations contain **no payment creation, confirmation,
refund, transfer, payout, account creation or postage purchase**. Configured credentials
must remain private; API responses may contain sensitive fields in memory and must
not be logged or sent to a browser. The receipt adapter persists only minimal IDs/hashes.

Validation: **109 tests plus 38 existing money/shipping checks pass locally**.
The 33 new tests cover complete amounts/evidence, missing-vs-zero components,
context mutation, consent, expiry, changed terms/addresses, quote/payment binding,
forced-write rollback, backup/restore with foreign-key verification, provider request
authentication/account scoping, live-origin/key rejection, path/header/host attacks,
remote verification failures, bounds and redacted timeouts. HTTP is mocked; no real
credentials or provider API requests were used. Actual provider sandbox access,
network egress, registered webhook behavior, SDK equivalence and hosted acceptance
are still unverified. No Sandbox/Production deployment or live migration occurred.

Additional primary request-contract references checked November 5, 2026 (Pacific):

- https://docs.stripe.com/connect/authentication
- https://docs.stripe.com/api/accounts/retrieve
- https://docs.stripe.com/api/payment_intents/create (version/amount contract only; creation is not implemented)
- https://developer.paypal.com/api/rest/authentication/
- https://developer.paypal.com/api/rest/webhooks/rest/

Next: actual provider account/operating approval and consent, real owned/versioned
address storage, shipping/tax services/policy, publishable listing eligibility,
idempotent provider attempt creation, PayPal canonical event processing and durable
retries. Then add one winning settlement per order across processors with atomic
stock/accounting/refund effects, before hosted UI/acceptance and any live pilot.

## Increment 5: encrypted address versions and fixed domestic shipping

`marketplace_addresses.py` replaces the address-only fixture boundary with a native,
test-only encrypted store and location resolver. It uses `cryptography==50.0.2`,
already in the repository lock and matching the local validation environment.
Fernet/MultiFernet perform authenticated encryption and key rotation. Keys must be
explicit server configuration, kept separately from databases, source and logs.
No key is created automatically and no missing-key/plaintext fallback exists.

Buyer destinations and seller origins are owner-bound. Edits create new encrypted
versions and use optimistic concurrency/idempotent replay, rather than replacing
past address data. The authenticated encrypted envelope binds owner, book/version,
purpose, shop and environment; ciphertext moved to another row is rejected. ZIPs
remain strings, including leading zeros. Validation covers format/bounds, not postal
deliverability. This initial format supports US states plus DC; territories and
military address formats remain outside this test implementation.

Regular reads are owner-only and record metadata-only view events. Listing address
references and audit rows does not reveal recipient/street/city fields. Buyers do
not gain access to seller origins; sellers/Page editors do not gain access to buyer
addresses. Shop changes never transfer address ownership. Archive/restore prevents
new use without erasing retained history. Paid-order seller access, support access,
retention/erasure policy and customer UI are separate unfinished work; no blanket
seller-address-read endpoint is introduced.

Quotes now retain an immutable opaque binding to the exact origin and destination
versions used. A buyer can recover their own historical destination through that
binding, without receiving the seller origin. Native resolver checks run again
inside the quote/consent/payment-binding write transaction, closing the gap between
initial resolution and committing use of an address. Address edits, archive/restore,
origin changes and shipping-profile changes invalidate pending quote use. Rotation
rewrites ciphertext while preserving semantic version IDs, so it does not invalidate
an otherwise-current quote. This is not a claim of protection against a compromised
application runtime holding the encryption keys.

`marketplace_shipping.py` adds explicit owner-configured fixed domestic charges:
one base charge per order plus a charge per physical unit, optionally capped. The
seller can explicitly configure free shipping. Digital-only carts have zero shipping.
Profile versions are immutable; owner checks, stale-write handling and current-profile
bindings prevent silent changes to a pending quote. This is a seller-defined shipping
charge, **not** a carrier rate, label purchase or replacement for the agreed Shippo
integration and Pirate Ship/manual fulfillment workflow.

The combined resolver connects encrypted locations and shipping profiles to the
existing complete-quote/consent/payment-expectation flow. It also provides a private,
version-bound calculation handoff containing minimum street/city/state/ZIP/country
fields, excluding recipient/company. It does not transmit that data anywhere.
External tax/carrier adapters still need their disclosed, approved data flow and
actual service integration. Tax is still required explicitly and is never assumed
to be zero. The native integration tests use a clearly fictional tax assessment and
simulated canonical payment state; actual tax responsibility/calculation remains open.

Validation: **136 tests plus 38 existing money/shipping checks pass locally**.
The 27 new tests use actual encryption, not a mock cipher, with fictional addresses
and ephemeral generated keys. Coverage includes ciphertext/metadata privacy, wrong
keys/swapped tokens, authorization, archive/history, key rotation, concurrent edits,
write rollback, encrypted backup/restore/FK checks, fixed combined/capped/free shipping,
quote invalidation, historical binding recovery and native quote-to-test-reconciliation.
Successful reconciliation still leaves an order unpaid and stock unconsumed.

No dependency changes, real customer data, external data transmissions, provider
calls, deployed key configuration, application registration or Sandbox/Production
migrations/deployments occurred. Before collecting real addresses, configure and
rehearse private key backup/recovery and rotation, authorize the retention policy,
implement scoped UI/CSRF/rate limits and complete hosted privacy/permission checks.
Backups of ciphertext need the separate keys to be recoverable; retiring keys must
account for historical versions and retained backups. Fernet exposes token creation
timestamps, not address contents, as described in its documentation.

Primary encryption reference checked November 6, 2026 (Pacific):
https://cryptography.io/en/50.0.2/fernet/

Next: real tax/carrier services and policy, seller consent/provider associations,
publishable listing eligibility, durable event retries/PayPal canonical processing,
one-winning-payment stock/accounting/refund settlement and scoped customer/seller UI,
then hosted acceptance. All commerce activation gates remain open.

## Increment 6: durable event recovery and canonical-state polling

`marketplace_payment_jobs.py` adds a SQLite-backed, test-only recovery queue for
Stripe receipts. Signature verification still happens before receipt creation;
the verified minimal receipt and its job are then committed in the same transaction.
Backfill preserves existing receipts and derives initial states without resetting
already-recorded job attempts or leases. Historical processing counts that were
never recorded by older code cannot be reconstructed and start at zero on backfill.

The synchronous receiver and bounded worker use the same leased reconciliation
path. A worker claims a receipt in a short `BEGIN IMMEDIATE` transaction, releases
the write lock before canonical provider retrieval, then rechecks its random lease
token/attempt and expiry before atomically committing the observation, receipt and
job result. A crash leaves the job recoverable after its 60-second lease expires.
A stale/expired worker cannot overwrite another worker's result. Clock handling
accounts for elapsed lookup time; reservation/quote/permission checks use completion
time rather than trusting the time the request began.

Worker retries use exponential delay starting at 30 seconds, capped at 15 minutes,
with eight total processing attempts per receipt. Provider outages retry; pending
or retryable failed canonical states are polled using the existing verified receipt,
so a missing completion webhook can be recovered. No raw payload/signature is stored,
replayed or forged for recovery. Canonical reads retain the exact provider/platform/
account/payment scope, amount, order/quote and permission checks already described.

Definite binding/eligibility/expiry conflicts go to review rather than an automatic
retry loop. Exhausted jobs remain visible for review instead of disappearing. A
newly signature-verified provider redelivery may expedite a delayed/reviewed job,
but cannot override an active lease, cached terminal success or the attempt cap.
Internal scheduled processing respects backoff. Terminal observations are cached
for duplicate deliveries. Queue summaries expose only aggregate states/due counts,
without customer records, keys, payment references or lease tokens.

`StripeTestPaymentReader` separates canonical lookup from webhook verification:
the recovery process needs its configured read credentials, not the endpoint's
signing secret. It cannot be used to ingest a new webhook. The existing webhook
adapter inherits the same canonical validation, while keeping signature checks
mandatory at ingestion. All adapters and receipt schemas remain test-only.

`run_due(db, adapter, now, limit=25, ...)` performs one worker tick with a maximum
batch of 100; it does not sleep or install a schedule. `reap_exhausted` handles final
crash leases, and `summary` provides internal diagnostics. These are server-only
functions, not seller/public endpoints. No cron, task service, heartbeat, alerting
or operator review UI has been configured or deployed. Before operational use,
configure scoped test credentials, polling frequency, process limits, failure alerts,
authorized review procedures and hosted crash/recovery acceptance. Do not treat a
persisted receipt as permission to acknowledge and abandon a real event without a
working recovery process.

Validation: **160 tests plus 38 existing money/shipping checks pass locally**.
The 24 new tests cover atomic receipt/job persistence, backoff/exhaustion, recovery
without redelivery, missing completion events, crashes before/during processing,
expired and reclaimed leases, stale-worker fencing, reservation expiry during a
lookup, concurrent claims on separate SQLite connections, final-write rollback,
scope/clock/batch guards, legacy backfill, lease-preserving backup/restore, eligibility
revocation and operation without signing-secret access. Provider responses remain
fixtures; actual provider sandbox and hosted-worker acceptance are unverified.

No app registration, scheduler, live DB migration, deployment, provider API call,
charge, payout or fulfillment occurred. Queue completion and canonical test success
still do not mark an order paid, consume inventory, post a journal or grant downloads.
PayPal canonical receipt processing and the real one-winning-payment settlement/
refund lifecycle remain open; this increment does not complete MP-08 or MP-20.
