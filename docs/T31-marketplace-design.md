# T31 — Artist marketplace, memberships and fulfillment

Decision record: October 27, 2026 (Pacific). Approved product design, not live sales or a payment-provider contract. T31's specification scope is complete; implementation, provider approval and financial launch acceptance remain open.

## Product and identity

Neonrest combines Page-based artist shops, physical and digital goods, scoped commissions and recurring creator memberships. Preserve creator ownership, clear usage licenses, voluntary participation and ordinary free community access. Listings support title, escaped description, preview images, category, condition where relevant, variations, stock or made-to-order capacity, price, delivery timing, shipping/return rules and explicit license terms. Free drafts, preview, publish/unpublish/archive and versioned edits are required. Order records retain an immutable description/price/policy snapshot. Ratings/reviews come from verified purchases with reporting and appeal controls, never paid moderation exemptions.

Launch with adult US sellers, USD checkout and domestic physical shipping. Purchasers must be adults initially too; younger member checkout remains disabled until a separately reviewed guardian purchase design exists. Ordinary youth community access is unchanged. This is an implementation default, not an assertion about universal age law. Account DOB locks, blocks and consent protections remain intact; payment onboarding must not let users edit their age. Seller verification and provider onboarding are separate from ordinary Page creation.

Support lawful categories that also satisfy processor/carrier rules and Neonrest's mixed-age marketplace standards. Restricted categories are denied by default until reviewed. Copyright complaints, counterfeits, unsafe/recalled goods and prohibited services need reporting and enforcement flows. Public mixed-age previews must be appropriate independently of seller eligibility. Tax calculation/remittance, seller identity/reporting, privacy retention and applicable consumer rights require a documented launch review; provider integration alone does not discharge them.

## Agreed fees and sustainability

- USD $0.10 per published listing, valid four months. Drafts free; no extra listing charge per unit sold. Expiry renewal off by default; show the charge and require explicit renewal authorization. Inventory/variants do not silently multiply listing charges.
- 6% on physical/digital/commission item or service subtotal after discounts, excluding tax and separately stated shipping. No extra buyer Neonrest service fee. Shipping must represent actual fulfillment rather than disguise item price; audit abuse without automatically changing fees.
- Creator memberships: 6% of successfully collected membership amount excluding tax; no listing charge for a tier. Tips, if implemented, use the same disclosed 6% rather than an undisclosed special rule.
- Processor, conversion and necessary payout charges are separately disclosed before seller enrollment and in statements. Never advertise a guaranteed net payout before provider configuration is known. Platform subscription/Connect/Shippo charges paid by Neonrest are organizational expenses unless separately agreed and clearly disclosed.
- Refund Neonrest's percentage proportionally for refunded item amounts, including partial refunds, once only. A successfully published listing fee normally remains earned; platform publication failures are credited. Any nonrefundable processor charges must be explained. Disputes, reversals and fee credits share an auditable ledger to avoid duplicate refunds.
- These marketplace fees do not modify the separate approved $5 per three-calendar-month business Page subscription or activate that billing. Creative Pages stay free. Do not require a paid business Page solely to sell art; shop eligibility is a separate capability.

Use integer currency minor units, explicit deterministic rounding and versioned fee schedules. Example: a $20 item creates $1.20 percentage revenue and one $0.10 publication charge (if newly published), leaving $18.70 before processing/other seller costs. At $10,000 monthly eligible gross, 6% produces $600 before expenses; it is revenue, not profit or promised personal income. Maintain transparent operating accounts and appropriate owner compensation arrangements outside seller balances. Optional memberships supporting Neonrest itself may later be a distinct offering.

## Payments, accounts and orders

Choose Stripe Connect and PayPal's marketplace platform; Google Pay is a wallet offered through a compatible configured processor, not a third independent processor. Show only payment methods the seller/currency/device/provider can actually accept. Provider marketplace onboarding/approval, verified webhooks, sandbox acceptance and live credentials are launch dependencies. No scraping, personal-payment workaround or forwarding seller funds through ordinary Neonrest checkout. Prefer provider-managed seller accounts/payouts and avoid platform-held balances where feasible; verify actual negative-balance/dispute responsibility before selecting the charge model. Do not call payout delays escrow or promise processor protection not contracted.

One seller per checkout initially. Multiple items from that seller are supported; each seller gets a separate order in any future combined cart. Calculate item/discount/shipping/tax totals on the server from a versioned quote; reserve limited inventory with an expiry, revalidate price/stock/delivery immediately before payment, and use stable idempotency keys. Explicitly state when an order is created awaiting payment; only verified canonical provider success makes it paid and unlocks delivery. Browser returns never grant entitlement. Deduplicate provider event IDs and transitions, verify seller, amount, currency and order binding, tolerate out-of-order webhooks and reconcile missed notifications.

States include awaiting_payment, paid, fulfillment_pending, fulfilled, canceled, partially_refunded, refunded and disputed, with explicit valid transitions and separate payment/fulfillment records. Seller statements itemize gross, shipping, tax, platform/processor costs, adjustments and net. Buyers receive an order-linked receipt and private purchases page; staff access requires permission/fresh auth and audited reasons. Public profiles never reveal addresses or purchase history. Delegate roles distinguish listing edits from shipment access, refunds and payout settings. Payout identity changes/transfers require a separate reviewed ownership workflow.

## Fulfillment by product

Digital: private immutable purchased version with file manifest, hash, size/license and a durable order entitlement; short-lived authenticated download links, no public storage URLs. Listing removal prevents future sales but does not silently revoke existing purchases. Published download availability and shutdown/refund provisions must be accepted before purchase. Malware/copyright response can suspend delivery with clear buyer support and audit evidence. Paid file hosting needs separate capacity/quota design; T29's current ordinary attachment budget is not a marketplace storage allocation.

