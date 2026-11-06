"""Inactive test-mode seller-account and Stripe event reconciliation foundation.

No HTTP routes, provider SDK/network client, payable checkout, stock consumption,
journal posting, entitlement or paid-order transition. Configured server adapters
own provider calls; webhook receipt verification itself uses real HMAC checks.
No request form may supply an adapter, account observation or verified flag.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import uuid

if __package__:
    from . import marketplace_checkout as checkout
    from . import marketplace_inventory as inventory
else:
    import marketplace_checkout as checkout
    import marketplace_inventory as inventory


class PaymentError(ValueError):
    pass


def ref(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value, re.ASCII):
        raise PaymentError('invalid provider reference')
    return value


@dataclass(frozen=True)
class Scope:
    provider: str
    platform: str
    environment: str = 'test'

    def __post_init__(self):
        if self.provider not in ('stripe', 'paypal') or self.environment != 'test':
            raise PaymentError('only test provider scopes are enabled')
        ref(self.platform)


@dataclass(frozen=True)
class AccountObservation:
    """Returned only by the configured server onboarding/account resolver.

    The resolver must retrieve the provider account using platform credentials and
    bind the onboarding reference to the server-created request; it cannot echo
    merchant IDs or capability/ownership claims from a browser return URL.
    """
    scope: Scope
    onboarding_ref: str
    account_ref: str
    owner_id: int
    charges_enabled: bool
    payouts_enabled: bool


SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_payment_onboarding (
    id TEXT PRIMARY KEY, environment TEXT NOT NULL CHECK(environment='test'),
    provider TEXT NOT NULL CHECK(provider IN ('stripe','paypal')),platform_ref TEXT NOT NULL,
    seller_ref TEXT NOT NULL REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
    request_key TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','completed')),account_id TEXT REFERENCES marketplace_payment_accounts(id),
    UNIQUE(environment,owner_id,request_key),
    CHECK(expires_at>created_at),CHECK((state='pending' AND account_id IS NULL) OR (state='completed' AND account_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS marketplace_payment_accounts (
    id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
    provider TEXT NOT NULL CHECK(provider IN ('stripe','paypal')),platform_ref TEXT NOT NULL,
    account_ref TEXT NOT NULL,owner_id INTEGER NOT NULL REFERENCES users(id),
    charges_enabled INTEGER NOT NULL CHECK(charges_enabled IN (0,1)),
    payouts_enabled INTEGER NOT NULL CHECK(payouts_enabled IN (0,1)),observed_at INTEGER NOT NULL,
    UNIQUE(environment,provider,platform_ref,account_ref),
    UNIQUE(id,environment,provider,owner_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_payment_account_identity
BEFORE UPDATE ON marketplace_payment_accounts
WHEN NEW.id!=OLD.id OR NEW.environment!=OLD.environment OR NEW.provider!=OLD.provider
 OR NEW.platform_ref!=OLD.platform_ref OR NEW.account_ref!=OLD.account_ref OR NEW.owner_id!=OLD.owner_id
BEGIN SELECT RAISE(ABORT,'payment account identity is immutable'); END;
CREATE TABLE IF NOT EXISTS marketplace_payment_shop_links (
    environment TEXT NOT NULL CHECK(environment='test'),seller_ref TEXT NOT NULL REFERENCES seller_shops(page_id),
    provider TEXT NOT NULL,owner_id INTEGER NOT NULL,account_id TEXT NOT NULL,
    PRIMARY KEY(environment,seller_ref,provider),
    FOREIGN KEY(account_id,environment,provider,owner_id) REFERENCES marketplace_payment_accounts(id,environment,provider,owner_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_payment_link_update BEFORE UPDATE ON marketplace_payment_shop_links
BEGIN SELECT RAISE(ABORT,'payment account relinking requires support review'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_link_insert BEFORE INSERT ON marketplace_payment_shop_links
WHEN NOT EXISTS (SELECT 1 FROM seller_shops s WHERE s.page_id=NEW.seller_ref AND s.owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT,'shop/payment owner mismatch'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_onboarding_insert
BEFORE INSERT ON marketplace_payment_onboarding WHEN NEW.state!='pending'
BEGIN SELECT RAISE(ABORT,'onboarding must start pending'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_onboarding_update
BEFORE UPDATE ON marketplace_payment_onboarding
WHEN OLD.state!='pending' OR NEW.state!='completed' OR NEW.id!=OLD.id OR NEW.environment!=OLD.environment
 OR NEW.provider!=OLD.provider OR NEW.platform_ref!=OLD.platform_ref OR NEW.seller_ref!=OLD.seller_ref
 OR NEW.owner_id!=OLD.owner_id OR NEW.request_key!=OLD.request_key OR NEW.created_at!=OLD.created_at OR NEW.expires_at!=OLD.expires_at
 OR NOT EXISTS (SELECT 1 FROM marketplace_payment_accounts a JOIN marketplace_payment_shop_links l ON l.account_id=a.id
   WHERE a.id=NEW.account_id AND a.environment=NEW.environment AND a.provider=NEW.provider AND a.platform_ref=NEW.platform_ref
   AND a.owner_id=NEW.owner_id AND l.seller_ref=NEW.seller_ref AND l.owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT,'onboarding binding is immutable'); END;
CREATE TABLE IF NOT EXISTS marketplace_payment_test_attempts (
    id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
    order_id TEXT NOT NULL REFERENCES marketplace_checkout_orders(id),account_id TEXT NOT NULL REFERENCES marketplace_payment_accounts(id),
    payment_ref TEXT NOT NULL,expected_amount_cents INTEGER NOT NULL CHECK(expected_amount_cents BETWEEN 0 AND 100000000),
    currency TEXT NOT NULL CHECK(currency='USD'),
    observed_status TEXT NOT NULL CHECK(observed_status IN ('tracking','pending','failed','canceled','succeeded')),
    created_at INTEGER NOT NULL,observed_at INTEGER,
    UNIQUE(account_id,payment_ref),UNIQUE(order_id,account_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_payment_attempt_identity
BEFORE UPDATE ON marketplace_payment_test_attempts
WHEN NEW.id!=OLD.id OR NEW.environment!=OLD.environment OR NEW.order_id!=OLD.order_id OR NEW.account_id!=OLD.account_id
 OR NEW.payment_ref!=OLD.payment_ref OR NEW.expected_amount_cents!=OLD.expected_amount_cents
 OR NEW.currency!=OLD.currency OR NEW.created_at!=OLD.created_at
 OR (OLD.observed_status IN ('succeeded','canceled') AND NEW.observed_status!=OLD.observed_status)
BEGIN SELECT RAISE(ABORT,'payment expectation is immutable'); END;
CREATE TABLE IF NOT EXISTS marketplace_payment_events (
    id INTEGER PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),provider TEXT NOT NULL CHECK(provider='stripe'),
    platform_ref TEXT NOT NULL,event_ref TEXT NOT NULL,account_ref TEXT NOT NULL,event_type TEXT NOT NULL,
    payment_ref TEXT NOT NULL,event_created INTEGER NOT NULL,body_hash TEXT NOT NULL,fingerprint TEXT NOT NULL,
    received_at INTEGER NOT NULL,checked_at INTEGER,
    outcome TEXT NOT NULL CHECK(outcome IN ('received','retry','ignored','needs_review','observed_test')),
    reason TEXT NOT NULL,attempt_id TEXT REFERENCES marketplace_payment_test_attempts(id),
    UNIQUE(environment,provider,platform_ref,event_ref)
);
CREATE TRIGGER IF NOT EXISTS marketplace_payment_event_identity
BEFORE UPDATE ON marketplace_payment_events
WHEN NEW.id!=OLD.id OR NEW.environment!=OLD.environment OR NEW.provider!=OLD.provider
 OR NEW.platform_ref!=OLD.platform_ref OR NEW.event_ref!=OLD.event_ref OR NEW.account_ref!=OLD.account_ref
 OR NEW.event_type!=OLD.event_type OR NEW.payment_ref!=OLD.payment_ref OR NEW.event_created!=OLD.event_created
 OR NEW.body_hash!=OLD.body_hash OR NEW.fingerprint!=OLD.fingerprint OR NEW.received_at!=OLD.received_at
BEGIN SELECT RAISE(ABORT,'event receipt is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_event_delete BEFORE DELETE ON marketplace_payment_events
BEGIN SELECT RAISE(ABORT,'event receipt is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_attempt_delete BEFORE DELETE ON marketplace_payment_test_attempts
BEGIN SELECT RAISE(ABORT,'payment expectation is retained'); END;
CREATE TABLE IF NOT EXISTS marketplace_payment_quote_links (
    attempt_id TEXT PRIMARY KEY REFERENCES marketplace_payment_test_attempts(id),
    quote_id TEXT NOT NULL REFERENCES marketplace_checkout_quote_acceptances(quote_id),expires_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS marketplace_payment_quote_link_insert BEFORE INSERT ON marketplace_payment_quote_links
WHEN NOT EXISTS (SELECT 1 FROM marketplace_payment_test_attempts a
 JOIN marketplace_checkout_quote_acceptances c ON c.quote_id=NEW.quote_id
 JOIN marketplace_checkout_quotes q ON q.id=c.quote_id
 WHERE a.id=NEW.attempt_id AND a.order_id=q.order_id AND c.order_id=q.order_id
 AND c.buyer_id=q.buyer_id AND a.environment=q.environment AND NEW.expires_at=q.expires_at
 AND a.created_at>=c.accepted_at AND a.created_at<q.expires_at)
BEGIN SELECT RAISE(ABORT,'invalid accepted quote/payment binding'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_quote_link_update BEFORE UPDATE ON marketplace_payment_quote_links
BEGIN SELECT RAISE(ABORT,'payment quote binding is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_quote_link_delete BEFORE DELETE ON marketplace_payment_quote_links
BEGIN SELECT RAISE(ABORT,'payment quote binding is retained'); END;
CREATE INDEX IF NOT EXISTS marketplace_payment_events_retry
ON marketplace_payment_events(environment,outcome,received_at,id);
"""


