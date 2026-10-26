"""Flask adapter for storage admission. Limits require explicit private setup."""
import errno
from contextlib import contextmanager
from contextvars import ContextVar
import json
import fcntl
import os
import sqlite3
from pathlib import Path
from flask import Request, abort, current_app, redirect, render_template, request, session, url_for
from .storage_reservations import connect, Limits, QuotaExceeded, ReservationConflict
from .storage_writers import encode as encode_image, write_outputs, OutputTooLarge


def owner_key():
    uid = session.get('user_id')
    if type(uid) is not int or uid <= 0:
        abort(401)
    environment = current_app.config.get('STORAGE_ENVIRONMENT')
    if environment not in ('production', 'sandbox'):
        raise RuntimeError('Explicit storage environment required.')
    return environment+':user:'+str(uid)


def policy():
    # Provisioned deployment configuration, not an editable request parameter.
    value = current_app.config.get('STORAGE_POLICY')
    if value is None:
        return None
    if not isinstance(value, dict) or not value.get('ledger') or not value.get('account_root'):
        raise RuntimeError('Incomplete storage policy.')
    Limits(value['per_owner'], value['aggregate'])
    if type(value.get('provider_quota')) is not int or type(value.get('headroom')) is not int or not 0 < value['headroom'] < value['provider_quota']:
        raise RuntimeError('Provider quota and headroom required.')
    return value


