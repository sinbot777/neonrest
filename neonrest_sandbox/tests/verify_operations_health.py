"""T08 checks against disposable source, data and storage; no SMTP sends."""
from pathlib import Path
import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import time

live = Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'))
checks = 0
def check(value, label):
    global checks
    assert value, label
    checks += 1

with tempfile.TemporaryDirectory(prefix='neonrest-operations-') as temp:
    root = Path(temp); stage = root / 'neonrest_sandbox'; stage.mkdir()
    for p in live.glob('*.py'): shutil.copy2(p, stage / p.name)
    for folder in ('templates', 'routes', 'utils'): shutil.copytree(live / folder, stage / folder)
    (stage / 'static').mkdir()
    source = sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro', uri=True)
    before = source.execute('SELECT count(*) FROM users').fetchone()[0]
    dest = sqlite3.connect(root / 'test.db'); source.backup(dest); dest.close()
    os.environ['NEONREST_SANDBOX_DATABASE'] = str(root / 'test.db')
    os.environ['NEONREST_SANDBOX_SECRET_FILE'] = str(root / 'secret')
    sys.path.insert(0, str(root))
    with contextlib.redirect_stdout(io.StringIO()):
        import neonrest_sandbox.app as core
    from neonrest_sandbox import operations_health as ops, community_features as cf
    app = core.app
    app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=True,MAIL_QUEUE_ENABLED=False, SESSION_COOKIE_PATH='/', PROPAGATE_EXCEPTIONS=False,
                      FAMILY_CONSENT_FOLDER=str(root / 'consent'))
    # All scanned test directories are isolated.
    app.instance_path = str(root / 'instance'); Path(app.instance_path).mkdir()
    app.add_url_rule('/isolated-error-check', 'isolated_error_check',
                     lambda: (_ for _ in ()).throw(RuntimeError('private-email@example.invalid secret-token')))
    now = int(time.time())
    with app.app_context():
        db = core.get_db()
        admin = db.execute("INSERT INTO users(handle,email,password_hash,dob,verified) VALUES ('@OperationsAdmin','operations-admin@example.invalid','unused','1998-01-01',1)").lastrowid
        peer = db.execute("INSERT INTO users(handle,email,password_hash,dob,verified) VALUES ('@OperationsPeer','operations-peer@example.invalid','unused','1998-01-01',1)").lastrowid
        db.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'admin')", (admin,))
        db.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?)', (admin, 'JBSWY3DPEHPK3PXP'))
        for uid in (admin, peer):
            db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',
                       (cf.digest('operations-' + str(uid)), uid, now, now, now + 3600, 'isolated-test'))
        db.commit()
    def client(uid):
        c = app.test_client()
        with c.session_transaction() as state:
            state.update(user_id=uid, user_handle='@OperationsAdmin' if uid == admin else '@OperationsPeer',
                         sid='operations-' + str(uid), fresh_at=now, factor_at=now, theme_csrf_token='operations-csrf')
        return c
    owner = client(admin); ordinary = client(peer); guest = app.test_client()
    check(guest.get('/manage/operations').status_code in (401, 403), 'Operations rejects guests')
    check(ordinary.get('/manage/operations').status_code == 403, 'Operations rejects ordinary members')
    response = owner.get('/manage/operations')
    check(response.status_code == 200, 'Staff health dashboard renders')
    check(b'Storage monitoring' in response.data and b'not your hosting account quota' in response.data, 'Storage scope is explicit')
    check('no-store' in response.headers.get('Cache-Control', ''), 'Staff health is not cached')
    check(owner.post('/manage/operations', data={'action': 'backup'}).status_code == 400, 'Backup requires CSRF')
    with owner.session_transaction() as state: state['fresh_at'] = now - 1801
    response = owner.post('/manage/operations', data={'action': 'backup', 'theme_csrf_token': 'operations-csrf'})
    check(response.status_code == 302 and '/reauth' in response.location, 'Backup requires renewed authorization')
    with owner.session_transaction() as state: state['fresh_at'] = now
    with owner.session_transaction() as state: state['factor_at'] = now - 1801
    response = owner.post('/manage/operations', data={'action': 'backup', 'theme_csrf_token': 'operations-csrf'})
    check(response.status_code == 302 and '/reauth' in response.location, 'Backup requires current second factor')
    with owner.session_transaction() as state: state['factor_at'] = now
    check(owner.post('/manage/operations', data={'action': 'unknown', 'theme_csrf_token': 'operations-csrf'}).status_code == 400, 'Unknown action rejected')
    check(owner.post('/manage/operations', data={'action': 'backup', 'theme_csrf_token': 'operations-csrf'}).status_code == 302, 'Verified backup succeeds')
    with app.app_context():
        db = core.get_db(); row = dict(db.execute('SELECT * FROM backup_records ORDER BY id DESC LIMIT 1').fetchone())
        folder = root / 'sandbox_backups'; path = Path(row['path'])
        check(path.stat().st_mode & 0o777 == 0o600, 'Database backup private')
        check(folder.stat().st_mode & 0o777 == 0o700, 'Backup directory private')
        check(row['sha256'] == ops.file_hash(path) and row['verified_at'], 'Backup fingerprint and verification saved')
        check(ops.backup_health(row, folder)['state'] == 'verified', 'Intact backup verifies')
        restored = root / 'restore.db'; shutil.copy2(path, restored)
        restored_db = sqlite3.connect(restored)
        check(restored_db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Disposable database restore healthy')
        check(restored_db.execute('SELECT count(*) FROM users').fetchone()[0] == before + 2, 'Restore preserves users')
        check(restored_db.execute('SELECT count(*) FROM posts').fetchone()[0] == db.execute('SELECT count(*) FROM posts').fetchone()[0], 'Restore preserves posts')
        restored_db.close()
        check(ops.file_hash(restored) == row['sha256'], 'Restored bytes match backup')
        check(ops.backup_health(row, folder, row['verified_at'] + 7 * 86400)['state'] == 'stale', 'Seven-day backup warning')
        check(ops.backup_health(dict(row, sha256=None), folder)['state'] == 'unverified', 'Legacy backup is not falsely verified')
        check(ops.backup_health(None, folder)['state'] == 'none', 'No backup is explicit')
        check(ops.backup_health(dict(row, path=str(root / 'missing.db')), folder)['state'] == 'unsafe', 'Outside backup path rejected')
        check(ops.backup_health(dict(row, path=str(folder / 'missing.db')), folder)['state'] == 'missing', 'Missing backup detected')
        link = folder / 'linked.db'; link.symlink_to(path)
        check(ops.backup_health(dict(row, path=str(link)), folder)['state'] == 'unsafe', 'Backup symlink rejected')
        with path.open('ab') as stream: stream.write(b'changed')
        check(ops.backup_health(row, folder)['state'] == 'changed', 'Changed backup detected')
        shutil.copy2(restored, path)
        class FailedBackup:
            def backup(self, target): raise OSError('private path')
            def rollback(self): pass
        count = len(list(folder.glob('*.db')))
        try: ops.create_backup(FailedBackup(), folder)
        except OSError: pass
        else: raise AssertionError('Expected failure')
        check(len(list(folder.glob('*.db'))) == count and not list(folder.glob('*.partial')), 'Failed backup preserves existing files and removes partial output')
        tree = root / 'tree'; tree.mkdir(); (tree / 'data').write_bytes(b'12345')
        os.link(tree / 'data', tree / 'hardlink')
        check(ops.tree_usage(tree)['bytes'] == 5, 'Hard links counted once per category')
        (tree / 'outside').symlink_to(root / 'test.db')
        usage = ops.tree_usage(tree)
        check(usage['bytes'] == 5 and usage['incomplete'] and usage['skipped'] == 1, 'Symlinks skipped with honest lower-bound warning')
        check(ops.tree_usage(tree, limit=1)['incomplete'], 'Bounded scan reports incomplete')
        check(ops.tree_usage(root / 'absent')['bytes'] == 0, 'Absent optional folder is empty')
        baseline = ops.health(app, db)
        app.config['OPERATIONS_STORAGE_ALERT_BYTES'] = baseline['total_bytes']
        check(ops.health(app, db)['storage_state'] == 'critical', 'Threshold reached warning')
        app.config['OPERATIONS_STORAGE_ALERT_BYTES'] = int(baseline['total_bytes'] / .9)
        check(ops.health(app, db)['storage_state'] == 'warning', 'Eighty percent warning')
        app.config['OPERATIONS_STORAGE_ALERT_BYTES'] = baseline['total_bytes'] * 2
        check(ops.health(app, db)['storage_state'] == 'ok', 'Below threshold healthy')
        media = Path(app.instance_path) / 'media'; media.mkdir()
        post = db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'media health fixture','public')", (peer,)).lastrowid
        db.execute("INSERT INTO post_media(post_id,kind,filename,poster) VALUES (?,'gif','missing.gif','present.png')", (post,))
        db.commit(); (media / 'present.png').write_bytes(b'fixture')
        before_missing = ops.health(app, db)['missing_media']
        (media / 'missing.gif').write_bytes(b'fixture')
        check(ops.health(app, db)['missing_media'] == before_missing - 1, 'Missing referenced media detected and clears on restoration')
    original = ops.create_backup
    def broken_backup(*args): raise OSError('private filesystem details')
    ops.create_backup = broken_backup
    response = owner.post('/manage/operations', data={'action': 'backup', 'theme_csrf_token': 'operations-csrf'}, follow_redirects=True)
    check(response.status_code == 200 and b'backup could not be completed' in response.data, 'Backup failure gives recovery guidance')
    check(b'private filesystem details' not in response.data, 'Backup failure does not expose filesystem details')
    ops.create_backup = original
    response = guest.get('/isolated-error-check?token=private-query')
    check(response.status_code == 500 and b'Something went wrong' in response.data, 'Styled error fallback')
    check(b'private-email' not in response.data and b'secret-token' not in response.data and b'private-query' not in response.data, 'Error page excludes private values')
    check('no-store' in response.headers.get('Cache-Control', ''), 'Error page not cached')
    with app.app_context():
        db = core.get_db(); detail = db.execute("SELECT detail FROM operations_events WHERE kind='error' ORDER BY id DESC LIMIT 1").fetchone()[0]
        check('isolated_error_check' in detail and 'RuntimeError' in detail, 'Staff error has route and type')
        check('private-email' not in detail and 'secret-token' not in detail and 'private-query' not in detail, 'Staff event omits exception message and query')
        check(detail.split(' · ')[0].encode() in response.data, 'Public reference matches private staff record')
        check(ops.health(app, db)['errors_day'] >= 1, 'Recent error count visible')
    check(source.execute('SELECT count(*) FROM users').fetchone()[0] == before, 'Live user count unchanged')
    source.close()
print(f'PASS: {checks} isolated operations health checks; live accounts/files untouched; no email sent')