def initialize(db):
    if db.in_transaction:
        raise PaymentError('dedicated connection required')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
    if __package__:
        from . import marketplace_payment_jobs as jobs
    else:
        import marketplace_payment_jobs as jobs
    jobs.initialize(db)



def _owner(db, uid, shop_id, policy):
    checkout.actor(policy, db, uid)
    shop = checkout.shop_row(db, shop_id)
    if shop['owner_id'] != uid or not policy.owner(db, uid, shop):
        raise PaymentError('shop owner permission required')
    return shop


def begin_onboarding(db, uid, shop_id, scope, request_key, now, policy=checkout.NeonrestPolicy):
    """Create a bound request only; does not create a provider account or URL."""
    if not isinstance(scope, Scope):
        raise PaymentError('configured provider scope required')
    ref(request_key)
    inventory.clock(now)
    with inventory.transaction(db):
        _owner(db, uid, shop_id, policy)
        old = db.execute('SELECT * FROM marketplace_payment_onboarding WHERE environment=? AND owner_id=? AND request_key=?', (scope.environment, uid, request_key)).fetchone()
        if old:
            if (old['seller_ref'], old['provider'], old['platform_ref']) != (shop_id, scope.provider, scope.platform):
                raise PaymentError('onboarding idempotency conflict')
            return old['id']
        request = uuid.uuid4().hex
        db.execute('INSERT INTO marketplace_payment_onboarding VALUES (?,?,?,?,?,?,?,?,?,?,NULL)',
            (request, scope.environment, scope.provider, scope.platform, shop_id, uid, request_key, now, now+900, 'pending'))
        return request


