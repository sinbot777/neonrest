"""Disposable privacy/hold regression suite. No live DB, filesystem roots, SMTP or secrets."""
import hashlib,json,os,sqlite3,sys,tempfile,time,types,unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask,abort,request,session

source=Path(os.environ.get('NEONREST_TEST_SOURCE',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(source.parent))
# Exercise the actual request routes with deterministic synthetic ages, not live enrollment.
ages=types.ModuleType('neonrest_sandbox.age_policy');ages.age=lambda db,uid:18 if uid in (1,2,4) else 14 if uid==3 else None
sys.modules['neonrest_sandbox.age_policy']=ages
from neonrest_sandbox import privacy_workflows as privacy, family_data, retention

SCHEMA='''
CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT,email TEXT,password_hash TEXT,verified INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP,bio TEXT,dob TEXT,actual_name TEXT,pronouns TEXT,timezone TEXT,avatar TEXT,avatar_path TEXT);
CREATE TABLE posts(id INTEGER PRIMARY KEY,user_id INTEGER,target_user_id INTEGER,content TEXT,circle TEXT,created_at TEXT);
CREATE TABLE comments(id INTEGER PRIMARY KEY,user_id INTEGER,post_id INTEGER,parent_comment_id INTEGER,content TEXT,created_at TEXT);
CREATE TABLE post_media(id INTEGER PRIMARY KEY,post_id INTEGER,filename TEXT,poster TEXT,loop_filename TEXT,kind TEXT);
CREATE TABLE family_links(parent_id INTEGER,child_id INTEGER,status TEXT,method TEXT,reference TEXT,reviewed_by INTEGER,reviewed_at TEXT);
CREATE TABLE account_safety(user_id INTEGER PRIMARY KEY,inactive INTEGER DEFAULT 0,deletion_requested_at TEXT);
CREATE TABLE active_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER,revoked INTEGER,expires_at INTEGER,seen_at INTEGER);
CREATE TABLE age_policy_events(actor_id INTEGER,child_id INTEGER,action TEXT);
CREATE TABLE family_consent_documents(id INTEGER PRIMARY KEY,parent_id INTEGER,child_id INTEGER,storage_key TEXT,created_at TEXT);
CREATE TABLE moderation_cases(id INTEGER PRIMARY KEY,target_type TEXT,target_id INTEGER,owner_id INTEGER,status TEXT,closed_at TEXT);
CREATE TABLE case_links(case_id INTEGER,kind TEXT,item_id INTEGER);
CREATE TABLE case_evidence(case_id INTEGER,snapshot TEXT);
CREATE TABLE content_reports(id INTEGER PRIMARY KEY,target_type TEXT,target_id INTEGER,reporter_id INTEGER,status TEXT);
CREATE TABLE moderation_appeals(id INTEGER PRIMARY KEY,appellant_id INTEGER,status TEXT);
CREATE TABLE rate_buckets(subject TEXT,action TEXT,window INTEGER,touched_at INTEGER);
CREATE TABLE staff_roles(user_id INTEGER,role TEXT);
CREATE TABLE friend_requests(sender_id INTEGER,receiver_id INTEGER,status TEXT,created_at TEXT);
CREATE TABLE password_resets(user_id INTEGER,expires_at INTEGER,used INTEGER);
'''
class PrivacyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.db.executescript(SCHEMA)
  for uid in (1,2,3,4):self.db.execute('INSERT INTO users(id,handle,email,password_hash,verified,bio) VALUES (?,?,?,?,1,?)',(uid,'@person'+str(uid),'person'+str(uid)+'@example.invalid','not-a-login-hash','Profile'))
  self.db.execute("INSERT INTO family_links VALUES (2,3,'approved','signed-form','test-only',1,'2026-01-01')")
  self.db.execute("INSERT INTO posts VALUES (10,3,NULL,'Child post','public','2026-01-01')")
  self.db.execute("INSERT INTO posts VALUES (11,4,NULL,'Other person private text','private','2026-01-01')")
  self.db.execute("INSERT INTO comments VALUES (20,3,11,NULL,'Child reply','2026-01-01')")
  self.db.execute("INSERT INTO post_media VALUES (30,10,'private-file',NULL,NULL,'image')")
  self.db.commit()
  self.app=Flask('privacy-tests',template_folder=str(source/'templates'));self.app.secret_key='disposable-privacy-test-secret';self.app.config['TESTING']=True
  self.app.jinja_loader=__import__('jinja2').ChoiceLoader([__import__('jinja2').DictLoader({'base.html':'{% block content %}{% endblock %}','partials/account_navigation.html':''}),self.app.jinja_loader])
  def csrf():
   if request.form.get('theme_csrf_token')!='synthetic-token':abort(400)
  def perm(permission):
   if session.get('user_id') not in (1,4):abort(403)
   return session['user_id']
  self.core=types.SimpleNamespace(get_db=lambda:self.db,require_staff_permission=perm,has_staff_permission=lambda db,uid,p:uid in (1,4),theme_csrf_token=lambda:'synthetic-token',identifiers=types.SimpleNamespace(export_ids=lambda db,data:None))
  self.app.extensions['community_auth_helpers']={'csrf':csrf,'fresh':lambda:session.get('fresh',False),'limited':lambda *a:None}
  self.app.add_url_rule('/confirm','community_reauth',lambda:'Confirm')
  family_data.register(self.app,self.core)
  self.client=self.app.test_client();self.login(1)
  cur=self.db.execute("INSERT INTO family_data_requests(parent_id,child_id,kind,response_due,assigned_to) VALUES (2,3,'data-review',?,1)",(int(time.time())+45*privacy.DAY,));self.rid=cur.lastrowid;self.db.commit()
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def login(self,uid,fresh=True):
  with self.client.session_transaction() as sess:sess['user_id']=uid;sess['fresh']=fresh
 def post(self,path,data):return self.client.post(path,data=dict(data,theme_csrf_token='synthetic-token'))
 def row(self):return self.db.execute('SELECT * FROM family_data_requests WHERE id=?',(self.rid,)).fetchone()
 def hold(self,uid=3):
  self.db.execute('INSERT INTO privacy_holds(user_id,reason,legal_basis,reference,reviewer_id,created_at,review_due) VALUES (?,?,?,?,?,?,?)',(uid,'Unresolved harassment','Necessary investigation','case-test',1,1,2));self.db.commit()
 def approve(self,payload=None):
  data=privacy.export_candidate(self.db,3) if payload is None else payload
  return self.post('/manage/family/requests',dict(request_id=self.rid,action='approve-access',reference='reviewed',guardian_verified='1',disclosure_reviewed='1',disclosure_basis='Verified authority for this disclosure',reviewed_export=json.dumps(data)))
 def deletion(self,uid=3):
  self.db.execute("INSERT INTO account_safety(user_id,inactive,deletion_requested_at) VALUES (?,1,'2000-01-01')",(uid,));self.db.commit()
 def test_additive_migration_is_repeatable(self):
  privacy.initialize(self.db);privacy.initialize(self.db);self.assertEqual(self.db.execute('SELECT count(*) FROM users').fetchone()[0],4)
 def test_management_requires_permission_and_freshness(self):
  self.login(2);self.assertEqual(self.client.get('/manage/privacy').status_code,403)
  self.login(1,False);self.assertEqual(self.client.get('/manage/privacy').status_code,403)
 def test_csrf_required(self):self.assertEqual(self.client.post('/manage/privacy',data={'action':'add-hold'}).status_code,400)
 def test_pages_render_and_escape(self):
  self.db.execute('UPDATE family_data_requests SET notes=?',('<script>bad()</script>',));self.db.commit()
  self.assertEqual(self.client.get('/manage/privacy').status_code,200)
  self.assertNotIn(b'<script>bad()',self.client.get('/manage/family/requests').data)
  self.login(2);self.assertEqual(self.client.get('/account/family/requests').status_code,200)
 def test_hold_blocks_plan_and_direct_erasure_even_when_overdue(self):
  self.deletion();self.hold();p=retention.plan(self.db);self.assertNotIn(3,p['accounts']);self.assertIn(3,p['held_accounts'])
  with self.assertRaises(ValueError):retention.erase_account(self.db,3,{})
  self.assertEqual(self.db.execute('SELECT content FROM posts WHERE id=10').fetchone()[0],'Child post')
 def test_hold_added_after_preview_blocks_erasure(self):
  self.deletion();self.assertIn(3,retention.plan(self.db)['accounts']);self.hold()
  with self.assertRaises(ValueError):retention.erase_account(self.db,3,{})
 def test_case_requires_recorded_final_disposition_and_reopen_invalidates_it(self):
  self.db.execute("INSERT INTO moderation_cases VALUES (1,'post',10,3,'open',NULL)");self.db.commit();self.assertTrue(privacy.blockers(self.db,3))
  self.db.execute("UPDATE moderation_cases SET status='closed' WHERE id=1");self.db.commit();self.assertTrue(privacy.blockers(self.db,3))
  self.assertEqual(self.post('/manage/privacy',dict(action='finalize-case',case_id=1,reason='No action needed, review complete',appeals_final='1')).status_code,302)
  self.assertFalse(privacy.blockers(self.db,3))
  self.db.execute("UPDATE moderation_cases SET status='open' WHERE id=1");self.db.execute("UPDATE moderation_cases SET status='closed' WHERE id=1");self.db.commit();self.assertTrue(privacy.blockers(self.db,3))
 def test_linked_open_appeal_prevents_finalization(self):
  self.db.execute("INSERT INTO moderation_cases VALUES (1,'post',10,3,'closed',NULL)");self.db.execute("INSERT INTO moderation_appeals VALUES (7,3,'open')");self.db.execute("INSERT INTO case_links VALUES (1,'appeal',7)");self.db.commit()
  self.assertEqual(self.post('/manage/privacy',dict(action='finalize-case',case_id=1,reason='Final',appeals_final='1')).status_code,409)
 def test_reporter_and_preserved_commenter_are_protected(self):
  self.db.execute("INSERT INTO moderation_cases VALUES (1,'post',10,3,'open',NULL)");self.db.execute("INSERT INTO content_reports VALUES (8,'post',10,2,'open')");self.db.execute("INSERT INTO case_links VALUES (1,'report',8)");self.db.execute('INSERT INTO case_evidence VALUES (?,?)',(1,json.dumps({'comments':[{'user_id':4}]})));self.db.commit()
  self.assertTrue(privacy.blockers(self.db,2));self.assertTrue(privacy.blockers(self.db,4))
 def test_cascade_cannot_remove_held_comment(self):
  self.hold(3);self.assertTrue(privacy.erasure_blockers(self.db,4))
  with self.assertRaises(ValueError):retention.erase_account(self.db,4,{})
 def test_deleting_commenter_cannot_alter_held_thread_owner(self):
  self.hold(4);self.assertTrue(privacy.erasure_blockers(self.db,3))
  with self.assertRaises(ValueError):retention.erase_account(self.db,3,{})
 def test_account_erasure_removes_reviewed_export_copy(self):
  self.approve();retention.initialize(self.db)
  roots={key:str(Path(self.tmp.name)/key) for key in ('avatars','media','consent','backups')}
  retention.erase_account(self.db,3,roots)
  self.assertFalse(self.db.execute('SELECT 1 FROM users WHERE id=3').fetchone());self.assertIsNone(self.row()['approved_payload'])
 def test_releasing_one_hold_does_not_release_another(self):
  self.hold();self.hold();self.assertEqual(self.post('/manage/privacy',dict(action='release-hold',hold_id=1,reason='Resolved',reference='final')).status_code,302);self.assertTrue(privacy.blockers(self.db,3))
 def test_hold_keeps_auth_records_and_queued_files_in_apply(self):
  self.deletion();self.hold();self.db.execute('INSERT INTO password_resets VALUES (3,1,1)');self.db.commit()
  roots={key:str(Path(self.tmp.name)/key) for key in ('avatars','media','consent','backups')}
  for folder in roots.values():Path(folder).mkdir()
  retention.initialize(self.db)
  file=Path(roots['media'])/'old';file.write_text('preserved');self.db.execute('INSERT INTO retention_file_queue(path) VALUES (?)',(str(file),));self.db.commit()
  result=retention.run(self.db,roots,apply=True);self.assertTrue(result['ancillary_cleanup_paused']);self.assertTrue(file.exists());self.assertTrue(self.db.execute('SELECT 1 FROM password_resets').fetchone())
 def test_export_requires_explicit_review(self):
  self.assertEqual(self.post('/manage/family/requests',dict(request_id=self.rid,action='approve-access',reference='review',guardian_verified='1')).status_code,400)
 def test_export_whitelists_and_ownership(self):
  data=privacy.export_candidate(self.db,3);self.assertNotIn('password_hash',data['profile']);self.assertEqual([r['id'] for r in data['posts']],[10]);self.assertNotIn('filename',data['media'][0])
  data['profile']['totp_secret']='not-allowed'
  with self.assertRaises(ValueError):privacy.validate_export(self.db,3,json.dumps(data))
  with self.assertRaises(ValueError):privacy.validate_export(self.db,3,json.dumps({'posts':[{'id':11,'content':'Other user'}]}))
 def test_export_is_frozen_redacted_and_not_extended_to_new_content(self):
  self.assertEqual(self.approve({'profile':{'handle':'@person3'},'posts':[{'id':10,'content':'[redacted]'}]}).status_code,302)
  self.db.execute("UPDATE posts SET content='Changed later' WHERE id=10");self.db.execute("INSERT INTO posts VALUES (12,3,NULL,'New private post','private','2026-01-01')");self.db.commit();self.login(2)
  response=self.client.get('/account/family/requests/'+str(self.rid)+'/download');self.assertEqual(response.status_code,200);self.assertIn(b'[redacted]',response.data);self.assertNotIn(b'Changed later',response.data);self.assertNotIn(b'New private',response.data)
 def test_export_revocation_expiry_age_and_tampering(self):
  self.approve();self.login(2);url='/account/family/requests/'+str(self.rid)+'/download'
  self.login(4);self.assertEqual(self.client.get(url).status_code,404);self.login(2,False);self.assertEqual(self.client.get(url).status_code,302);self.login(2)
  self.db.execute("UPDATE family_links SET status='revoked',reviewed_at='changed'");self.db.commit();self.assertEqual(self.client.get(url).status_code,404)
  self.login(1);self.approve();self.login(2)
  with patch.object(ages,'age',side_effect=lambda db,uid:18):self.assertEqual(self.client.get(url).status_code,404)
  self.db.execute('UPDATE family_data_requests SET expires_at=1');self.db.commit();self.assertEqual(self.client.get(url).status_code,404)
  self.db.execute('UPDATE family_data_requests SET expires_at=?,approved_payload=?',(int(time.time())+100,'{}'));self.db.commit();self.assertEqual(self.client.get(url).status_code,404)
 def test_legacy_grant_requires_new_scope_review(self):
  self.db.execute("UPDATE family_data_requests SET status='access-approved',expires_at=?",(int(time.time())+100,));self.db.commit();self.login(2);self.assertEqual(self.client.get('/account/family/requests/'+str(self.rid)+'/download').status_code,404)
 def test_extension_once_and_only_before_original_deadline(self):
  due=self.row()['response_due'];self.assertEqual(self.post('/manage/privacy',dict(action='extend',request_id=self.rid,reason='Complex request',delivery_reference='Email delivered')).status_code,302);self.assertEqual(self.row()['response_due'],due+45*privacy.DAY)
  self.assertEqual(self.post('/manage/privacy',dict(action='extend',request_id=self.rid,reason='Again',delivery_reference='Email')).status_code,409)
 def test_assisted_intake_preserves_original_receipt_date(self):
  self.assertEqual(self.post('/manage/privacy',dict(action='record-request',child_id=3,parent_id=0,contact_email='parent@example.invalid',kind='data-review',notes='Received by email',received_at='2026-01-01T10:00')).status_code,302)
  row=self.db.execute('SELECT * FROM family_data_requests ORDER BY id DESC LIMIT 1').fetchone();self.assertEqual(row['parent_id'],0);self.assertEqual(row['created_at'],'2026-01-01 10:00:00')
 def test_decline_needs_explanation_and_parent_can_appeal(self):
  data=dict(action='decline',request_id=self.rid,reference='review')
  self.assertEqual(self.post('/manage/family/requests',data).status_code,400)
  data['decision_reason']='More authority evidence required';self.assertEqual(self.post('/manage/family/requests',data).status_code,302)
  self.login(2);self.assertEqual(self.post('/account/family/requests/'+str(self.rid)+'/appeal',dict(reason='Please reconsider')).status_code,302);self.assertTrue(privacy.blockers(self.db,3))
  self.login(1);self.assertEqual(self.post('/manage/privacy',dict(action='decide-appeal',request_id=self.rid,decision='denied',response_text='Authority not established',delivery_reference='Already delivered',complaint_notice_delivered='1',independence_reason='Sole available reviewer')).status_code,302);self.assertIn('Oregon Attorney General',self.row()['appeal_response'])
 def test_document_schedule_respects_preservation(self):
  self.db.execute("INSERT INTO family_consent_documents(id,parent_id,child_id,storage_key,created_at) VALUES (1,2,3,'doc.pdf','2000-01-01')");self.db.commit()
  self.assertEqual(self.post('/manage/privacy',dict(action='schedule-document-purge',document_id=1,purge_days=30,reason='Verified, retained minimal result')).status_code,302)
  self.db.execute('UPDATE family_consent_documents SET purge_after=1');self.db.commit();roots={'backups':self.tmp.name};self.assertEqual(retention.file_work(self.db,roots,int(time.time()))[1],[(1,'doc.pdf')]);self.hold();self.assertEqual(retention.file_work(self.db,roots,int(time.time()))[1],[])

if __name__=='__main__':unittest.main(verbosity=2)
