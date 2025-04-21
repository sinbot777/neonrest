import random
import string
from flask import g

def generate_unique_handle(base='@user'):
    db = g.db
    while True:
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        handle = f"{base}{suffix}"
        exists = db.execute('SELECT 1 FROM users WHERE handle = ?', (handle,)).fetchone()
        if not exists:
            return handle
