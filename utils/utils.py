# utils/utils.py  – helper for Base‑62 IDs and handle generation
import random, string
from flask import session

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def encode_base62(n):
    if n == 0:
        return ALPHABET[0]
    s = ''
    while n:
        n, r = divmod(n, 62)
        s = ALPHABET[r] + s
    return s

def generate_random_handle(length=5):
    adjectives = ['cozy','bright','quiet','soft','weird','slow','warm','neon','dreamy']
    nouns      = ['beanbag','mixtape','zine','vibe','light','tape','loop','glow']
    base   = f"{random.choice(adjectives)}-{random.choice(nouns)}"
    suffix = ''.join(random.choices(string.digits, k=length))
    return f"@{base}-{suffix}"

def generate_unique_handle(db):
    while True:
        handle = generate_random_handle()
        if not db.execute('SELECT 1 FROM users WHERE handle=?',(handle,)).fetchone():
            return handle

def get_reserved_prefixes(db):
    rows = db.execute("SELECT prefix FROM id_prefixes WHERE reserved=1").fetchall()
    return {r['prefix'] for r in rows}

def generate_prefixed_id(db, raw_id: int, prefix: str | None = None):
    while True:
        base62 = encode_base62(raw_id)
        base62 = base62.rjust(8, 'A')  # Pad with 'A' to ensure 8-character length

        if len(base62) == 8 and not base62.startswith('0'):
            break
        raw_id += 1  # Try the next ID if too short or starts with '0'

    if prefix:
        row = db.execute('SELECT reserved FROM id_prefixes WHERE prefix = ?', (prefix,)).fetchone()
        if not row:
            raise ValueError(f"Unknown prefix: {prefix}")
        if row['reserved'] and not session.get('is_mod'):
            raise PermissionError("Reserved prefix use blocked")
        return f"{prefix}{base62}"

    for p in get_reserved_prefixes(db):
        if base62.startswith(p):
            raise ValueError(f"Base62 {base62} collides with reserved {p}")

    return base62




def decode_prefixed_id(prefixed_id: str) -> int:
    for i,c in enumerate(prefixed_id):
        if c in ALPHABET:
            base62_part = prefixed_id[i:]; break
    else: raise ValueError("No Base62 segment found")
    n = 0
    for ch in base62_part: n = n*62 + ALPHABET.index(ch)
    return n

def build_comment_tree(comments):
    """Recursively build a threaded comment tree from flat comment rows."""
    comment_map = {c['id']: dict(c, replies=[]) for c in comments}
    root_comments = []

    for c in comments:
        parent_id = c['parent_comment_id']
        if parent_id and parent_id in comment_map:
            comment_map[parent_id]['replies'].append(comment_map[c['id']])
        else:
            root_comments.append(comment_map[c['id']])
    return root_comments