def complete_onboarding(db, uid, request_id, adapter, now, policy=checkout.NeonrestPolicy):
    """Resolve a server-owned request through an authenticated provider adapter.

    Provider account creation/consent and its server-created association are separate.
    The resolver is configured code, not a user-selectable callback or verified flag;
    marketplace_provider_api now supplies a test-key authenticated read adapter.
    """
    inventory.clock(now)
    if db.in_transaction:
        raise PaymentError('dedicated connection required')
    request = db.execute('SELECT * FROM marketplace_payment_onboarding WHERE id=? AND owner_id=?', (request_id, uid)).fetchone()
    if not request:
        raise PaymentError('onboarding unavailable')
    _owner(db, uid, request['seller_ref'], policy)
    scope = Scope(request['provider'], request['platform_ref'], request['environment'])
    if adapter.scope != scope:
        raise PaymentError('provider scope mismatch')
    if request['state'] == 'completed':
        return request['account_id']
    if request['expires_at'] <= now:
        raise PaymentError('onboarding expired')
    # Never hold a SQLite write lock across the provider lookup.
    observation = adapter.resolve_onboarding(request_id)
    if not isinstance(observation, AccountObservation) or observation.scope != scope or observation.onboarding_ref != request_id or type(observation.owner_id) is not int or observation.owner_id != uid:
        raise PaymentError('provider onboarding binding mismatch')
    ref(observation.account_ref)
    if type(observation.charges_enabled) is not bool or type(observation.payouts_enabled) is not bool:
        raise PaymentError('invalid provider capabilities')
    with inventory.transaction(db):
        _owner(db, uid, request['seller_ref'], policy)
        current = db.execute('SELECT * FROM marketplace_payment_onboarding WHERE id=?', (request_id,)).fetchone()
        if current['state'] == 'completed':
            return current['account_id']
        old = db.execute('SELECT * FROM marketplace_payment_accounts WHERE environment=? AND provider=? AND platform_ref=? AND account_ref=?',
            (scope.environment, scope.provider, scope.platform, observation.account_ref)).fetchone()
        if old and old['owner_id'] != uid:
            raise PaymentError('payment account belongs to another owner')
        account = old['id'] if old else uuid.uuid4().hex
        if not old:
            db.execute('INSERT INTO marketplace_payment_accounts VALUES (?,?,?,?,?,?,?,?,?)',
                (account, scope.environment, scope.provider, scope.platform, observation.account_ref, uid, observation.charges_enabled, observation.payouts_enabled, now))
        else:
            if old['observed_at'] > now:
                raise PaymentError('stale account observation')
            db.execute('UPDATE marketplace_payment_accounts SET charges_enabled=?,payouts_enabled=?,observed_at=? WHERE id=?',
                (observation.charges_enabled, observation.payouts_enabled, now, account))
        link = db.execute('SELECT account_id,owner_id FROM marketplace_payment_shop_links WHERE environment=? AND seller_ref=? AND provider=?',
            (scope.environment, request['seller_ref'], scope.provider)).fetchone()
        if link and (link['account_id'] != account or link['owner_id'] != uid):
            raise PaymentError('payment account relinking requires support review')
        if not link:
            db.execute('INSERT INTO marketplace_payment_shop_links VALUES (?,?,?,?,?)', (scope.environment, request['seller_ref'], scope.provider, uid, account))
        db.execute("UPDATE marketplace_payment_onboarding SET state='completed',account_id=? WHERE id=?", (account, request_id))
        return account