Physical: seller origin, item weight/dimensions, packed parcel dimensions, combined-shipping rules, handling time and supported domestic services. Buyer sees shipping price before payment. Fulfillment address is visible only to authorized seller roles for that order. Labels, tracking, partial shipments, cancellations, label void/refund requests, delivery exceptions, returns and postage adjustments have separate states; creating a label does not mean a parcel was shipped or delivered. Seller buys postage; Neonrest does not silently advance label funds or expose one seller's wallet to another.

Commissions: accepted written brief and immutable scope, deliverables, license, price, deadline, revision allowance and cancellation/refund terms. Messages and proposals stay order-linked; changed scope requires an explicit accepted amendment, not a listing edit affecting an existing order. Begin with fixed-price single-stage work; milestones are later work after payment/acceptance design. Never auto-charge scope increases.

Memberships: monthly and annual tiers, member posts, downloads and early access. Show interval, renewal amount/date, tax and included benefits before authorization. Cancel stops renewal, preserving access through paid period; failed payments follow a disclosed grace/recovery rule. Tier changes must show proration and next charge; do not silently rebill. Digital purchases remain distinct from membership access. Initial tiers exclude recurring physical rewards until recurring fulfillment is implemented. Provider migration requires fresh customer authorization where needed, never a silent transfer of payment credentials.

## Shipping provider choice and Pirate Ship compatibility

Primary integrated provider: Shippo for Platforms, subject to marketplace terms/pricing and approval. Support seller onboarding, rate quotes, labels, tracked status and returns using provider-supported APIs. Seller-specific credentials/subaccounts are private, encrypted/configured outside public source, and revocable. Verify webhook signatures and order/seller/carrier binding. Pricing/fees and responsibility for label adjustments must be agreed before live labels. Keep a provider adapter so external shipping remains supported; EasyPost is a possible later adapter, not a launch dependency.

Pirate Ship remains an equal external fulfillment option. It has no public API; do not promise automatic label purchase or account synchronization. Provide an explicitly selected, seller-authorized UTF-8 CSV of unshipped paid physical orders, one row per intended parcel. Before export, show the included orders and an address-sharing notice. No scheduled transmission to Pirate Ship: the seller downloads and chooses to upload it there.

CSV columns: Order Reference, Shipment Reference, Recipient, Company, Address 1, Address 2, City, State, ZIP, Country, Weight Ounces, Length Inches, Width Inches, Height Inches. Use stable opaque references; no account IDs, birth dates, order contents, private messages or recipient email by default. Field mapping is performed in Pirate Ship on first import; this is spreadsheet compatibility, not a claimed official integration. All postal codes and identifiers are text. Quote CSV safely and guard spreadsheet formula injection without changing postal/address meanings. Reject control characters, preserve Unicode/leading zeros and test the round trip in Excel/Pirate Ship before enabling exports. Unknown package data remains blank or requires seller input; never fabricate weight/dimensions. Export only the current seller's authorized orders in requested state; deny another seller's IDs even if guessed.

Tracking import maps seller-authorized Order Reference + Shipment Reference to Carrier + Tracking Number (+ optional Ship Date). Offer column mapping for Pirate Ship's actual exported headings; preserve reference passthrough in the export/import rehearsal. Parse with bounded file/row limits, show a dry-run preview, reject formula cells, conflicting tracking and cross-seller references, deduplicate repeated rows, and require confirmation before applying. Unmatched rows are reported, never assigned by recipient name/address alone. CSV fields cannot set paid/refunded/delivered status. Tracking updates do not send duplicate customer notices. Manual carrier/tracking entry remains available.

## Support and rollout

Buyer/seller order messages first, then an accessible Neonrest case process with evidence, response deadlines, escalation and decisions. Payment processors decide their own chargebacks; Neonrest still handles marketplace enforcement, delivery issues and refund workflows. Define return addresses/disclosure, lost parcel claims, digital delivery failures and seller disappearance before accepting money. Preserve only necessary private records under a documented retention/access policy; do not expand automatic account erasure.

Build stages: (1) catalog/drafts and server-side fee/quote/order ledger with no live payments; (2) sandbox physical/digital orders, Stripe/PayPal adapters, Google Pay capability, Shippo and Pirate Ship CSV; (3) verified launch for eligible sellers after tax/support/provider/capacity acceptance; (4) commissions; (5) memberships. International selling, combined multi-seller checkout and additional processors follow measured demand.

Acceptance must cover cross-seller/address/file privacy, role revocation, inventory races, duplicate/out-of-order notifications, partial refunds and disputes, malformed CSV/formulas/leading zeros, Pirate Ship reference round trip, Shippo label/void/adjustment failures, canceled subscriptions and entitlement expiry, paid-file revocation rules, reduced-motion/keyboard/mobile/day-night UI, capacity/backup restore and exact-source rollout. No real charges, payouts, labels or customer address transmission during tests.

## References checked during decision discussion

- Shippo platforms: https://goshippo.com/shippo-for-platforms
- Shippo marketplace/API pricing: https://goshippo.com/pricing/api (merchant free tier is not assumed to cover Neonrest).
- Pirate Ship API limitation: https://support.pirateship.com/en/articles/2309246-does-pirate-ship-have-an-api
- Pirate Ship spreadsheet import: https://support.pirateship.com/en/articles/1068428-how-do-i-upload-address-spreadsheets-into-pirate-ship
- Pirate Ship spreadsheet passthrough: https://www.pirateship.com/integrations/spreadsheets
- Stripe Connect pricing: https://stripe.com/connect/pricing
- PayPal marketplace overview: https://developer.paypal.com/platforms/overview

Reference pricing/capabilities must be rechecked before contracting or enabling live services. No provider agreement was accepted by this specification.
