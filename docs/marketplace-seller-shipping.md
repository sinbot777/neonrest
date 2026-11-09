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

The complete local and hosted isolated suites pass 322 tests plus 38 money/shipping assertions. Hosted run `7e3d9f440e8e4fe48c5c965dec2d0610` verified 45 source blobs (603,613 bytes) at component `5e915408b65538b655d25558b3f59a4b9ccf45ec` using harness `edf1f2e72ace4e1d6a48edd84780fb5ed9710c5d`. Python 3.13.1, SQLite 3.37.2 and cryptography 50.0.2 reported zero failures, errors, skips, network, external database, live app/path or subprocess attempts during the guarded tests. Hosted footprint was 666,923 bytes. A separate genuine Shippo test-key read also passed the new connection verifier, with the key loaded privately on the host and no credential or carrier account details printed. This verifies provider authentication, not full merchant onboarding or a connected seller UI session. The new forms render through Flask/Jinja integration tests. Browser visual review is pending: the available browser rejected data-URL preview navigation, and the separate browser binary download failed integrity/unzip. No browser-policy workaround was attempted.

Pending: reconcile/mount on hosted Sandbox with real session policies and isolated provisioning, verify real per-merchant onboarding/callbacks and provider acceptance, browser/mobile accessibility review, integration with product editing and seller guidance, generalized multi-package packing, tax setup, and remaining payment/live-release gates. Production and live checkout are unchanged.

## Shipping-only host adapter

`marketplace_shipping_sandbox.register` adds a separate restricted mount to the existing Sandbox app. It refuses Production, the live application database, unmarked databases and non-private files. An explicit fresh-file provisioning step creates the isolated test store. Startup never migrates it. Current adult/account and shop/Page ownership decisions come from the existing Sandbox modules using the live request connection; the shadow metadata cannot grant permission.

On an allowed seller request, only that seller's eligible shop/listing/variation metadata is mirrored. User rows contain an ID only: no passwords, session keys, emails or dates of birth are copied. Native stock synchronization affects only the isolated store. Revoked ownership/eligibility is rechecked against the real Sandbox; deleted or nonphysical listings deactivate their mirrored stock identifiers. The preview scope returns 404 for checkout, purchases, payment, rates, refund, delivery-address and fulfillment routes even for approved testers. A conditional Seller Studio navigation link appears only when this mount's context flag is enabled for an approved eligible account. Existing Production templates without that flag render no link.

Seven additional tests exercise that gate, session/CSRF/owner protection, read-only source mirroring and absence of copied authentication data, live revocation, Production/existing-database refusal and deactivation without altering live stock. The combined local suite now passes 329 tests plus 38 money/shipping assertions. Hosted verification and actual deployment are separate recorded steps.


## Signed-in browser follow-up — November 8, 2026 (Pacific)

After owner sign-in confirmation, a private **Shipping QA — Sandbox only** shop and a two-variation **Shipping QA sample — not for sale** draft were created through the ordinary Sandbox UI. The shipping-only mount mirrored their metadata into its isolated settings store. Browser checks verified fictional encrypted origin persistence, two saved packages, enable/disable, capacity, separate variation weights, and stale-edit rejection without overwriting the current settings. The test fixtures are not published products.

A unit-selector bug was found and fixed: changing between inches/cm/mm or oz/lb/g now converts the displayed measurements. Stored integer micrometres/milligrams are retained through unit round trips and no-op saves; submission sends exact canonical units rather than rounded display approximations. Manually edited measurements are quantized upward once at the existing precision. Saved forms reopen in cm/g. JavaScript-disabled forms retain explicit-unit server parsing but do not auto-convert on selector changes.

Browser evidence: the 6.50 × 4.75 × 0.25 inch fixture reopens as 16.51 × 12.065 × 0.635 cm; 200 × 150 × 30 mm reopens as 20 × 15 × 3 cm. Fictional variation weights of 0.24 oz and 0.05 lb become 6.804 g and 22.68 g. The 0.10 oz packaging value becomes 2.835 g. These are QA inputs, not verified production packing measurements; the provisional Etsy packed-weight example was not treated as an established item/packaging split.

A stale-edit error also exposed purchase/refund navigation in the shipping-only preview. Its error page now offers Shipping settings and a settings recovery link; the full purchase pilot retains its own order guidance. The error text remains escaped.

Seven Node browser-script regressions pass locally (`node tests/verify_marketplace_shipping_units.cjs`), covering repeated switches/submits, smallest stored dimensions/weights, manual/exponent entry, new forms, per-item weights and invalid inputs. Three Jinja error-presentation tests pass in the hosted virtualenv (`python tests/verify_marketplace_shipping_error_ui.py`). These supplement the previously passed 329-case component suite and 38 money/shipping assertions; that full suite was not rerun for this template-only follow-up. Both deployed template blobs match the reviewed Git source. The isolated settings database passes integrity and foreign-key checks.

Only the two templates in the existing Sandbox shipping runtime were replaced, with original copies retained under `/home/sinbot/releases/seller-shipping-20261108`. The WSGI configuration, Production source and financial/purchase route restrictions were not changed. The QA shop remains unconnected to Shippo: no key was copied from another shop/configuration, no address was transmitted externally, no carrier quote or label was requested, and no payment occurred. Genuine per-shop provider connection/rates, broader purchase acceptance and narrow-screen/actual-device review remain separate gates.
