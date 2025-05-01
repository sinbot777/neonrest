# utils/utils.py
import random
import string
from flask import session

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def encode_base62(n):
    if n == 0:
        return ALPHABET[0]
    s = ''
    while n > 0:
        n, r = divmod(n, 62)
        s = ALPHABET[r] + s
    return s

def generate_random_handle(length=5):
    adjectives = ['cozy', 'bright', 'quiet', 'soft', 'weird', 'slow', 'warm', 'neon', 'dreamy']
    nouns = ['beanbag', 'mixtape', 'zine', 'vibe', 'light', 'tape', 'loop', 'glow']
    base = f"{random.choice(adjectives)}-{random.choice(nouns)}"
    suffix = ''.join(random.choices(string.digits, k=length))
    return f"@{base}-{suffix}"

def generate_unique_handle(db):
    while True:
        handle = generate_random_handle()
        exists = db.execute('SELECT 1 FROM users WHERE handle = ?', (handle,)).fetchone()
        if not exists:
            return handle

def get_reserved_prefixes(db):
    rows = db.execute("SELECT prefix FROM id_prefixes WHERE reserved = 1").fetchall()
    return {row['prefix'] for row in rows}

def generate_prefixed_id(db, raw_id: int, prefix: str = None):
    base62 = encode_base62(raw_id).zfill(8)
    if prefix:
        row = db.execute('SELECT reserved FROM id_prefixes WHERE prefix = ?', (prefix,)).fetchone()
        if not row:
            raise ValueError(f"Unknown prefix: {prefix}")
        if row['reserved'] and not session.get('is_mod'):
            raise PermissionError("Reserved prefix use blocked")
        return f"{prefix}{base62}"
    else:
        reserved = get_reserved_prefixes(db)
        for p in reserved:
            if base62.startswith(p):
                raise ValueError(f"Base62 ID {base62} collides with reserved prefix {p}")
        return base62

def decode_prefixed_id(prefixed_id: str) -> int:
    # Strips leading prefix (e.g., 'MOD') and decodes the rest
    for i, c in enumerate(prefixed_id):
        if c in ALPHABET:
            base62_part = prefixed_id[i:]
            break
    else:
        raise ValueError("No Base62 segment found")

    n = 0
    for char in base62_part:
        n = n * 62 + ALPHABET.index(char)
    return n
