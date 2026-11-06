# Marketplace foundations — implementation increment 1

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
is included in this increment.

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

1. Stable seller-owned SKU/variant mapping, adult eligibility checks and owner-benefit
   binding, followed by seller onboarding and protected integration into Sandbox.
2. Real immutable order/line/fee snapshots, attempt IDs and reservation-to-order
   binding. Stock consumption must be atomic with the verified payment transition;
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
