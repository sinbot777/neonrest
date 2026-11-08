# Seller shipping settings: test-mode implementation

This increment supplies general shop-owned shipping setup. An individual store's measurements are not a development prerequisite. No OregonButtonStore dimensions, key, user ID or shop ID is hardcoded in the new services.

## Behavior

The allowlisted Sandbox purchase blueprint now has Shipping settings, a shop picker, and owner-only forms for a verified Shippo test connection, encrypted origin address, reusable packages and per-stock-variation item weights. Existing login/session, adult eligibility, current shop/Page ownership, CSRF and rate-limit gates remain in force. Ordinary package/weight edits add no fresh-auth demand.

The setup screen accepts inches/centimetres/millimetres and ounces/pounds/grams. Decimal conversions use integer micrometres/milligrams and round upward only at that precision; a quarter-inch mailer is preserved as 6.35 mm. Keys are encrypted with the configured vault and never repopulated into forms or returned by the display service. Verification uses a fixed HTTPS Shippo carrier-account read, refuses live keys, does not follow redirects and returns sanitized failures. Disconnecting disables that shop's connection without claiming to revoke the key at Shippo.

Checkout sums each variation's own weight times quantity and adds the chosen package's fixed empty-packaging weight. It selects the smallest enabled preset within the seller's explicit item-count cap and the bounded weight limit. There is no geometric packing simulation: sellers must define safe presets/capacities. Missing item weights or a suitable package stop quoting rather than inventing shipping. Multiple items within one shop are supported; multiple packages/split shipments and different package restrictions per product remain future work.

Changes to connections, presets or item weights invalidate existing rate/quote locations. Saved paid-order historical destination snapshots remain intact. Connections/presets/weights/audit have immutable version history, optimistic save revisions and owner checks before and after provider verification. Credentials and settings never transfer automatically with a Page/shop owner change.

## Host integration

Imports register or migrate nothing. In the explicitly provisioned isolated Sandbox pilot database, run `marketplace_seller_shipping.initialize(db)` after checkout/address tables exist. Keep encryption keys private and separate from the database. Construct the same-connection service in the existing trusted factory:

```python
ctx.shipping_settings = SellerShipping(db, ctx.address_store.vault, policy)
```

`PilotServices.location()` and the rate-request route then use this service for shipping context, packing and the current shop's test API. Do not configure a shared owner's token as every shop's default. The older fixed-weight resolver remains only for existing explicitly configured component rehearsals; new seller settings use per-item weights. No real stored key is copied into a fixture or committed. The generic forms are not mounted by this source change.

The API-key form is explicitly test-only. Shippo's current documentation says multi-merchant marketplaces should use Platform/Managed accounts for carriers including USPS and UPS, while merchants maintaining their own Shippo settings/direct billing may require OAuth. Public onboarding must use the supported provider model and approved commercial configuration. This increment does not implement OAuth, create Managed Accounts, accept agreements, buy labels, or establish carrier marketplace approval.

Official references:
- https://docs.goshippo.com/platform-accounts/platform-accounts
- https://docs.goshippo.com/carriers/carrier-accounts
- https://docs.goshippo.com/guides/authentication

## Validation and release status

Eighteen new tests exercise two seller identities; encrypted/no-echo keys; shop, SKU, role and ciphertext binding; CSRF and explicit provider-verification consent; stale revisions; owner changes during verification; live-key refusal; connection failure/disconnect; repeat migration/immutable history; exact units; per-variation weight; package capacity/disable/selection; rate invalidation; all owner forms; and a signed test purchase settling through the generalized shipping service. Provider HTTP and site-policy boundaries are deterministic fixtures, not real provider/platform acceptance.

The complete local suite passes 322 tests plus 38 money/shipping assertions. The new forms render through Flask/Jinja integration tests. Browser visual review is pending: the available browser rejected data-URL preview navigation, and the separate browser binary download failed integrity/unzip. No browser-policy workaround was attempted.

Pending: reconcile/mount on hosted Sandbox with real session policies and isolated provisioning, verify real per-merchant onboarding/callbacks and provider acceptance, browser/mobile accessibility review, integration with product editing and seller guidance, generalized multi-package packing, tax setup, and remaining payment/live-release gates. Production and live checkout are unchanged.