def refresh_account(db, account_id, adapter, now):
    """Internal capability refresh using configured authenticated account lookup."""
    inventory.clock(now)
    if db.in_transaction:
        raise PaymentError('dedicated connection required')
    account = db.execute('SELECT * FROM marketplace_payment_accounts WHERE id=?', (account_id,)).fetchone()
    if not account or adapter.scope != Scope(account['provider'], account['platform_ref'], account['environment']):
        raise PaymentError('provider scope mismatch')
    observation = adapter.resolve_account(account['account_ref'])
    if not isinstance(observation, AccountObservation) or observation.scope != adapter.scope or observation.account_ref != account['account_ref'] or type(observation.owner_id) is not int or observation.owner_id != account['owner_id']:
        raise PaymentError('provider account binding mismatch')
    if type(observation.charges_enabled) is not bool or type(observation.payouts_enabled) is not bool:
        raise PaymentError('invalid provider capabilities')
    with inventory.transaction(db):
        current = db.execute('SELECT observed_at FROM marketplace_payment_accounts WHERE id=?', (account_id,)).fetchone()
        if current['observed_at'] > now:
            raise PaymentError('stale account observation')
        db.execute('UPDATE marketplace_payment_accounts SET charges_enabled=?,payouts_enabled=?,observed_at=? WHERE id=?',
            (observation.charges_enabled, observation.payouts_enabled, now, account_id))


