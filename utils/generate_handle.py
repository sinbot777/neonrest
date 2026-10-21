import random
import string

def generate_random_handle(db, prefix="@user", max_attempts=10):
    for _ in range(max_attempts):
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        candidate = f"{prefix}{suffix}"
        exists = db.execute('SELECT 1 FROM users WHERE handle = ?', (candidate,)).fetchone()
        if not exists:
            return candidate
    return f"{prefix}{random.randint(10000, 99999)}"
