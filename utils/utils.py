import random
import string

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
