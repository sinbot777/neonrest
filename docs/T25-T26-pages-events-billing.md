# T25 page-social and Stripe work; T26 events/calendar

Candidate work, not a declaration of live billing. Creative pages were already deployed separately.

## Page social

Case-insensitive `_handle`/`$handle` discovery and a Pages category in existing search. One-way follows and a separate chronological Followed page updates view linked from Feed. Eligibility, account restrictions, current page state, owner/author age and blocks are rechecked when reading. Follows do not grant private page access. No public follower directory or count is exposed.

Private in-app editor/manager invitations last seven days. Pending invitations grant no rights. Recipients accept after fresh authentication; current contact, consent and block rules are rechecked. Owners can remove delegates/revoke invitations. Ownership transfers require explicit consequence confirmation and the recipient's acceptance, atomically revoke other pending invitations and grant no automatic ongoing access to the previous owner. Business delegation/transfer remains blocked pending a separate billing-ownership policy. No real invitation is sent by deployment or tests.

## Events

Eligible members can create private or age-eligible public events, or private events scoped to current Circle membership. Optional page attribution requires page editing permission. Title/description/location are escaped, times are stored as UTC with a chosen IANA zone, and ambiguous/nonexistent daylight-saving local times require an explicit offset. Revision-checked editing/cancellation, private Going/Interested responses and authenticated iCalendar export are included. Block/age/page and Circle membership restrictions are rechecked on every detail/list/export request. Event reports preserve immutable private snapshots and staff-factor review can hide/restore events. Public Circle visibility never grants access to private Circle events.

## Stripe subscription integration

Approved pricing: USD 500 cents every three calendar months, no setup fee; cancellation stops renewal at period end and preserves paid access. Stripe was selected by the owner. Fixed provider URLs, hosted Checkout, a configured immutable Price ID, owner/fresh-auth/CSRF checks and a stable idempotency key govern checkout. No card details are stored locally. Stripe receives the account contact email only during explicitly accepted checkout.

REST is pinned to API version 2024-06-20. Webhooks verify the raw request signature and five-minute timestamp tolerance, retrieve the canonical event and normalize referenced objects through the pinned API. An exact price/currency/interval/quantity, matching owner/customer/subscription and authoritative paid invoice are required. Processed event IDs are unique. Browser returns never grant entitlement. Failures do not extend paid access; cancellation retains paid access; refund/dispute notifications require review rather than silently extending access. Test invoices never publish live business pages.

Default mode is off. Sandbox live payments are forbidden. Live mode requires environment configuration plus a separate explicit NEONREST_STRIPE_LIVE_CONFIRMED=1 gate. Secrets and provider identifiers are omitted from exports and public source. Account setup, signed test-event delivery and real hosted test checkout must pass before live billing is enabled. No existing user is automatically subscribed or charged. No automatic refund action is implemented; support review remains the refund path.

Private configuration per environment: NEONREST_PRODUCTION_STRIPE_MODE / SECRET_KEY / WEBHOOK_SECRET / PRICE_ID (with the shared STRIPE prefix on each full variable name: NEONREST_PRODUCTION_STRIPE_SECRET_KEY etc.); Sandbox uses NEONREST_SANDBOX_STRIPE_*. Never put keys into GitHub, pages, screenshots or roadmap files.

## Reference audit

Production's 56 original violations comprise 45 post_vibes references to a removed posts_old table, nine comments whose posts are missing and two comments whose parent comments are missing. Forty-four post/Vibe mappings still match current posts. The repair rebuilds only post_vibes to point at current posts, preserving every row, index and trigger and restoring the caller's foreign-key setting. One genuinely orphaned post/Vibe mapping and eleven orphaned comment references remain for reviewed disposition. No comment or mapping is deleted or reassigned. Sandbox has no violations. Back up and rehearse before applying the repair to live data.


Stripe test product created in the existing Neonrest account: Neonrest Business Page (Test), USD $5 every three months. This is test data only; no live product/subscription/charge has been created. Private configuration may also be read from an owner-only (0600) stripe.json in /home/sinbot/private/neonrest_production or /home/sinbot/private/neonrest_sandbox. Never export its contents.
