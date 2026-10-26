"""Read-only inventory for quota seeding. Never deletes, imports app, or opens DB.

Ownership must come from reviewed references across BOTH environments. Missing
and ambiguous ownership is explicitly unassigned, never exempt from aggregate.
"""
import os
import stat
from pathlib import Path


def inventory(roots, owners, limit=100000):
    """Return ledger objects and review findings, without following symlinks.

    roots maps stable namespace to a physical directory; overlapping roots are
    rejected. owners maps namespace/relative filename to a set of owner keys.
    Hard links count once and retain every alias in private review details.
    Either unreadable paths or a traversal limit makes seeding unsafe.
    """
    if type(limit) is not int or limit <= 0:
        raise ValueError('Use a positive file limit.')
    configured = []
    for namespace, root in roots.items():
        root = Path(root).absolute()
        if not namespace or '/' in namespace or root.is_symlink() or any(p.is_symlink() for p in root.parents):
            raise ValueError('Use distinct namespaces and physical nonsymlink roots.')
        for _, old in configured:
            if root == old or root in old.parents or old in root.parents:
                raise ValueError('Overlapping roots would make inventory ambiguous.')
        configured.append((namespace, root))
    entries = {}
    findings = []
    visited = 0
    incomplete = False
    for namespace, root in configured:
        if not root.exists():
            findings.append({'kind': 'missing_root', 'key': namespace})
            incomplete = True
            continue
        if not root.is_dir():
            raise ValueError('Inventory roots must be directories.')
        def failed(error):
            nonlocal incomplete
            incomplete = True
            findings.append({'kind': 'unreadable', 'key': namespace})
        for directory, folders, files in os.walk(root, followlinks=False, onerror=failed):
            for name in folders[:]:
                candidate = Path(directory) / name
                if candidate.is_symlink():
                    folders.remove(name)
                    findings.append({'kind': 'symlink', 'key': namespace + '/' + candidate.relative_to(root).as_posix()})
                    incomplete = True
            for name in files:
                visited += 1
                if visited > limit:
                    return {'objects': [], 'findings': findings + [{'kind': 'limit'}], 'incomplete': True, 'safe_to_seed': False}
                candidate = Path(directory) / name
                key = namespace + '/' + candidate.relative_to(root).as_posix()
                try:
                    info = candidate.lstat()
                    if not stat.S_ISREG(info.st_mode):
                        findings.append({'kind': 'nonregular', 'key': key})
                        incomplete = True
                        continue
                    inode = (info.st_dev, info.st_ino)
                    entry = entries.setdefault(inode, {'aliases': [], 'owners': set(), 'logical': info.st_size, 'allocated': getattr(info, 'st_blocks', 0) * 512})
                    if info.st_size != entry['logical']:
                        findings.append({'kind': 'changed_during_scan', 'key': key})
                        incomplete = True
                    entry['aliases'].append(key)
                    entry['owners'].update(owners.get(key, set()))
                except OSError:
                    incomplete = True
                    findings.append({'kind': 'unreadable', 'key': key})
    objects = []
    for entry in entries.values():
        aliases = sorted(entry['aliases'])
        who = entry['owners']
        owner = next(iter(who)) if len(who) == 1 else 'unattributed'
        if len(who) != 1:
            findings.append({'kind': 'unknown_owner' if not who else 'ambiguous_owner', 'key': aliases[0]})
        objects.append({'key': aliases[0], 'owner': owner, 'bytes': max(entry['logical'], entry['allocated']), 'logical_bytes': entry['logical'], 'allocated_bytes': entry['allocated'], 'aliases': aliases})
    return {'objects': sorted(objects, key=lambda item: item['key']), 'findings': findings,
            'incomplete': incomplete, 'safe_to_seed': not incomplete,
            'charged_bytes': sum(item['bytes'] for item in objects)}
