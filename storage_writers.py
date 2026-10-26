"""Bounded in-memory encoding and durable, all-output upload admission.

No Flask imports, database setup, automatic expiry or deletion of old media.
"""
import io
import os
from pathlib import Path


class OutputTooLarge(ValueError):
    pass


class BoundedBuffer(io.BytesIO):
    def __init__(self, maximum):
        super().__init__()
        if type(maximum) is not int or maximum <= 0:
            raise ValueError('Positive output bound required.')
        self.maximum = maximum

    def write(self, data):
        if self.tell() + len(data) > self.maximum:
            raise OutputTooLarge('The processed attachment is too large.')
        return super().write(data)

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.tell()+offset if whence == 1 else len(self.getbuffer())+offset
        if not 0 <= position <= self.maximum:
            raise OutputTooLarge('Output position exceeds its bound.')
        return super().seek(offset, whence)


def encode(image, maximum, format, **options):
    with BoundedBuffer(maximum) as output:
        image.save(output, format=format, **options)
        return output.getvalue()


def charged(size):
    # Reserve filesystem allocation as well as logical payload, with slack for
    # filesystems whose first allocation is larger than a 4 KiB block.
    return max(8192, ((size+4095)//4096)*4096)


def write_outputs(outputs, ledger=None, owner=None, key_prefix='', headroom=None):
    """Admit ALL derivatives before creating the first file; use unique names.

    Each output is (trusted path, bounded immutable bytes). A failed batch only
    removes files created by that batch. If cleanup cannot prove zero retained
    files, its durable reservation remains fully charged for operator review.
    """
    outputs = [(Path(path), data) for path, data in outputs]
    if not outputs or any(type(data) is not bytes for _, data in outputs):
        raise ValueError('A nonempty encoded output batch is required.')
    paths = [path.absolute() for path, _ in outputs]
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate output path.')
    if any(path.is_symlink() or path.exists() or any(p.is_symlink() for p in path.parents) for path in paths):
        raise ValueError('New media requires unique nonsymlink paths.')
    maximum = sum(charged(len(data)) for _, data in outputs)
    token = None
    if ledger:
        # Headroom must be checked by the caller under its cross-app admission
        # lock, before reservation. This callback may not create output files.
        if headroom:
            headroom(maximum)
        token = ledger.reserve(owner, maximum)
        try:
            ledger.mark_started(token)
        except BaseException:
            # A failed/uncertain commit must never release a possibly-started
            # reservation. Reconciliation decides its state after a restart.
            raise
    created = []
    try:
        for path, (_, data) in zip(paths, outputs):
            # Exclusive creation prevents a collision from replacing old media.
            # Files are private until the caller attaches their references.
            descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            created.append(path)
            try:
                stream = os.fdopen(descriptor, 'wb')
            except BaseException:
                os.close(descriptor)
                raise
            with stream as destination:
                os.chmod(path, 0o600)
                destination.write(data)
                destination.flush()
                os.fsync(destination.fileno())
        manifest = []
        for path in created:
            info = path.stat()
            size = max(info.st_size, getattr(info, 'st_blocks', 0)*512)
            manifest.append((key_prefix+'/'+path.name, owner, size))
        if ledger:
            ledger.settle(token, manifest)
        return paths
    except BaseException:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        # A certain, complete cleanup can reconcile this reservation immediately.
        # Database or cleanup failures leave its original durable charge intact.
        if ledger and not any(path.exists() or path.is_symlink() for path in paths):
            try:
                ledger.settle(token, [])
            except Exception:
                pass
        raise
