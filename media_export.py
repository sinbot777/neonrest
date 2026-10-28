"""Bounded owner-upload archive. No public files or retained ZIPs are created."""
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import zipfile

MAX_SOURCE = 64 * 1024 * 1024
MAX_ARCHIVE = 72 * 1024 * 1024
MAX_FILES = 2000

class ExportUnavailable(Exception):
    pass

class LimitedArchive(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_ARCHIVE:
            raise ExportUnavailable('The export exceeds the archive size limit. Contact support for a reviewed export.')
        return super().write(data)

@contextmanager
def open_regular(root, relative):
    """Walk every component using dirfds; never follow a symlink."""
    root = Path(root).absolute()
    if not isinstance(relative,str) or len(relative)>500 or any(ord(c)<32 for c in relative):
        raise OSError(errno.EPERM, 'Unsafe export path')
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(p in ('..', '.') for p in parts) or '\\' in relative:
        raise OSError(errno.EPERM, 'Unsafe export path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.parts[1:] + parts[:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = new
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, 'rb') as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise OSError(errno.EPERM, 'Not a regular export file')
            yield file
    finally:
        os.close(fd)


def build_archive(account, candidates, max_source=MAX_SOURCE):
    """Candidates are private (root, relative, category) tuples, pre-authorized.

    Archive names never contain storage keys, paths or user-controlled filenames.
    Missing/unsafe items get generic manifest reasons without leaking paths.
    """
    if len(candidates) > MAX_FILES:
        raise ExportUnavailable('Too many files for one export. Contact support for a reviewed export.')
    output = LimitedArchive(); manifest = []; seen = {}; used = 0
    try:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
            archive.writestr('account.json', json.dumps(account, ensure_ascii=False, indent=2))
            for root, relative, category in candidates:
                item = {'category': category}
                try:
                    with open_regular(root, relative) as source:
                        before = os.fstat(source.fileno()); identity = (before.st_dev, before.st_ino)
                        if identity in seen:
                            item.update(status='included', file=seen[identity], duplicate=True); manifest.append(item); continue
                        if before.st_size < 0 or used + before.st_size > max_source:
                            raise ExportUnavailable('Your uploaded files exceed the 64 MiB export limit. Contact support for a reviewed export.')
                        suffix = Path(relative).suffix.lower()
                        if len(suffix) > 10 or not suffix[1:].isalnum(): suffix = '.bin'
                        name = 'media/' + str(len(seen)+1).zfill(5) + suffix
                        digest = hashlib.sha256(); size = 0
                        with archive.open(name, 'w') as target:
                            while True:
                                chunk = source.read(65536)
                                if not chunk: break
                                size += len(chunk)
                                if used + size > max_source or size > before.st_size:
                                    raise ExportUnavailable('An upload changed during export. Please retry.')
                                digest.update(chunk); target.write(chunk)
                        after = os.fstat(source.fileno())
                        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or size != before.st_size:
                            raise ExportUnavailable('An upload changed during export. Please retry.')
                        used += size; seen[identity] = name
                        item.update(status='included', file=name, bytes=size, sha256=digest.hexdigest())
                except FileNotFoundError:
                    item.update(status='missing', reason='An attributed upload is no longer available.')
                except OSError:
                    item.update(status='unavailable', reason='An attributed upload could not be safely read.')
                manifest.append(item)
            summary = {'version':1, 'source_bytes':used, 'files':manifest,
                       'scope':'Existing files attributed to your uploads. Legacy files with unknown uploaders need support review; remote embeds and deleted originals cannot be reconstructed.'}
            archive.writestr('manifest.json', json.dumps(summary, ensure_ascii=False, indent=2))
            archive.writestr('README.txt', 'PRIVATE ACCOUNT EXPORT\nThis download can contain sensitive private documents. Store it securely.\naccount.json contains your account data; manifest.json lists included or unavailable uploads.\nFiles use generated names. Other people\'s uploads, staff additions and remote embeds are excluded.\nNo copy is retained by this export feature. No new rights to reuse uploaded material are granted.\n')
        output.seek(0); return output
    except BaseException:
        output.close(); raise


def owner_candidates(app, db, uid, cfg):
    """Read committed uploader attribution; never infer from current destination owners."""
    environment = app.config['STORAGE_ENVIRONMENT']
    roots = {environment+'-uploads':Path(app.static_folder)/'uploads',
             environment+'-media':Path(app.instance_path)/'media',
             environment+'-icons':Path(app.instance_path)/'circle_icons',
             environment+'-covers':Path(app.instance_path)/'circle_covers'}
    candidates = []
    ledger = sqlite3.connect('file:'+str(Path(cfg['ledger']).absolute())+'?mode=ro', uri=True)
    try:
        rows = ledger.execute('SELECT object_key FROM upload_objects WHERE owner=? ORDER BY object_key LIMIT ?',
                              (environment+':user:'+str(uid), MAX_FILES+1)).fetchall()
        for (key,) in rows:
            namespace, separator, relative = key.partition('/')
            if not separator or namespace not in roots:
                raise ExportUnavailable('An upload attribution needs review. Contact support.')
            candidates.append((roots[namespace], relative, 'uploaded attachment or artwork'))
    finally: ledger.close()
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='family_consent_documents'").fetchone()
    if exists:
        from .family_consent import folder
        from types import SimpleNamespace
        directory = folder(SimpleNamespace(app=app))
        for row in db.execute('SELECT storage_key FROM family_consent_documents WHERE parent_id=? ORDER BY id LIMIT ?', (uid,MAX_FILES+1)):
            candidates.append((directory, row[0], 'personally submitted private document'))
    return candidates


def download(app, db, uid, account):
    """Called only by existing authenticated fresh-auth + CSRF export endpoint."""
    from flask import abort, send_file
    from .storage_uploads import policy
    cfg = policy()
    if cfg is None or cfg.get('ready') is False:
        abort(503, description='Media export is unavailable until upload attribution is configured. Your JSON export remains available.')
    # Same cross-environment lock as upload writers: one export globally, no file
    # replacement while the ledger snapshot and uploaded bytes are being read.
    lock_path = Path(cfg['ledger']).with_suffix('.upload-lock')
    with lock_path.open('a+b') as lock:
        os.chmod(lock_path,0o600)
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: abort(503,description='An upload or export is busy. Please retry shortly.')
        try: output = build_archive(account, owner_candidates(app,db,uid,cfg))
        except ExportUnavailable as error: abort(413,description=str(error))
        except (OSError, sqlite3.Error): abort(503,description='Upload attribution could not be verified. Please retry; your files are unchanged.')
    response = send_file(output,mimetype='application/zip',as_attachment=True,download_name='neonrest-data-and-uploads.zip',conditional=False,etag=False,max_age=0)
    response.headers.update({'Cache-Control':'private, no-store','Pragma':'no-cache','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"sandbox; default-src 'none'"})
    response.call_on_close(output.close)
    return response
