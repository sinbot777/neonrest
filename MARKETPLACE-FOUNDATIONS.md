# Marketplace foundations — implementation increments 1–2

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
3. Authenticated provider inbox with provider/account/environment/event uniqueness,
   duplicate/out-of-order recovery, reconciliation and seller-scoped journal rules.
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