def allocated_tree(root, limit=100000):
    """Count unique physical allocations including directories and symlinks.

    Symlinks are counted but never traversed. An unreadable or incomplete scan
    fails admission; no filenames or contents enter the account-facing result.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise OSError(errno.EIO, 'Storage inventory root unavailable.')
    seen = set(); total = 0; visited = 0
    def count(path):
        nonlocal total, visited
        visited += 1
        if visited > limit:
            raise OSError(errno.EIO, 'Storage inventory is incomplete.')
        info = path.lstat(); key = (info.st_dev, info.st_ino)
        if key not in seen:
            seen.add(key); total += max(info.st_size, getattr(info,'st_blocks',0)*512)
    count(root)
    def failed(error):
        raise error
    for directory, folders, files in os.walk(root, followlinks=False, onerror=failed):
        for name in folders[:]:
            path = Path(directory)/name; count(path)
            if path.is_symlink():folders.remove(name)
        for name in files:count(Path(directory)/name)
    return total


_batch = ContextVar('neonrest_upload_batch', default=None)


@contextmanager
def batch():
    if _batch.get() is not None:
        raise RuntimeError('Nested upload batches are not supported.')
    pending=[];marker=_batch.set(pending)
    try:
        yield
    finally:
        _batch.reset(marker)
    # Reaching here means all input validation and encoding succeeded.
    if pending:
        categories={category for _,category in pending}
        if len(categories)!=1:raise ValueError('An upload batch requires one storage category.')
        write([item for outputs,_ in pending for item in outputs],pending[0][1])


def upload_busy():
    from .resource_errors import response_for
    abort(response_for('upload_busy'))


def write(outputs, category):
    if category not in ('media','avatars','legacy_posts','circle_icons','circle_covers'):
        raise ValueError('Unknown upload category.')
    outputs=list(outputs)
    pending = _batch.get()
    if pending is not None:
        pending.append((list(outputs),category))
        return [Path(path) for path,_ in outputs]
    cfg = policy()
    if cfg is None:
        return write_outputs(outputs)
    if cfg.get('ready') is False:
        upload_busy()
    who = owner_key(); ledger = None
    # Both environments share this lock and ledger. Permission/CSRF checks in
    # the owning route still precede every call to this adapter.
    lock_path = Path(cfg['ledger']).with_suffix('.upload-lock')
    with lock_path.open('a+b') as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            upload_busy()
        try:
            ledger = connect(cfg['ledger'], Limits(cfg['per_owner'],cfg['aggregate']))
            def headroom(maximum):
                try:
                    measured = allocated_tree(cfg['account_root'])
                except OSError:
                    upload_busy()
                # Include in-flight reservations conservatively even if some
                # outputs are already counted by the physical scan.
                pending = ledger.db.execute("SELECT COALESCE(SUM(reserved),0) FROM upload_reservations WHERE state IN ('reserved','writing')").fetchone()[0]
                if measured+pending+maximum+cfg['headroom'] > cfg['provider_quota']:
                    raise OSError(getattr(errno,'EDQUOT',errno.ENOSPC), 'Provider storage headroom unavailable.')
            names={'media':'media','avatars':'uploads/avatars','legacy_posts':'uploads/posts','circle_icons':'icons','circle_covers':'covers'}
            return write_outputs(outputs, ledger, who, who.split(':user:')[0]+'-'+names[category], headroom)
        except QuotaExceeded:
            abort(413, description='This upload exceeds the available attachment allowance. Your existing files are unchanged; keep your text before returning.')
        except sqlite3.Error as error:
            from .resource_errors import failure_kind
            if failure_kind(error) is not None:raise
            upload_busy()
        except ReservationConflict:
            upload_busy()
        finally:
            if ledger:ledger.db.close()


def image(path, picture, maximum, format, category, **options):
    try:
        data = encode_image(picture, maximum, format, **options)
    except OutputTooLarge:
        abort(413, description='The processed image is too large. Choose a smaller image.')
    return write([(Path(path),data)],category)


def usage(staff=False):
    cfg = policy()
    if cfg is None:return {'enabled':False}
    ledger = connect(cfg['ledger'],Limits(cfg['per_owner'],cfg['aggregate']))
    try:
        who = None if staff else owner_key()
        ledger.db.execute('BEGIN')
        result = {'enabled':True,'used':ledger.usage(who),'limit':cfg['aggregate'] if staff else cfg['per_owner']}
        if staff:
            result['pending'] = ledger.db.execute("SELECT COUNT(*) FROM upload_reservations WHERE state IN ('reserved','writing')").fetchone()[0]
            result['unattributed'] = ledger.db.execute("SELECT COALESCE(SUM(bytes),0) FROM upload_objects WHERE owner='unattributed'").fetchone()[0]
        return result
    finally:ledger.db.close()


class MemoryUploadRequest(Request):
    # Existing 26 MiB total request limit remains authoritative. Parsing does
    # not spool unaccounted incoming attachment bytes onto the hosting disk.
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        from .storage_writers import BoundedBuffer
        return BoundedBuffer(26*1024*1024)


def register(app, core):
    @app.errorhandler(413)
    def upload_limit_response(error):
        from .resource_errors import response_for
        return response_for('attachment_limit')

    app.request_class = MemoryUploadRequest
    app.config.setdefault('MAX_FORM_PARTS', 100)
    environment = 'sandbox' if Path(app.root_path).name == 'neonrest_sandbox' else 'production'
    app.config.setdefault('STORAGE_ENVIRONMENT', environment)
    path = Path(os.environ.get('NEONREST_STORAGE_POLICY', '/home/sinbot/private/storage-policy.json'))
    expected_db=Path('/home/sinbot/db')/('neonrest_sandbox.db' if environment=='sandbox' else 'neonrest.db')
    expected_source=Path('/home/sinbot')/('neonrest_sandbox' if environment=='sandbox' else 'neonrest')
    # Sandbox retains Flask's legacy default instance directory. Match the
    # deployed source and database rather than assuming an instance location.
    deployed=(Path(app.config.get('DATABASE','')).absolute()==expected_db and Path(app.root_path).absolute()==expected_source)
    # A disposable database/instance must never inherit the live accounting
    # ledger, including when regression suites run after activation.
    if deployed and path.is_file():
        if path.stat().st_mode & 0o077:
            raise RuntimeError('Storage policy must be owner-only.')
        app.config.setdefault('STORAGE_POLICY', json.loads(path.read_text()))
    @app.get('/account/storage')
    def account_storage_usage():
        if not core.get_logged_in_user():return redirect(url_for('login'))
        response = current_app.make_response(render_template('storage_usage.html',storage=usage(),staff=False,can_manage=core.has_staff_permission(core.get_db(),session.get('user_id'),'manage_roles')))
        response.headers['Cache-Control']='private, no-store'
        return response

    @app.get('/manage/storage')
    def staff_storage_usage():
        core.require_staff_permission('manage_roles')
        if not app.extensions['community_auth_helpers']['fresh']():
            return redirect(url_for('community_reauth',next=request.path))
        response = current_app.make_response(render_template('storage_usage.html',storage=usage(True),staff=True))
        response.headers['Cache-Control']='private, no-store'
        return response