def track_test_payment(db, uid, order_id, account_id, payment_ref, now, policy=checkout.NeonrestPolicy):
    """Track a synthetic provider object against the rehearsal's item subtotal.

    This is deliberately not a payable amount/authorization or provider creation.
    A future real attempt must require an immutable final shipping/tax quote.
    """
    with inventory.transaction(db):
        return _track_test_payment_locked(db, uid, order_id, account_id, payment_ref, now, policy)


def _track_test_payment_locked(db, uid, order_id, account_id, payment_ref, now, policy, quote_row=None):
    """Internal shared writer; caller owns BEGIN IMMEDIATE."""
    if not db.in_transaction:
        raise PaymentError('transaction required')
    ref(payment_ref)
    inventory.clock(now)
    checkout.actor(policy, db, uid)
    order = db.execute("SELECT * FROM marketplace_checkout_orders WHERE id=? AND environment='test' AND buyer_id=?", (order_id, uid)).fetchone()
    account = db.execute('SELECT * FROM marketplace_payment_accounts WHERE id=?', (account_id,)).fetchone()
    if not order or not account or account['environment'] != 'test':
        raise PaymentError('test order/account unavailable')
    _owner(db, order['seller_owner_id'], order['seller_ref'], policy)
    link = db.execute("SELECT 1 FROM marketplace_payment_shop_links WHERE environment='test' AND seller_ref=? AND account_id=? AND owner_id=?", (order['seller_ref'], account_id, order['seller_owner_id'])).fetchone()
    if not link or account['owner_id'] != order['seller_owner_id'] or not account['charges_enabled'] or not account['payouts_enabled']:
        raise PaymentError('payment account unavailable')
    old = db.execute('SELECT * FROM marketplace_payment_test_attempts WHERE order_id=? AND account_id=?', (order_id, account_id)).fetchone()
    if old:
        link=db.execute('SELECT quote_id FROM marketplace_payment_quote_links WHERE attempt_id=?',(old['id'],)).fetchone()
        if old['payment_ref'] != payment_ref or (quote_row is None and link) or (quote_row is not None and (not link or link['quote_id']!=quote_row['id'])):
            raise PaymentError('payment reference conflict')
        return old['id']
    if order['state'] != 'awaiting_payment' or order['expires_at'] <= now:
        raise PaymentError('reservation no longer active')
    snapshot = json.loads(order['snapshot'])
    if snapshot.get('test_only') is not True or snapshot.get('payment_enabled') is not False:
        raise PaymentError('only nonpayable rehearsal orders are accepted')
    attempt = uuid.uuid4().hex
    amount=snapshot['subtotal_cents'] if quote_row is None else json.loads(quote_row['snapshot'])['total_cents']
    db.execute('INSERT INTO marketplace_payment_test_attempts VALUES (?,?,?,?,?,?,?,\'tracking\',?,NULL)',
        (attempt, 'test', order_id, account_id, payment_ref, amount, snapshot['currency'], now))
    if quote_row is not None:
        db.execute('INSERT INTO marketplace_payment_quote_links VALUES (?,?,?)',(attempt,quote_row['id'],quote_row['expires_at']))
    return attempt


