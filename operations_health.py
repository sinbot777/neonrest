"""Private backup validation and scoped, read-only Sandbox health reporting."""
from pathlib import Path
import hashlib
import os
import secrets
import sqlite3
import stat
import time


def initialize(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(backup_records)')}
    for name, declaration in [('sha256', 'TEXT'), ('verified_at', 'INTEGER')]:
        if name not in columns:
            db.execute(f'ALTER TABLE backup_records ADD COLUMN {name} {declaration}')
    db.commit()


def file_hash(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create_backup(db, folder):
    folder = Path(folder)
    if folder.is_symlink():
        raise OSError('Unsafe backup directory')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    name = 'neonrest-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4)
    temporary = folder / (name + '.partial')
    final = folder / (name + '.db')
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        target = sqlite3.connect(temporary)
        try:
            db.backup(target)
            if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('Backup integrity failed')
        finally:
            target.close()
        digest = file_hash(temporary)
        os.replace(temporary, final)
        now = int(time.time())
        db.execute('INSERT INTO backup_records(path,bytes,sha256,verified_at) VALUES (?,?,?,?)',
                   (str(final), final.stat().st_size, digest, now))
        db.commit()
        return final
    except Exception:
        db.rollback()
        # Only this operation's generated files; never existing backups.
        temporary.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise


def backup_health(row, folder, now=None):
    now = int(time.time()) if now is None else now
    result = {'state': 'none', 'age_days': None, 'verified': False}
    if not row:
        return result
    path = Path(row['path']); root = Path(folder)
    if path.is_symlink() or path.parent.resolve() != root.resolve():
        return dict(result, state='unsafe')
    if not path.is_file():
        return dict(result, state='missing')
    if not row['sha256'] or not row['verified_at']:
        return dict(result, state='unverified')
    try:
        if path.stat().st_size != row['bytes'] or file_hash(path) != row['sha256']:
            return dict(result, state='changed')
        connection = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
        try:
            healthy = connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        finally:
            connection.close()
        if not healthy:
            return dict(result, state='corrupt')
    except (OSError, sqlite3.Error):
        return dict(result, state='unreadable')
    age = max(0, (now - row['verified_at']) / 86400)
    return {'state': 'stale' if age >= 7 else 'verified', 'age_days': age, 'verified': True}


def tree_usage(path, limit=100000):
    result = {'bytes': 0, 'allocated_bytes': 0, 'files': 0, 'incomplete': False, 'skipped': 0}
    path = Path(path)
    if path.is_symlink():
        return dict(result, incomplete=True, skipped=1)
    if not path.exists():
        return result
    seen = set(); visited = 0
    def add(p):
        nonlocal visited
        visited += 1
        if visited > limit:
            result['incomplete'] = True
            return False
        try:
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode):
                result['skipped'] += 1; result['incomplete'] = True
            elif stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) not in seen:
                seen.add((info.st_dev, info.st_ino))
                result['bytes'] += info.st_size; result['allocated_bytes'] += getattr(info, 'st_blocks', 0) * 512; result['files'] += 1
        except OSError:
            result['incomplete'] = True
        return True
    if path.is_file():
        add(path); return result
    def failed(error):
        result['incomplete'] = True
    for directory, folders, files in os.walk(path, followlinks=False, onerror=failed):
        for name in folders[:]:
            child = Path(directory) / name
            if child.is_symlink():
                folders.remove(name); result['skipped'] += 1; result['incomplete'] = True
        for name in files:
            if not add(Path(directory) / name):
                return result
    return result



def account_storage(app):
    # A separate home-directory reading: never add overlapping category totals.
    root = Path(app.config.get('OPERATIONS_ACCOUNT_ROOT', Path(app.root_path).parent))
    quota = int(app.config.get('OPERATIONS_ACCOUNT_QUOTA_BYTES', 1024 * 1024 * 1024))
    usage = tree_usage(root)
    measured = usage['allocated_bytes']
    state = 'critical' if quota > 0 and measured >= quota * .9 else 'warning' if quota > 0 and measured >= quota * .8 else 'ok'
    return dict(usage, state=state, quota_bytes=quota, measured_bytes=measured,
                available_upper_bound=max(0, quota-measured) if quota > 0 else None)


def health(app, db, now=None):
    from neonrest_sandbox.retention import storage_roots
    roots = storage_roots(app)
    categories = [('Database', app.config['DATABASE']),
                  ('Avatars and legacy uploads', Path(app.static_folder) / 'uploads'),
                  ('Post media', roots['media']), ('Case evidence', Path(app.instance_path) / 'case-evidence'),
                  ('Consent documents', roots['consent']), ('Database backups', roots['backups'])]
    usage = [dict(tree_usage(path), label=label) for label, path in categories]
    # This is an explicit alert threshold, not a hosting-provider disk quota.
    budget = int(app.config.get('OPERATIONS_STORAGE_ALERT_BYTES', 256 * 1024 * 1024))
    total = sum(item['bytes'] for item in usage)
    storage_state = 'critical' if budget > 0 and total >= budget else 'warning' if budget > 0 and total >= budget * .8 else 'ok'
    backup_row = db.execute('SELECT * FROM backup_records ORDER BY id DESC LIMIT 1').fetchone()
    errors = db.execute("SELECT COUNT(*) FROM operations_events WHERE kind='error' AND created_at>=datetime('now','-1 day')").fetchone()[0]
    failed_mail = db.execute("SELECT COUNT(*) FROM operations_events WHERE kind='email' AND (detail LIKE 'Account email failed%' OR detail LIKE 'Account email dead%' OR detail LIKE 'Account email uncertain%') AND created_at>=datetime('now','-1 day')").fetchone()[0]
    referenced = set()
    for row in db.execute('SELECT filename,poster,loop_filename FROM post_media'):
        referenced.update(name for name in row if name)
    referenced.update(row[0] for row in db.execute('SELECT profile_midi FROM media_settings') if row[0])
    missing_media = sum(1 for name in referenced
                        if Path(name).name != name or (Path(roots['media']) / name).is_symlink()
                        or not (Path(roots['media']) / name).is_file())
    return {'account_storage': account_storage(app), 'usage': usage, 'total_bytes': total, 'alert_bytes': budget, 'storage_state': storage_state,
            'incomplete': any(item['incomplete'] for item in usage), 'backup': backup_health(backup_row, roots['backups'], now),
            'errors_day': errors, 'failed_mail_day': failed_mail, 'missing_media': missing_media}
