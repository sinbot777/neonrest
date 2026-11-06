"""USD double-entry journal foundation. No provider calls or Flask integration.

Call initialize explicitly on a dedicated connection. Each post owns its transaction;
callers must not wrap it in another transaction. Internal test settlement uses the
locked composition writer within its own transaction. Amounts are integer cents. Positive
entries are debits and negative entries are credits. Corrections are new journals.
"""
import hashlib
import json
import sqlite3


class LedgerError(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_ledger_accounts (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL CHECK(environment IN ('test','live')),
    owner TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('asset','liability','income','expense','equity')),
    currency TEXT NOT NULL CHECK(currency='USD'),
    UNIQUE(id, environment)
);
CREATE TABLE IF NOT EXISTS marketplace_ledger_journals (
    id INTEGER PRIMARY KEY,
    environment TEXT NOT NULL CHECK(environment IN ('test','live')),
    request_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    event_ref TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    posted INTEGER NOT NULL DEFAULT 0 CHECK(posted IN (0,1)),
    UNIQUE(environment, request_key),
    UNIQUE(id, environment)
);
CREATE TABLE IF NOT EXISTS marketplace_ledger_entries (
    journal_id INTEGER NOT NULL,
    environment TEXT NOT NULL,
    account_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents != 0
        AND amount_cents BETWEEN -100000000 AND 100000000),
    PRIMARY KEY(journal_id, account_id),
    FOREIGN KEY(journal_id, environment) REFERENCES marketplace_ledger_journals(id, environment),
    FOREIGN KEY(account_id, environment) REFERENCES marketplace_ledger_accounts(id, environment)
);
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_journal_insert
BEFORE INSERT ON marketplace_ledger_journals WHEN NEW.posted != 0
BEGIN SELECT RAISE(ABORT,'journal must start open'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_journal_seal
BEFORE UPDATE ON marketplace_ledger_journals
BEGIN
    SELECT CASE WHEN OLD.posted != 0 OR NEW.posted != 1
      OR NEW.id != OLD.id OR NEW.environment != OLD.environment
      OR NEW.request_key != OLD.request_key OR NEW.payload_hash != OLD.payload_hash
      OR NEW.event_ref != OLD.event_ref OR NEW.created_at != OLD.created_at
      THEN RAISE(ABORT,'journal is immutable') END;
    SELECT CASE WHEN (SELECT COUNT(*) FROM marketplace_ledger_entries WHERE journal_id=OLD.id) < 2
      OR (SELECT COALESCE(SUM(amount_cents),0) FROM marketplace_ledger_entries WHERE journal_id=OLD.id) != 0
      THEN RAISE(ABORT,'journal must balance') END;
END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_journal_delete
BEFORE DELETE ON marketplace_ledger_journals
BEGIN SELECT RAISE(ABORT,'journal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_entry_insert
BEFORE INSERT ON marketplace_ledger_entries
WHEN COALESCE((SELECT posted FROM marketplace_ledger_journals WHERE id=NEW.journal_id),1) != 0
BEGIN SELECT RAISE(ABORT,'journal is sealed'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_entry_update BEFORE UPDATE ON marketplace_ledger_entries
BEGIN SELECT RAISE(ABORT,'entry is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_entry_delete BEFORE DELETE ON marketplace_ledger_entries
BEGIN SELECT RAISE(ABORT,'entry is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_account_update BEFORE UPDATE ON marketplace_ledger_accounts
BEGIN SELECT RAISE(ABORT,'account is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_ledger_account_delete BEFORE DELETE ON marketplace_ledger_accounts
BEGIN SELECT RAISE(ABORT,'account is immutable'); END;
"""


def initialize(db):
    if db.in_transaction:
        raise LedgerError('initialize outside a transaction')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise LedgerError('invalid identifier')
    return value


def environment(value):
    if value not in ('test', 'live'):
        raise LedgerError('invalid environment')
    return value


def create_account(db, account_id, env, owner, kind):
    """Trusted provisioning only; owner is an opaque reference, never buyer PII."""
    values = (label(account_id), environment(env), label(owner), kind, 'USD')
    if kind not in ('asset', 'liability', 'income', 'expense', 'equity'):
        raise LedgerError('invalid account kind')
    if db.in_transaction:
        raise LedgerError('dedicated connection required')
    with db:
        existing = db.execute('SELECT id,environment,owner,kind,currency FROM marketplace_ledger_accounts WHERE id=?', (account_id,)).fetchone()
        if existing is not None:
            if tuple(existing) != values:
                raise LedgerError('account conflicts with existing identity')
            return
        db.execute('INSERT INTO marketplace_ledger_accounts VALUES (?,?,?,?,?)', values)


def post(db, env, request_key, event_ref, entries, now):
    """Atomically append an already-authorized accounting event, not mark an order paid.

    The future provider adapter must authenticate and reconcile events first. Replay
    returns the original journal; conflicting reuse of a key fails without writing.
    """
    if db.in_transaction:
        raise LedgerError('dedicated connection required')
    if db.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise LedgerError('foreign keys must be enabled on this connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        result = _post_locked(db, env, request_key, event_ref, entries, now)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def _post_locked(db, env, request_key, event_ref, entries, now):
    """Internal composition writer; the caller owns the entire transaction."""
    if not db.in_transaction or db.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise LedgerError('foreign-key-enabled transaction required')
    environment(env)
    label(request_key)
    label(event_ref)
    if type(now) is not int or now < 0:
        raise LedgerError('invalid time')
    if not isinstance(entries, (list, tuple)) or not 2 <= len(entries) <= 100:
        raise LedgerError('expected 2–100 entries')
    normalized = []
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise LedgerError('invalid entry')
        account, amount = entry
        label(account)
        if type(amount) is not int or not 0 < abs(amount) <= 100_000_000:
            raise LedgerError('invalid cents')
        normalized.append((account, amount))
    normalized.sort()
    if len({a for a, _ in normalized}) != len(normalized) or sum(n for _, n in normalized):
        raise LedgerError('entries must be distinct and balance')
    digest = hashlib.sha256(json.dumps([env, event_ref, normalized], separators=(',', ':')).encode()).hexdigest()
    old = db.execute('SELECT id,payload_hash,posted FROM marketplace_ledger_journals WHERE environment=? AND request_key=?', (env, request_key)).fetchone()
    if old:
        if old[1] != digest or old[2] != 1:
            raise LedgerError('idempotency conflict')
        return old[0]
    cursor = db.execute('INSERT INTO marketplace_ledger_journals (environment,request_key,payload_hash,event_ref,created_at) VALUES (?,?,?,?,?)', (env, request_key, digest, event_ref, now))
    journal_id = cursor.lastrowid
    db.executemany('INSERT INTO marketplace_ledger_entries VALUES (?,?,?,?)', [(journal_id, env, a, n) for a, n in normalized])
    db.execute('UPDATE marketplace_ledger_journals SET posted=1 WHERE id=?', (journal_id,))
    return journal_id


def balances(db, env):
    environment(env)
    return dict(db.execute('''SELECT e.account_id,SUM(e.amount_cents)
        FROM marketplace_ledger_entries e JOIN marketplace_ledger_journals j ON j.id=e.journal_id
        WHERE j.environment=? AND j.posted=1 GROUP BY e.account_id''', (env,)))