def track_quoted_test_payment(db,uid,quote_id,account_id,payment_ref,location_resolver,now,policy=checkout.NeonrestPolicy):
    """Bind a synthetic test payment to a complete explicitly accepted quote."""
    if __package__:
        from . import marketplace_quotes as quotes
    else:
        import marketplace_quotes as quotes
    result=quotes.get_quote(db,uid,quote_id,location_resolver,now,policy)
    location=quotes.Location(**result['snapshot']['location'])
    with inventory.transaction(db):
        quotes._assert_local_location(location_resolver,uid,result['snapshot']['location']['seller_ref'],location)
        fresh=quotes._fresh_quote(db,uid,quote_id,location,now,policy)
        if not db.execute('SELECT 1 FROM marketplace_checkout_quote_acceptances WHERE quote_id=? AND buyer_id=? AND order_id=?',
                (quote_id,uid,fresh['order_id'])).fetchone():
            raise PaymentError('explicit quote acceptance required')
        return _track_test_payment_locked(db,uid,fresh['order_id'],account_id,payment_ref,now,policy,fresh)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PaymentError('duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise PaymentError('invalid JSON constant')


class StripeTestPaymentReader:
    """Canonical read adapter for durable workers; no signing secret required."""
    TYPES = {'payment_intent.succeeded','payment_intent.payment_failed','payment_intent.canceled','payment_intent.processing'}
    def __init__(self,platform,fetch_payment):
        self.scope=Scope('stripe',platform)
        if not callable(fetch_payment):
            raise PaymentError('configured canonical payment resolver required')
        self._fetch=fetch_payment

    def canonical(self, account_ref, payment_ref):
        payment = self._fetch(account_ref, payment_ref)
        if not isinstance(payment, dict) or payment.get('id') != payment_ref or payment.get('object') != 'payment_intent' or payment.get('livemode') is not False:
            raise PaymentError('canonical payment scope mismatch')
        status = payment.get('status')
        states = {'succeeded':'succeeded','canceled':'canceled','processing':'pending','requires_payment_method':'failed','requires_confirmation':'pending','requires_action':'pending','requires_capture':'pending'}
        if type(status) is not str or status not in states:
            raise PaymentError('unknown canonical payment status')
        amount = payment.get('amount_received') if status == 'succeeded' else payment.get('amount')
        if type(amount) is not int or not 0 <= amount <= 100_000_000:
            raise PaymentError('invalid canonical payment amount')
        metadata = payment.get('metadata')
        if not isinstance(metadata, dict):
            raise PaymentError('canonical order binding missing')
        quote_id=metadata.get('neonrest_quote')
        if quote_id is not None:
            ref(quote_id)
        return dict(order=ref(metadata.get('neonrest_order')),quote=quote_id,amount=amount,currency=payment.get('currency'),status=states[status])


class StripeTestWebhookAdapter(StripeTestPaymentReader):
    """Stripe v1 connected-account snapshot events only, test mode only.

    fetch_payment(account_ref, payment_ref) must retrieve canonical PaymentIntent
    state through the configured platform's test API using that connected-account
    context. marketplace_provider_api.StripeTestAPI supplies an optional credentialed
    read adapter; network use is never automatic. Direct-charge fixtures do not
    decide the Production charge/responsibility model.
    """
    def __init__(self, platform, signing_secrets, fetch_payment):
        super().__init__(platform,fetch_payment)
        if not isinstance(signing_secrets, (list, tuple)) or not 1 <= len(signing_secrets) <= 3 or any(type(s) is not bytes or not 16 <= len(s) <= 512 for s in signing_secrets):
            raise PaymentError('configured signing secrets required')
        self._secrets = tuple(signing_secrets)

    def verify(self, raw, signature, now):
        inventory.clock(now)
        if type(raw) is not bytes or not 0 < len(raw) <= 1_048_576 or not isinstance(signature, str) or len(signature) > 4096:
            raise PaymentError('invalid webhook payload')
        parts = [p.strip().partition('=') for p in signature.split(',')]
        timestamps = [value for key, sep, value in parts if key == 't' and sep]
        signatures = [value for key, sep, value in parts if key == 'v1' and sep]
        if len(timestamps) != 1 or not re.fullmatch(r'[0-9]{1,12}', timestamps[0]) or not 1 <= len(signatures) <= 10 or any(not re.fullmatch(r'[a-fA-F0-9]{64}', v) for v in signatures):
            raise PaymentError('invalid webhook signature')
        if abs(now - int(timestamps[0])) > 300:
            raise PaymentError('webhook signature expired')
        signed = timestamps[0].encode() + b'.' + raw
        valid = any(hmac.compare_digest(hmac.new(secret, signed, hashlib.sha256).hexdigest(), candidate.lower()) for secret in self._secrets for candidate in signatures)
        if not valid:
            raise PaymentError('invalid webhook signature')
        try:
            event = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_invalid_constant)
        except (UnicodeError, ValueError, RecursionError) as error:
            raise PaymentError('invalid webhook JSON') from error
        if not isinstance(event, dict) or event.get('object') != 'event' or event.get('livemode') is not False:
            raise PaymentError('only test snapshot events are accepted')
        try:
            event_id, account, kind = ref(event['id']), ref(event['account']), ref(event['type'].replace('.', '_'))
            payment = event['data']['object']['id']
            if not isinstance(event['type'], str) or not isinstance(payment, str):
                raise PaymentError('invalid event identity')
            ref(payment)
            created = event['created']
            if type(created) is not int or not 0 <= created <= now + 300:
                raise PaymentError('invalid event time')
        except (KeyError, TypeError, AttributeError) as error:
            raise PaymentError('invalid snapshot event') from error
        identity = [event_id, account, event['type'], payment, created]
        return dict(id=event_id, account=account, kind=event['type'], payment=payment, created=created,
            body_hash=hashlib.sha256(raw).hexdigest(), fingerprint=hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest())



