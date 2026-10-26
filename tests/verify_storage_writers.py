import errno
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage_reservations import Ledger, Limits, QuotaExceeded
from storage_writers import BoundedBuffer, OutputTooLarge, write_outputs


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.db=sqlite3.connect(':memory:');self.ledger=Ledger(self.db,Limits(100000,100000));self.ledger.initialize()
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def output(self,items,**kwargs):
        return write_outputs([(self.root/n,data) for n,data in items],self.ledger,'prod:user:1','prod:media',**kwargs)
    def test_encoding_bound_covers_seek_and_overwrite(self):
        b=BoundedBuffer(4);b.write(b'abcd');b.seek(0);b.write(b'xy');self.assertEqual(b.getvalue(),b'xycd')
        with self.assertRaises(OutputTooLarge):b.write(b'123')
        with self.assertRaises(OutputTooLarge):b.seek(5)
        b.close()
    def test_entire_derivative_batch_admitted_before_first_output(self):
        self.ledger.limits=Limits(8192,8192)
        with self.assertRaises(QuotaExceeded):self.output([('poster',b'1'),('loop',b'2')])
        self.assertEqual(list(self.root.iterdir()),[])
    def test_physical_allocation_and_owner_charge(self):
        self.output([('poster',b'1'),('loop',b'2')])
        physical=sum(max(p.stat().st_size,p.stat().st_blocks*512) for p in self.root.iterdir())
        self.assertEqual(self.ledger.usage('prod:user:1'),physical)
        self.assertEqual(self.ledger.usage('sandbox:user:1'),0)
        self.assertEqual((self.root/'poster').stat().st_mode&0o777,0o600)
    def test_headroom_denial_creates_no_reservation_or_output(self):
        def full(_):raise OSError(errno.ENOSPC,'full')
        with self.assertRaises(OSError):self.output([('x',b'a')],headroom=full)
        self.assertEqual(self.ledger.usage(),0);self.assertEqual(list(self.root.iterdir()),[])
    def test_disk_full_after_first_output_cleans_only_batch(self):
        old=self.root/'old';old.write_bytes(b'KEEP')
        original=os.fsync;calls=[]
        def fail_second(fd):
            calls.append(fd)
            if len(calls)==2:raise OSError(errno.ENOSPC,'full')
            return original(fd)
        with patch('storage_writers.os.fsync',side_effect=fail_second),self.assertRaises(OSError):self.output([('a',b'a'),('b',b'b')])
        self.assertEqual(list(self.root.iterdir()),[old]);self.assertEqual(old.read_bytes(),b'KEEP');self.assertEqual(self.ledger.usage(),0)
    def test_stream_setup_failure_cleans_new_file_and_reservation(self):
        with patch('storage_writers.os.fdopen',side_effect=OSError(errno.EMFILE,'no streams')),self.assertRaises(OSError):self.output([('new',b'a')])
        self.assertEqual(list(self.root.iterdir()),[]);self.assertEqual(self.ledger.usage(),0)
    def test_existing_file_and_symlink_are_never_replaced(self):
        old=self.root/'old';old.write_bytes(b'KEEP');(self.root/'link').symlink_to(old)
        for name in ['old','link']:
            with self.assertRaises(ValueError):self.output([(name,b'NEW')])
        self.assertEqual(old.read_bytes(),b'KEEP');self.assertEqual(self.ledger.usage(),0)
    def test_uncleanable_partial_keeps_full_crash_charge(self):
        with patch('storage_writers.os.fsync',side_effect=OSError(errno.ENOSPC,'full')),patch.object(Path,'unlink',side_effect=PermissionError('retain')),self.assertRaises(OSError):self.output([('partial',b'1')])
        self.assertEqual(self.ledger.usage(),8192)
        self.assertEqual(self.db.execute('SELECT state FROM upload_reservations').fetchone()[0],'writing')
    def test_settlement_failure_cleans_files_but_keeps_uncertain_charge(self):
        with patch.object(self.ledger,'settle',side_effect=sqlite3.OperationalError('database is locked')),self.assertRaises(sqlite3.OperationalError):self.output([('a',b'1')])
        self.assertEqual(list(self.root.iterdir()),[]);self.assertEqual(self.ledger.usage(),8192)

if __name__=='__main__':unittest.main(verbosity=2)
