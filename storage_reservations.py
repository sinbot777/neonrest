"""Durable, shared upload admission. Explicit setup; no live activation on import.

Callers must reserve a hard upper bound BEFORE creating any output or temporary
file, mark_started before writing, and settle every retained derivative. Failed
or crashed writers remain charged until an operator reconciles their outputs.
"""
from contextlib import contextmanager
import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path


class QuotaExceeded(Exception):
    """The account or shared media budget cannot admit this allocation."""


class ReservationConflict(Exception):
    """Reservation state or inventory changed; no allocation was authorized."""


@dataclass(frozen=True)
class Limits:
    per_owner: int
    aggregate: int

    def __post_init__(self):
        for amount in (self.per_owner, self.aggregate):
            if type(amount) is not int or not 0 < amount <= 2**62:
                raise ValueError('Configure positive integer byte limits.')


def amount(value):
    if type(value) is not int or not 0 <= value <= 2**62:
        raise ValueError('Expected a nonnegative integer byte count.')
    return value


def label(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError('Expected a bounded opaque inventory key.')
    return value


class Ledger:
    def __init__(self, connection, limits):
        self.db = connection
        self.limits = limits

    def initialize(self):
        if self.db.in_transaction:
            raise ReservationConflict('Setup requires its own connection.')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS upload_reservations (
                token TEXT PRIMARY KEY, owner TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved>=0),
                state TEXT NOT NULL CHECK(state IN ('reserved','writing','settled','released')),
                manifest_hash TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS upload_reservations_owner ON upload_reservations(owner,state);
            CREATE TABLE IF NOT EXISTS upload_objects (
                object_key TEXT PRIMARY KEY, owner TEXT NOT NULL, bytes INTEGER NOT NULL CHECK(bytes>=0),
                reservation TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS upload_objects_owner ON upload_objects(owner);
        ''')

    @contextmanager
    def transaction(self):
        if self.db.in_transaction:
            raise ReservationConflict('Use a separate ledger connection, outside the app transaction.')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def usage(self, owner=None):
        # Caller holds an IMMEDIATE transaction when making admission decisions.
        suffix = ' WHERE owner=?' if owner is not None else ''
        args = (owner,) if owner is not None else ()
        used = self.db.execute('SELECT COALESCE(SUM(bytes),0) FROM upload_objects' + suffix, args).fetchone()[0]
        pending = self.db.execute("SELECT COALESCE(SUM(reserved),0) FROM upload_reservations WHERE state IN ('reserved','writing')" + (' AND owner=?' if owner is not None else ''), args).fetchone()[0]
        return used + pending

    def seed(self, objects):
        """Operator-only initial inventory. Unknown owners still consume aggregate.

        Idempotent only for identical entries; changed sizes/owners fail closed.
        This method never deletes an inventory entry or releases stored bytes.
        """
        entries = self._objects(objects)
        with self.transaction():
            for key, owner, size in entries:
                old = self.db.execute('SELECT owner,bytes FROM upload_objects WHERE object_key=?', (key,)).fetchone()
                if old is not None and tuple(old) != (owner, size):
                    raise ReservationConflict('Inventory entry changed.')
                if old is None:
                    self.db.execute('INSERT INTO upload_objects(object_key,owner,bytes) VALUES(?,?,?)', (key, owner, size))

    @staticmethod
    def _objects(objects):
        entries = [(label(key), label(owner), amount(size)) for key, owner, size in objects]
        if len({entry[0] for entry in entries}) != len(entries):
            raise ValueError('Duplicate inventory key.')
        return sorted(entries)

    def reserve(self, owner, maximum_bytes):
        owner = label(owner)
        cost = amount(maximum_bytes)
        if cost == 0:
            raise ValueError('An upload reservation must be positive.')
        token = secrets.token_hex(24)
        with self.transaction():
            if self.usage(owner) + cost > self.limits.per_owner:
                raise QuotaExceeded('Account upload allowance reached.')
            if self.usage() + cost > self.limits.aggregate:
                raise QuotaExceeded('Shared upload allowance reached.')
            self.db.execute("INSERT INTO upload_reservations(token,owner,reserved,state) VALUES(?,?,?,'reserved')", (token, owner, cost))
        return token

    def mark_started(self, token):
        with self.transaction():
            changed = self.db.execute("UPDATE upload_reservations SET state='writing' WHERE token=? AND state='reserved'", (token,)).rowcount
            if changed != 1:
                raise ReservationConflict('Reservation is not available to start.')

    def release_unwritten(self, token):
        """Only before mark_started; failures after output begins stay charged."""
        with self.transaction():
            changed = self.db.execute("UPDATE upload_reservations SET state='released' WHERE token=? AND state='reserved'", (token,)).rowcount
            if changed != 1:
                raise ReservationConflict('A started allocation requires output reconciliation.')

    def settle(self, token, objects):
        """Register ALL retained outputs after bounded writes have stopped.

        Objects are opaque environment-prefixed keys, not user-provided paths.
        Replaced/deleted app references do not free bytes here. Physical cleanup
        and evidence retention require a separate reviewed maintenance operation.
        """
        entries = self._objects(objects)
        digest = hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()
        with self.transaction():
            row = self.db.execute('SELECT owner,reserved,state,manifest_hash FROM upload_reservations WHERE token=?', (token,)).fetchone()
            if row is None:
                raise ReservationConflict('Unknown reservation.')
            owner, reserved, state, previous = row
            if state == 'settled' and previous == digest:
                return  # Safe retry after a connection failure following commit.
            if state != 'writing' or any(entry[1] != owner for entry in entries):
                raise ReservationConflict('Reservation state or output owner mismatch.')
            if sum(entry[2] for entry in entries) > reserved:
                raise QuotaExceeded('Outputs exceed reservation; retain the charge and stop writes.')
            for key, output_owner, size in entries:
                self.db.execute('INSERT INTO upload_objects(object_key,owner,bytes,reservation) VALUES(?,?,?,?)', (key, output_owner, size, token))
            self.db.execute("UPDATE upload_reservations SET state='settled',manifest_hash=? WHERE token=?", (digest, token))


def connect(path, limits):
    """Open a pre-provisioned private ledger. No implicit DB creation or setup."""
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    db = sqlite3.connect(uri, uri=True, timeout=1)
    return Ledger(db, limits)