def _receipt_binding_locked(db,adapter,receipt_id):
    receipt=db.execute('SELECT * FROM marketplace_payment_events WHERE id=?',(receipt_id,)).fetchone()
    scope=adapter.scope
    if not receipt or (receipt['environment'],receipt['provider'],receipt['platform_ref'])!=('test','stripe',scope.platform):
        raise PaymentError('receipt/provider scope mismatch')
    account=db.execute("SELECT * FROM marketplace_payment_accounts WHERE environment='test' AND provider='stripe' AND platform_ref=? AND account_ref=?",(scope.platform,receipt['account_ref'])).fetchone()
    attempt=db.execute('SELECT * FROM marketplace_payment_test_attempts WHERE account_id=? AND payment_ref=?',(account['id'],receipt['payment_ref'])).fetchone() if account else None
    early=('ignored','unsupported_event') if receipt['event_type'] not in adapter.TYPES else (('needs_review','unbound_payment') if not attempt else None)
    return receipt,account,attempt,early


def _reconcile_receipt_locked(db,adapter,receipt_id,canonical,outcome,reason,now,policy):
    """Internal writer; retry worker owns the transaction and fencing lease."""
    if not db.in_transaction:
        raise PaymentError('transaction required')
    receipt,account,attempt,early=_receipt_binding_locked(db,adapter,receipt_id)
    if early:
        outcome,reason=early
        db.execute('UPDATE marketplace_payment_events SET outcome=?,reason=?,checked_at=? WHERE id=?',(outcome,reason,now,receipt_id))
        return dict(receipt_id=receipt_id,outcome=outcome,reason=reason)
    order = db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=?', (attempt['order_id'],)).fetchone()
    quote_link=db.execute('SELECT * FROM marketplace_payment_quote_links WHERE attempt_id=?',(attempt['id'],)).fetchone()
    quote_current=True
    if quote_link:
        if __package__:
            from . import marketplace_quotes as quotes
        else:
            import marketplace_quotes as quotes
        try:
            quotes._fresh_order(db,order['buyer_id'],order['id'],now,policy)
        except ValueError:
            quote_current=False
    if canonical:
        try:
            _owner(db, order['seller_owner_id'], order['seller_ref'], policy)
            checkout.actor(policy, db, order['buyer_id'])
            shop = checkout.shop_row(db, order['seller_ref'])
            permitted = policy.visible(db, shop, order['buyer_id'])
        except (ValueError, KeyError):
            permitted = False
        linked = db.execute("SELECT 1 FROM marketplace_payment_shop_links WHERE environment='test' AND seller_ref=? AND owner_id=? AND account_id=?", (order['seller_ref'],order['seller_owner_id'],account['id'])).fetchone()
        if canonical['order'] != order['id'] or canonical['currency'] != 'usd' or canonical['amount'] != attempt['expected_amount_cents']:
            outcome, reason = 'needs_review', 'payment_binding_mismatch'
        elif quote_link and (not quote_current or canonical['quote']!=quote_link['quote_id'] or quote_link['expires_at']<=now):
            outcome, reason = 'needs_review', 'quote_binding_mismatch_or_expired'
        elif not permitted or not linked or account['owner_id'] != order['seller_owner_id'] or not account['charges_enabled'] or not account['payouts_enabled']:
            outcome, reason = 'needs_review', 'seller_or_buyer_unavailable'
        elif order['state'] != 'awaiting_payment' or order['expires_at'] <= now:
            outcome, reason = 'needs_review', 'reservation_no_longer_active'
        elif attempt['observed_status'] in ('succeeded','canceled') and attempt['observed_status'] != canonical['status']:
            outcome, reason = 'needs_review', 'terminal_observation_conflict'
        else:
            outcome, reason = 'observed_test', 'nonpayable_rehearsal_only'
            db.execute('UPDATE marketplace_payment_test_attempts SET observed_status=?,observed_at=? WHERE id=?', (canonical['status'],now,attempt['id']))
    db.execute('UPDATE marketplace_payment_events SET outcome=?,reason=?,checked_at=?,attempt_id=? WHERE id=?', (outcome,reason,now,attempt['id'],receipt_id))
    return {'receipt_id':receipt_id,'outcome':outcome,'reason':reason}


