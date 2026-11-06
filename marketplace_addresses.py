"""Encrypted, owned, versioned test addresses; no HTTP routes or seller delivery.

Uses the repository's existing cryptography dependency. Keys are explicit server
configuration, never stored with the database. No plaintext fallback, automatic
key creation, external address validation, deletion or third-party transmission.
"""
import hashlib
import json
import re
import uuid
from cryptography.fernet import Fernet,InvalidToken,MultiFernet

if __package__:
    from . import marketplace_checkout as checkout,marketplace_inventory as inventory
    from .marketplace_quotes import Location
else:
    import marketplace_checkout as checkout
    import marketplace_inventory as inventory
    from marketplace_quotes import Location


class AddressError(ValueError):
    pass


STATES=set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())
FIELDS={'recipient':120,'company':120,'line1':120,'line2':120,'city':80,'state':2,'postal_code':10,'country':2}


def normalize(value):
    if not isinstance(value,dict) or set(value)-set(FIELDS):
        raise AddressError('check address fields')
    result={}
    for field,maximum in FIELDS.items():
        text=value.get(field,'')
        if not isinstance(text,str) or len(text)>maximum or any(ord(c)<32 or ord(c)==127 for c in text):
            raise AddressError('check address fields')
        result[field]=text.strip()
    if not all(result[k] for k in ('recipient','line1','city')) or result['country']!='US' or result['state'] not in STATES:
        raise AddressError('a supported US address is required')
    if not re.fullmatch(r'[0-9]{5}(?:-[0-9]{4})?',result['postal_code'],re.ASCII):
        raise AddressError('enter a text ZIP or ZIP+4')
    if len(json.dumps(result,ensure_ascii=False).encode())>8192:
        raise AddressError('address is too large')
    return result


