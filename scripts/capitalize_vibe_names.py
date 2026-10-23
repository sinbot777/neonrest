"""Capitalize Vibe display names without changing IDs or theme slugs."""
import argparse
import datetime
import sqlite3
from pathlib import Path

def display_name(name):
    for index, character in enumerate(name):
        if character.isalpha():
            return name[:index] + character.upper() + name[index + 1:]
    return name

def migrate(db):
    changes = [(key, name, display_name(name))
               for key, name in db.execute('SELECT id,name FROM vibes ORDER BY id')
               if name != display_name(name)]
    with db:
        for key, old, new in changes:
            db.execute('UPDATE vibes SET name=? WHERE id=? AND name=?',(new,key,old))
    return changes

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    args=parser.parse_args()
    if not args.database.is_file():
        parser.error('Database must already exist.')
    with sqlite3.connect(args.database) as db:
        backup=args.database.with_name(args.database.name+'.before-vibe-case-'+
                                      datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
        with sqlite3.connect(backup) as snapshot:
            db.backup(snapshot)
        print('Changes:',migrate(db))
        print('Backup:',backup)