def receive_stripe(db, adapter, raw, signature, now, policy=checkout.NeonrestPolicy, clock=None):
    """Verify -> atomic receipt/job persistence -> leased test reconciliation.

    Errors from a configured network resolver are retryable; raw payloads, API
    error messages, signatures, secrets and customer fields are never persisted.
    No outcome means the order is paid, fulfillable or eligible for downloads.
    """
    if not isinstance(adapter, StripeTestWebhookAdapter):
        raise PaymentError('configured Stripe test adapter required')
    event = adapter.verify(raw, signature, now)
    scope = adapter.scope
    with inventory.transaction(db):
        receipt = db.execute("SELECT * FROM marketplace_payment_events WHERE environment='test' AND provider='stripe' AND platform_ref=? AND event_ref=?", (scope.platform, event['id'])).fetchone()
        if receipt and receipt['fingerprint'] != event['fingerprint']:
            raise PaymentError('event identity conflict')
        if not receipt:
            cursor = db.execute("INSERT INTO marketplace_payment_events (environment,provider,platform_ref,event_ref,account_ref,event_type,payment_ref,event_created,body_hash,fingerprint,received_at,outcome,reason) VALUES ('test','stripe',?,?,?,?,?,?,?,?,?,'received','')",
                (scope.platform,event['id'],event['account'],event['kind'],event['payment'],event['created'],event['body_hash'],event['fingerprint'],now))
            receipt_id = cursor.lastrowid
        else:
            receipt_id = receipt['id']
        if __package__:
            from . import marketplace_payment_jobs as jobs
        else:
            import marketplace_payment_jobs as jobs
        jobs.enqueue_locked(db,receipt_id,now)
    return jobs.process_delivery(db,adapter,receipt_id,now,policy,clock)