class FernetVault:
    """First key encrypts; all configured keys decrypt during explicit rotation."""
    def __init__(self,keys):
        if not isinstance(keys,(tuple,list)) or not 1<=len(keys)<=5 or any(type(k) is not bytes for k in keys):
            raise AddressError('configured address encryption keys required')
        try:
            self._cipher=MultiFernet([Fernet(k) for k in keys])
        except (ValueError,TypeError):
            raise AddressError('configured address encryption keys required') from None

    def seal(self,envelope):
        raw=json.dumps(envelope,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        if len(raw)>16384:
            raise AddressError('address is too large')
        return self._cipher.encrypt(raw)

    def open(self,token):
        if type(token) is not bytes or len(token)>32768:
            raise AddressError('address unavailable')
        try:
            result=json.loads(self._cipher.decrypt(token))
        except (InvalidToken,ValueError,TypeError,UnicodeError):
            raise AddressError('address unavailable') from None
        if not isinstance(result,dict):
            raise AddressError('address unavailable')
        return result

    def rotate(self,token):
        try:
            return self._cipher.rotate(token)
        except (InvalidToken,TypeError,ValueError):
            raise AddressError('address unavailable') from None


SCHEMA="""
CREATE TABLE IF NOT EXISTS marketplace_address_books (
    id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
    owner_id INTEGER NOT NULL REFERENCES users(id),purpose TEXT NOT NULL CHECK(purpose IN ('destination','origin')),
    shop_id TEXT REFERENCES seller_shops(page_id),request_key TEXT NOT NULL,current_version TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    created_at INTEGER NOT NULL,UNIQUE(environment,owner_id,request_key),
    CHECK((purpose='destination' AND shop_id IS NULL) OR (purpose='origin' AND shop_id IS NOT NULL)),
    FOREIGN KEY(current_version,id) REFERENCES marketplace_address_versions(id,book_id)
);
CREATE TABLE IF NOT EXISTS marketplace_address_versions (
    id TEXT PRIMARY KEY,book_id TEXT NOT NULL REFERENCES marketplace_address_books(id),
    number INTEGER NOT NULL CHECK(number>=0),ciphertext BLOB NOT NULL CHECK(typeof(ciphertext)='blob' AND length(ciphertext)<=32768),
    created_at INTEGER NOT NULL,rotated_at INTEGER NOT NULL,UNIQUE(book_id,number),UNIQUE(id,book_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_address_book_identity BEFORE UPDATE ON marketplace_address_books
WHEN NEW.id!=OLD.id OR NEW.environment!=OLD.environment OR NEW.owner_id!=OLD.owner_id OR NEW.purpose!=OLD.purpose
 OR NEW.shop_id IS NOT OLD.shop_id OR NEW.request_key!=OLD.request_key OR NEW.created_at!=OLD.created_at
 OR NOT ((OLD.current_version IS NULL AND NEW.revision=OLD.revision) OR NEW.revision=OLD.revision+1)
BEGIN SELECT RAISE(ABORT,'address identity/revision is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_address_version_update BEFORE UPDATE ON marketplace_address_versions
WHEN NEW.id!=OLD.id OR NEW.book_id!=OLD.book_id OR NEW.number!=OLD.number OR NEW.created_at!=OLD.created_at OR NEW.rotated_at<OLD.rotated_at
BEGIN SELECT RAISE(ABORT,'address version identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_address_version_delete BEFORE DELETE ON marketplace_address_versions
BEGIN SELECT RAISE(ABORT,'historical address version is retained'); END;
CREATE TABLE IF NOT EXISTS marketplace_shop_origins (
    shop_id TEXT PRIMARY KEY REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
    book_id TEXT NOT NULL REFERENCES marketplace_address_books(id),revision INTEGER NOT NULL DEFAULT 0
);
CREATE TRIGGER IF NOT EXISTS marketplace_shop_origin_insert BEFORE INSERT ON marketplace_shop_origins
WHEN NOT EXISTS (SELECT 1 FROM marketplace_address_books b JOIN seller_shops s ON s.page_id=b.shop_id
 WHERE b.id=NEW.book_id AND b.purpose='origin' AND b.environment='test' AND b.archived=0
 AND b.owner_id=NEW.owner_id AND s.owner_id=NEW.owner_id AND s.page_id=NEW.shop_id)
BEGIN SELECT RAISE(ABORT,'invalid owned shop origin'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_shop_origin_update BEFORE UPDATE ON marketplace_shop_origins
WHEN NEW.shop_id!=OLD.shop_id OR NEW.owner_id!=OLD.owner_id OR NEW.revision!=OLD.revision+1
 OR NOT EXISTS (SELECT 1 FROM marketplace_address_books b JOIN seller_shops s ON s.page_id=b.shop_id
 WHERE b.id=NEW.book_id AND b.purpose='origin' AND b.environment='test' AND b.archived=0
 AND b.owner_id=NEW.owner_id AND s.owner_id=NEW.owner_id AND s.page_id=NEW.shop_id)
BEGIN SELECT RAISE(ABORT,'invalid owned shop origin'); END;
CREATE TABLE IF NOT EXISTS marketplace_address_events (
    id INTEGER PRIMARY KEY,book_id TEXT NOT NULL REFERENCES marketplace_address_books(id),
    version_id TEXT REFERENCES marketplace_address_versions(id),actor_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL CHECK(action IN ('create','edit','view','archive','restore','rotate','set_origin')),created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS marketplace_address_snapshots (
    id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
    buyer_id INTEGER NOT NULL REFERENCES users(id),shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),
    origin_owner_id INTEGER NOT NULL REFERENCES users(id),destination_book TEXT NOT NULL,origin_book TEXT NOT NULL,
    destination_version TEXT NOT NULL,origin_version TEXT NOT NULL,
    FOREIGN KEY(destination_version,destination_book) REFERENCES marketplace_address_versions(id,book_id),
    FOREIGN KEY(origin_version,origin_book) REFERENCES marketplace_address_versions(id,book_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_address_snapshot_update BEFORE UPDATE ON marketplace_address_snapshots
BEGIN SELECT RAISE(ABORT,'address snapshot is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_address_snapshot_delete BEFORE DELETE ON marketplace_address_snapshots
BEGIN SELECT RAISE(ABORT,'address snapshot is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_address_snapshot_insert BEFORE INSERT ON marketplace_address_snapshots
WHEN NOT EXISTS (SELECT 1 FROM marketplace_address_books d JOIN marketplace_address_books o ON o.id=NEW.origin_book
 JOIN seller_shops s ON s.page_id=NEW.shop_id
 WHERE d.id=NEW.destination_book AND d.environment='test' AND o.environment='test'
 AND d.owner_id=NEW.buyer_id AND d.purpose='destination' AND d.archived=0 AND d.current_version=NEW.destination_version
 AND o.owner_id=NEW.origin_owner_id AND o.purpose='origin' AND o.archived=0 AND o.current_version=NEW.origin_version
 AND o.shop_id=NEW.shop_id AND s.owner_id=NEW.origin_owner_id)
BEGIN SELECT RAISE(ABORT,'invalid owned address snapshot'); END;
CREATE INDEX IF NOT EXISTS marketplace_address_owner ON marketplace_address_books(owner_id,archived,purpose,id);
"""


def initialize(db):
    if db.in_transaction:
        raise AddressError('dedicated connection required')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


class AddressStore:
    """Server-only vault service. Regular address reads are owner-only and audited."""
    def __init__(self,db,vault,policy=checkout.NeonrestPolicy):
        if not isinstance(vault,FernetVault):
            raise AddressError('configured encrypted vault required')
        self.db=db;self.vault=vault;self.policy=policy

    def _owned(self,uid,book_id):
        checkout.actor(self.policy,self.db,uid)
        row=self.db.execute("SELECT * FROM marketplace_address_books WHERE id=? AND owner_id=? AND environment='test'",(book_id,uid)).fetchone()
        if not row:
            raise AddressError('address unavailable')
        return row

    def _origin_owner(self,uid,shop_id):
        checkout.actor(self.policy,self.db,uid)
        shop=checkout.shop_row(self.db,shop_id)
        if shop['owner_id']!=uid or not self.policy.owner(self.db,uid,shop):
            raise AddressError('shop owner permission required')
        return shop

    def _envelope(self,book,version,address):
        return dict(schema_version=1,environment='test',book_id=book['id'],version_id=version,
            owner_id=book['owner_id'],purpose=book['purpose'],shop_id=book['shop_id'],address=address)

    def _open(self,book,version_id=None):
        version=self.db.execute('SELECT * FROM marketplace_address_versions WHERE id=? AND book_id=?',
            (version_id or book['current_version'],book['id'])).fetchone()
        if not version:
            raise AddressError('address unavailable')
        envelope=self.vault.open(version['ciphertext'])
        address=normalize(envelope.get('address'))
        if type(envelope.get('owner_id')) is not int or type(envelope.get('schema_version')) is not int or envelope!=self._envelope(book,version['id'],address):
            raise AddressError('address context mismatch')
        return version,address

    def _event(self,uid,book,version,action,now):
        self.db.execute('INSERT INTO marketplace_address_events(book_id,version_id,actor_id,action,created_at) VALUES (?,?,?,?,?)',(book,version,uid,action,now))

    def create(self,uid,purpose,address,request_key,now,shop_id=None):
        inventory.clock(now);inventory.identity('test',request_key)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',request_key,re.ASCII): raise AddressError('opaque request key required')
        if purpose not in ('destination','origin') or (purpose=='destination' and shop_id is not None) or (purpose=='origin' and not shop_id):
            raise AddressError('choose an address purpose')
        normalized=normalize(address)
        with inventory.transaction(self.db):
            checkout.actor(self.policy,self.db,uid)
            if purpose=='origin': self._origin_owner(uid,shop_id)
            old=self.db.execute("SELECT * FROM marketplace_address_books WHERE environment='test' AND owner_id=? AND request_key=?",(uid,request_key)).fetchone()
            if old:
                first=self.db.execute('SELECT id FROM marketplace_address_versions WHERE book_id=? AND number=0',(old['id'],)).fetchone()
                version,value=self._open(old,first[0])
                if old['purpose']!=purpose or old['shop_id']!=shop_id or value!=normalized:
                    raise AddressError('address request conflict')
                return dict(id=old['id'],version=version['id'],revision=0)
            book_id=uuid.uuid4().hex;version_id=uuid.uuid4().hex
            self.db.execute("INSERT INTO marketplace_address_books VALUES (?,'test',?,?,?,?,NULL,0,0,?)",(book_id,uid,purpose,shop_id,request_key,now))
            book=self._owned(uid,book_id)
            token=self.vault.seal(self._envelope(book,version_id,normalized))
            self.db.execute('INSERT INTO marketplace_address_versions VALUES (?,?,0,?,?,?)',(version_id,book_id,token,now,now))
            self.db.execute('UPDATE marketplace_address_books SET current_version=? WHERE id=?',(version_id,book_id))
            self._event(uid,book_id,version_id,'create',now)
            return dict(id=book_id,version=version_id,revision=0)

    def edit(self,uid,book_id,revision,address,now):
        inventory.clock(now)
        if type(revision) is not int or revision<0:
            raise AddressError('reload address before saving')
        normalized=normalize(address)
        with inventory.transaction(self.db):
            book=self._owned(uid,book_id)
            if book['purpose']=='origin': self._origin_owner(uid,book['shop_id'])
            if book['archived']: raise AddressError('restore address before editing')
            if book['revision']!=revision:
                version,current=self._open(book)
                if book['revision']==revision+1 and version['number']==book['revision'] and current==normalized:
                    return dict(id=book_id,version=version['id'],revision=book['revision'])
                raise AddressError('address changed; reload before saving')
            version_id=uuid.uuid4().hex;number=revision+1
            token=self.vault.seal(self._envelope(book,version_id,normalized))
            self.db.execute('INSERT INTO marketplace_address_versions VALUES (?,?,?,?,?,?)',(version_id,book_id,number,token,now,now))
            self.db.execute('UPDATE marketplace_address_books SET current_version=?,revision=revision+1 WHERE id=?',(version_id,book_id))
            self._event(uid,book_id,version_id,'edit',now)
            return dict(id=book_id,version=version_id,revision=number)

    def read(self,uid,book_id,now,version_id=None):
        inventory.clock(now)
        with inventory.transaction(self.db):
            book=self._owned(uid,book_id)
            version,address=self._open(book,version_id)
            self._event(uid,book_id,version['id'],'view',now)
            return dict(id=book_id,version=version['id'],revision=book['revision'],address=address)

    def references(self,uid):
        checkout.actor(self.policy,self.db,uid)
        return [dict(row) for row in self.db.execute("SELECT id,purpose,current_version,revision,archived FROM marketplace_address_books WHERE owner_id=? AND environment='test' ORDER BY id",(uid,))]

    def set_archived(self,uid,book_id,revision,archived,now):
        inventory.clock(now)
        if type(revision) is not int or type(archived) is not bool:
            raise AddressError('check address revision/state')
        with inventory.transaction(self.db):
            book=self._owned(uid,book_id)
            if book['revision']!=revision: raise AddressError('address changed; reload before saving')
            if bool(book['archived'])==archived: return book['revision']
            self.db.execute('UPDATE marketplace_address_books SET archived=?,revision=revision+1 WHERE id=?',(archived,book_id))
            self._event(uid,book_id,book['current_version'],'archive' if archived else 'restore',now)
            return revision+1

    def set_origin(self,uid,shop_id,book_id,now):
        inventory.clock(now)
        with inventory.transaction(self.db):
            self._origin_owner(uid,shop_id)
            book=self._owned(uid,book_id)
            if book['purpose']!='origin' or book['shop_id']!=shop_id or book['archived']:
                raise AddressError('choose an active owned shop origin')
            old=self.db.execute('SELECT * FROM marketplace_shop_origins WHERE shop_id=?',(shop_id,)).fetchone()
            if old and old['owner_id']!=uid: raise AddressError('origin ownership changed; support review required')
            if old and old['book_id']==book_id: return
            self.db.execute('''INSERT INTO marketplace_shop_origins VALUES (?,?,?,0)
                ON CONFLICT(shop_id) DO UPDATE SET book_id=excluded.book_id,revision=revision+1''',(shop_id,uid,book_id))
            self._event(uid,book_id,book['current_version'],'set_origin',now)

    def rotate_version(self,uid,book_id,version_id,now):
        inventory.clock(now)
        with inventory.transaction(self.db):
            book=self._owned(uid,book_id)
            version,_=self._open(book,version_id)
            if now<version['rotated_at']: raise AddressError('stale rotation time')
            token=self.vault.rotate(version['ciphertext'])
            self.db.execute('UPDATE marketplace_address_versions SET ciphertext=?,rotated_at=? WHERE id=?',(token,now,version_id))
            self._event(uid,book_id,version_id,'rotate',now)


class AddressResolver:
    """Server-only location resolver; public result contains opaque references only."""
    def __init__(self,store): self.store=store

    def _pair(self,buyer,seller_ref,destination_ref):
        store=self.store;db=store.db
        destination=store._owned(buyer,destination_ref)
        if destination['purpose']!='destination' or destination['archived']:
            raise AddressError('active destination required')
        shop=checkout.shop_row(db,seller_ref)
        checkout.actor(store.policy,db,shop['owner_id'])
        if not store.policy.visible(db,shop,buyer) or not store.policy.owner(db,shop['owner_id'],shop):
            raise AddressError('shop unavailable')
        selected=db.execute('SELECT * FROM marketplace_shop_origins WHERE shop_id=? AND owner_id=?',(seller_ref,shop['owner_id'])).fetchone()
        if not selected: raise AddressError('seller origin is not configured')
        origin=store._owned(shop['owner_id'],selected['book_id'])
        if origin['purpose']!='origin' or origin['shop_id']!=seller_ref or origin['archived']:
            raise AddressError('active owned seller origin required')
        destination_version,destination_value=store._open(destination)
        origin_version,origin_value=store._open(origin)
        binding=[destination['id'],destination_version['id'],destination['revision'],origin['id'],origin_version['id'],origin['revision'],selected['revision'],shop['owner_id']]
        version=hashlib.sha256(json.dumps(binding,separators=(',',':')).encode()).hexdigest()
        location=Location(buyer,seller_ref,destination_ref,version,origin_value['country'],destination_value['country'])
        return location,origin_value,destination_value

    def resolve_location(self,buyer,seller_ref,destination_ref):
        return self._pair(buyer,seller_ref,destination_ref)[0]

    def assert_current_location(self,buyer,seller_ref,location):
        if self.resolve_location(buyer,seller_ref,location.reference)!=location:
            raise AddressError('address context changed')

    def _save_snapshot(self,buyer,seller_ref,location,native_version):
        db=self.store.db
        if not db.in_transaction: raise AddressError('address snapshot requires transaction')
        actual=self.resolve_location(buyer,seller_ref,location.reference)
        if actual.version!=native_version: raise AddressError('address context changed')
        destination=self.store._owned(buyer,location.reference)
        selected=db.execute('SELECT * FROM marketplace_shop_origins WHERE shop_id=?',(seller_ref,)).fetchone()
        origin=self.store._owned(selected['owner_id'],selected['book_id'])
        values=(location.version,'test',buyer,seller_ref,origin['owner_id'],destination['id'],origin['id'],destination['current_version'],origin['current_version'])
        old=db.execute('SELECT * FROM marketplace_address_snapshots WHERE id=?',(location.version,)).fetchone()
        if old:
            if tuple(old)!=values: raise AddressError('address snapshot conflict')
        else:
            db.execute('INSERT INTO marketplace_address_snapshots VALUES (?,?,?,?,?,?,?,?,?)',values)
        return location.version

    def bind_location_snapshot(self,buyer,seller_ref,location):
        self.assert_current_location(buyer,seller_ref,location)
        return self._save_snapshot(buyer,seller_ref,location,location.version)

    def read_own_snapshot_destination(self,buyer,snapshot_id,now):
        """Owner access to the retained buyer version; never returns seller origin."""
        checkout.actor(self.store.policy,self.store.db,buyer)
        row=self.store.db.execute("SELECT * FROM marketplace_address_snapshots WHERE id=? AND buyer_id=? AND environment='test'",(snapshot_id,buyer)).fetchone()
        if not row: raise AddressError('address snapshot unavailable')
        return self.store.read(buyer,row['destination_book'],now,row['destination_version'])

    def calculation_addresses(self,buyer,seller_ref,destination_ref,expected_version):
        """Private minimum fields for a configured calculator, never a buyer response.

        This method does not transmit anything. External adapters require their own
        disclosed/provider-approved workflow and must not log these values.
        """
        location,origin,destination=self._pair(buyer,seller_ref,destination_ref)
        if location.version!=expected_version: raise AddressError('address context changed')
        fields=('line1','line2','city','state','postal_code','country')
        return dict(location=location,origin={k:origin[k] for k in fields},destination={k:destination[k] for k in fields})
