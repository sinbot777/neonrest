"""Disposable intake and document-retention checks. No SMTP or live files."""
import hashlib
import io
import re
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from verify_privacy_workflows import PrivacyTests
from neonrest import privacy_submissions as intake, retention


class SubmissionTests(unittest.TestCase):
    setUp_base = PrivacyTests.setUp
    tearDown = PrivacyTests.tearDown
    login = PrivacyTests.login
    post = PrivacyTests.post
    row = PrivacyTests.row
    hold = PrivacyTests.hold

    def setUp(self):
        self.setUp_base()
        self.app.extensions['community_auth_helpers']['limited']=lambda *args,**kwargs:None
        self.app.config['PRIVACY_SUBMISSIONS_FOLDER'] = str(Path(self.tmp.name) / 'documents')

    def invite(self):
        self.login(1)
        response = self.post('/manage/privacy/submissions', dict(action='invite', request_id=self.rid, instructions='Synthetic redacted evidence only'))
        self.assertEqual(response.status_code, 200)
        found = re.search(r'value="(https://[^" ]+#([A-Za-z0-9_-]+))"', response.data.decode())
        self.assertIsNotNone(found)
        return found.group(2)

    def upload(self, token, data=b'%PDF-1.4\nSynthetic training file\n%%EOF', csrf='synthetic-token', origin='http://localhost', filename='../../private.pdf'):
        return self.client.post('/privacy/submit', data={'invite_token':token,'theme_csrf_token':csrf,'document':(io.BytesIO(data),filename)},
                                headers={'Origin':origin}, content_type='multipart/form-data')

    def document(self):
        return self.db.execute('SELECT * FROM privacy_submission_documents ORDER BY id DESC LIMIT 1').fetchone()

    def prepare_purge(self):
        old = int(time.time())-40*intake.DAY
        date = datetime.fromtimestamp(old, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('UPDATE privacy_submission_documents SET reviewed_at=?,reviewed_by=1,review_reference=?',(old,'Synthetic review'))
        self.db.execute("UPDATE family_data_requests SET status='closed',reviewed_at=?,responded_at=? WHERE id=?",(date,old,self.rid));self.db.commit()

    def test_staff_invitation_is_hashed_one_file_and_no_email(self):
        self.login(1);self.assertEqual(self.client.get('/manage/privacy/submissions').headers['Referrer-Policy'],'same-origin')
        raw=self.invite();row=self.db.execute('SELECT * FROM privacy_upload_invites').fetchone()
        self.assertEqual(row['token_hash'],hashlib.sha256(raw.encode()).hexdigest());self.assertNotIn(raw,str([tuple(x) for x in self.db.execute('SELECT * FROM privacy_request_events')]))
        self.login(2);response=self.upload(raw);self.assertEqual(response.status_code,200);self.assertIn(b'document was received',response.data)
        self.assertEqual(self.upload(raw).status_code,404);self.assertEqual(self.db.execute('SELECT count(*) FROM privacy_submission_documents').fetchone()[0],1)

    def test_unlinked_requester_needs_no_account(self):
        self.db.execute('UPDATE family_data_requests SET parent_id=0 WHERE id=?',(self.rid,));self.db.commit();raw=self.invite()
        with self.client.session_transaction() as sess:sess.clear()
        self.assertEqual(self.client.get('/privacy/submit').status_code,200)
        self.assertEqual(self.upload(raw).status_code,200)
        self.assertEqual(self.db.execute('SELECT count(*) FROM users').fetchone()[0],4)

    def test_public_page_has_no_external_resources_and_fragment_is_removed(self):
        response=self.client.get('/privacy/submit');self.assertEqual(response.status_code,200)
        self.assertIn(b'history.replaceState',response.data);self.assertIn(b'location.hash',response.data)
        self.assertNotIn(b'<script src=',response.data);self.assertNotIn(b'fonts.googleapis',response.data)
        self.assertIn("default-src 'none'",response.headers['Content-Security-Policy']);self.assertEqual(response.headers['Referrer-Policy'],'same-origin');self.assertIn('no-store',response.headers['Cache-Control'])

    def test_expired_revoked_and_closed_invites_fail(self):
        raw=self.invite();self.db.execute('UPDATE privacy_upload_invites SET expires_at=1');self.db.commit();self.assertEqual(self.upload(raw).status_code,404)
        raw=self.invite();self.post('/manage/privacy/submissions',dict(action='revoke',request_id=self.rid));self.assertEqual(self.upload(raw).status_code,404)
        raw=self.invite();self.db.execute("UPDATE family_data_requests SET status='closed' WHERE id=?",(self.rid,));self.db.commit();self.assertEqual(self.upload(raw).status_code,404)

    def test_new_invite_invalidates_previous_link(self):
        first=self.invite();second=self.invite();self.assertEqual(self.upload(first).status_code,404);self.assertEqual(self.upload(second).status_code,200)

    def test_database_restore_does_not_replay_consumed_or_revoked_invite(self):
        raw=self.invite();self.assertEqual(self.upload(raw).status_code,200)
        self.db.execute('UPDATE privacy_upload_invites SET used_at=NULL');self.db.commit();self.assertEqual(self.upload(raw).status_code,404)
        raw=self.invite();self.post('/manage/privacy/submissions',dict(action='revoke',request_id=self.rid));self.db.execute('UPDATE privacy_upload_invites SET revoked_at=NULL');self.db.commit();self.assertEqual(self.upload(raw).status_code,404)

    def test_offline_restore_preflight_revokes_old_grants(self):
        raw=self.invite();self.db.execute("UPDATE family_data_requests SET status='access-approved',approved_payload='{}',payload_sha256='synthetic',expires_at=? WHERE id=?",(int(time.time())+100,self.rid));self.db.commit()
        intake.restore_preflight(self.app,self.db);self.assertEqual(self.upload(raw).status_code,404);self.assertIsNone(self.row()['approved_payload']);self.assertIsNone(self.row()['expires_at']);self.assertEqual(self.row()['status'],'pending-verification')

    def test_csrf_origin_and_invalid_token_rejected(self):
        raw=self.invite();self.assertEqual(self.upload(raw,csrf='wrong').status_code,400);self.assertEqual(self.upload(raw,origin='https://other.invalid').status_code,403);self.assertEqual(self.upload('invalid').status_code,404)

    def test_wrong_format_and_oversize_do_not_consume_link(self):
        raw=self.invite();self.assertEqual(self.upload(raw,b'<html>Not an identity document</html>').status_code,400)
        self.assertNotEqual(self.upload(raw,b'x'*(5*1024*1024+1)).status_code,200)
        self.assertEqual(self.upload(raw).status_code,200)

    def test_staff_only_private_download_and_integrity_check(self):
        raw=self.invite();self.assertEqual(self.upload(raw).status_code,200);doc=self.document();path='/manage/privacy/submissions/'+str(doc['id'])
        self.login(2);self.assertEqual(self.client.get(path).status_code,403)
        self.login(1,False);self.assertEqual(self.client.get(path).status_code,403)
        self.login(1);response=self.client.get(path);self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Referrer-Policy'],'no-referrer');self.assertIn('attachment',response.headers['Content-Disposition']);self.assertIn('no-store',response.headers['Cache-Control']);response.close()
        file=intake.document_path(self.app,doc['storage_key']);self.assertEqual(file.stat().st_mode&0o777,0o600);file.write_bytes(b'Tampered synthetic content');self.assertEqual(self.client.get(path).status_code,409)

    def test_documents_are_encrypted_and_missing_key_fails_closed(self):
        raw=self.invite();self.upload(raw);doc=self.document();file=intake.document_path(self.app,doc['storage_key']);self.assertNotIn(b'Synthetic training file',file.read_bytes())
        base,_=intake.roots(self.app);key=base.parent/(base.name+'.key');self.assertEqual(key.stat().st_mode&0o777,0o600);key.rename(key.with_suffix('.saved'))
        self.assertEqual(self.client.get('/manage/privacy/submissions/'+str(doc['id'])).status_code,409);self.assertFalse(key.exists())

    def test_path_traversal_filename_is_not_used(self):
        raw=self.invite();self.assertEqual(self.upload(raw).status_code,200);doc=self.document();self.assertRegex(doc['storage_key'],r'^[a-f0-9]{48}\.pdf$')
        with self.assertRaises(ValueError):intake.document_path(self.app,'../../secret')

    def test_document_review_does_not_grant_export_or_verify_authority(self):
        raw=self.invite();self.upload(raw);doc=self.document();response=self.post('/manage/privacy/submissions',dict(action='review-document',document_id=doc['id'],reference='Synthetic identity reviewed; authority not established'))
        self.assertEqual(response.status_code,200);self.assertEqual(self.row()['status'],'pending');self.assertIsNone(self.row()['approved_payload'])

    def test_purge_requires_final_resolution_review_grace_and_confirmation(self):
        raw=self.invite();self.upload(raw);doc=self.document();data=dict(action='purge-document',document_id=doc['id'],confirmation='DELETE DOCUMENT '+str(doc['id']))
        self.assertEqual(self.post('/manage/privacy/submissions',data).status_code,409);self.prepare_purge();self.assertIsNotNone(intake.purge_deadline(self.db,self.document()))
        self.assertEqual(self.post('/manage/privacy/submissions',dict(data,confirmation='wrong')).status_code,400)
        self.assertEqual(self.post('/manage/privacy/submissions',data).status_code,200);self.assertTrue(self.document()['purged_at']);self.assertFalse(intake.document_path(self.app,doc['storage_key']).exists());self.assertEqual(self.client.get('/manage/privacy/submissions/'+str(doc['id'])).status_code,404)

    def test_holds_appeals_and_release_extend_retention(self):
        raw=self.invite();self.upload(raw);self.prepare_purge();self.hold();self.assertIsNone(intake.purge_deadline(self.db,self.document()))
        self.db.execute('UPDATE privacy_holds SET released_at=?',(int(time.time()),));self.db.commit();self.assertGreater(intake.purge_deadline(self.db,self.document()),time.time()+29*intake.DAY)
        self.db.execute('UPDATE family_data_requests SET appealed_at=?,appeal_reviewed_at=NULL WHERE id=?',(int(time.time()),self.rid));self.db.commit();self.assertIsNone(intake.purge_deadline(self.db,self.document()))

    def test_request_records_use_final_appeal_date_and_keep_unpurged_document(self):
        old=int(time.time())-100*intake.DAY;date=datetime.fromtimestamp(old,timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute("UPDATE family_data_requests SET status='closed',created_at=?,reviewed_at=?,responded_at=?,appealed_at=?,appeal_reviewed_at=? WHERE id=?",(date,date,old,old,int(time.time()),self.rid));self.db.commit()
        self.assertFalse(any(x['table']=='family_data_requests' for x in retention.plan(self.db)['expired_records']))
        self.db.execute('UPDATE family_data_requests SET appeal_reviewed_at=? WHERE id=?',(old,self.rid));self.db.execute('INSERT INTO privacy_submission_documents(request_id,storage_key,media_type,bytes,sha256,created_at) VALUES (?, ?, ?,1,?,?)',(self.rid,'a'*48+'.pdf','application/pdf','synthetic',old));self.db.commit()
        self.assertFalse(any(x['table']=='family_data_requests' for x in retention.plan(self.db)['expired_records']))

    def test_unpurged_evidence_blocks_account_erasure(self):
        raw=self.invite();self.upload(raw)
        from neonrest import privacy_workflows
        self.assertIn('Private verification documents require reviewed disposal',privacy_workflows.erasure_blockers(self.db,3))
        self.assertIn('Private verification documents require reviewed disposal',privacy_workflows.erasure_blockers(self.db,2))

    def test_invitation_management_requires_staff_freshness_and_csrf(self):
        self.login(2);self.assertEqual(self.client.get('/manage/privacy/submissions').status_code,403)
        self.login(1,False);self.assertEqual(self.client.get('/manage/privacy/submissions').status_code,403)
        self.login(1);self.assertEqual(self.client.post('/manage/privacy/submissions',data={'action':'invite','request_id':self.rid,'instructions':'Synthetic'}).status_code,400)


if __name__=='__main__':unittest.main(verbosity=2)
