from pathlib import Path
exec(compile(Path(__file__).with_name('verify_circles_full_app.py').read_text(), 'verify_circles_full_app.py', 'exec'))

# Link-only sharing follows the same permissions and never copies source data.
import json
from urllib.parse import urlencode
from html import unescape
from neonrest_sandbox import public_ids
with app.app_context():
    action_public=public_ids.public(core.get_db(),'post',action_pid)
change("UPDATE circle_members SET status='removed' WHERE circle_id=? AND user_id=?",(action_cid,users['Outsider']))
share_path='/create_post?'+urlencode({'share_kind':'post','share_ref':action_public})
before_share=query('SELECT COUNT(*) FROM posts')[0][0]
shared=get('Member',share_path)
check(shared.status_code==200,'Member can prepare share of accessible Circle post')
check(b'ACTION POST SENTINEL' in shared.data,'Authorized source excerpt appears in composer preview')
check(b'ACTION POST SENTINEL' not in re.search(rb'<textarea[^>]*name="content"[^>]*>(.*?)</textarea>',shared.data,re.S).group(1),'Source excerpt is never placed in outgoing post content')
check(action_public.encode() in shared.data and b'https://www.neonrest.com/posts/' in shared.data,'Share uses canonical opaque original URL')
check(b'What you' in shared.data and b'name="shared_source"' in shared.data,'Composer identifies original and submits a structured reference')
check(query('SELECT COUNT(*) FROM posts')[0][0]==before_share,'Opening Share does not publish')
check(get('Outsider',share_path).status_code==404,'Nonmember cannot prepare inaccessible Circle post')
check(clients['Owner'].get('/create_post?'+urlencode({'share_kind':'circle','share_ref':hidden_opaque})).status_code==200,'Owner can share hidden Circle link')
check(clients['Outsider'].get('/create_post?'+urlencode({'share_kind':'circle','share_ref':hidden_opaque})).status_code==404,'Hidden Circle remains unavailable to outsider')
check(get('Owner','/create_post?share_kind=vibe&share_ref=Fresh+Starts').status_code==200,'Vibe link share composer')
for kind,ref in [('bad',action_public),('post','missing'),('circle','missing'),('vibe','missing'),('post','x'*201)]:
    check(get('Member','/create_post?'+urlencode({'share_kind':kind,'share_ref':ref})).status_code==404,'Malformed or absent share source rejected')
image_source=get('Member','/create_post?'+urlencode({'share_kind':'image','share_ref':action_public}))
check(image_source.status_code==404,'Missing image cannot be shared as own image')
change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(action_pid,users['Member'],users['Owner'],'Share test'))
check(get('Member',share_path).status_code==404,'Moderated source cannot be shared')
change('DELETE FROM moderated_posts WHERE post_id=?',(action_pid,))
# Separate fresh image and membership revocation checks.
change("DELETE FROM rate_buckets WHERE action='circle_changes'")
share_cid=hidden;share_token=public_circle(share_cid)
image=io.BytesIO();Image.new('RGB',(8,8),'blue').save(image,'PNG');image.seek(0)
check(clients['Owner'].post('/create_post',data={'content':'SHARE PRIVATE IMAGE SENTINEL','allow_circle_sharing':'1','circle_id':share_token,'audience':'public','theme_csrf_token':token,'post_image':(image,'share.png')}).status_code==302,'Create private image fixture')
share_pid=query('SELECT MAX(post_id) FROM circle_posts WHERE circle_id=?',(share_cid,))[0][0]
with app.app_context():share_public=public_ids.public(core.get_db(),'post',share_pid)
image_path='/create_post?'+urlencode({'share_kind':'image','share_ref':share_public})
image_draft=get('Owner',image_path)
check(image_draft.status_code==200 and ('#post-image-'+share_public).encode() in image_draft.data,'Own image shares post anchor, never raw media')
check(b'SHARE PRIVATE IMAGE SENTINEL' in image_draft.data and b'<img' in image_draft.data,'Authorized image preview includes original excerpt and protected thumbnail')
image_text=re.search(rb'<textarea[^>]*name="content"[^>]*>(.*?)</textarea>',image_draft.data,re.S).group(1)
check(b'SHARE PRIVATE IMAGE SENTINEL' not in image_text and b'/media-file/' not in image_text,'Preview image and excerpt are not copied into the outgoing post')
check(get('Outsider',image_path).status_code==404,'Own image sharing cannot cross ownership or membership')
body=get('Owner','/posts/'+share_public).data
check(b'Share image' in body and b'data-neon-share' in body,'Own image and post share controls render')
check(('id="post-image-'+share_public+'"').encode() in body,'Image share destination anchor exists')
check(b'Share Circle' in get('Owner','/circles/'+share_token).data,'Circle share button renders')
check(b'Share Vibe' in get('Owner','/vibe/Fresh%20Starts').data,'Vibe share button renders')
check(post('Owner','/create_post',content='Shared a post on Neonrest:\n\nhttps://www.neonrest.com/posts/'+share_public,audience='public').status_code==302,'Link repost uses normal protected composer')
check(get('Outsider','/posts/'+share_public).status_code==404,'Publishing a link never grants source access')
check(post('Owner','/create_post',content='SHARE VIBE SENTINEL',vibes='Fresh Starts',audience='public').status_code==302,'Create Vibe source fixture')
check(b'data-share-kind="post"' in get('Owner','/vibe/Fresh%20Starts').data,'Vibe posts include individual share controls')
# Viewer-only previews must escape source text and disappear with lost access.
change('UPDATE posts SET content=? WHERE id=?',('<script>PREVIEW_ESCAPE_SENTINEL</script>'+'x'*600,share_pid))
preview=get('Owner',image_path)
check(b'&lt;script&gt;PREVIEW_ESCAPE_SENTINEL&lt;/script&gt;' in preview.data and b'<script>PREVIEW_ESCAPE_SENTINEL</script>' not in preview.data,'Source preview is escaped, never executable HTML')
check(b'x'*450 not in preview.data,'Preview excerpt is bounded')
check(b'What you' in preview.data and b'Preview for you' in preview.data,'Preview clearly identified as viewer-only')
check(get('Outsider',image_path).status_code==404,'Inaccessible image preview returns no source details')
check(b'share-preview-heading' not in get('Owner','/create_post').data,'Ordinary composer has no misleading preview')
check('no-store' in preview.headers.get('Cache-Control',''),'Private composer preview is not cached')
old_media=query("SELECT * FROM post_media WHERE post_id=? AND kind='image'",(share_pid,))[0]
change("UPDATE post_media SET kind='gif',poster=filename,filename='PREVIEW_LOOP_ONLY.gif' WHERE post_id=? AND kind='image'",(share_pid,))
gif_preview=get('Owner',image_path)
check(old_media['filename'].encode() in gif_preview.data and b'PREVIEW_LOOP_ONLY.gif' not in gif_preview.data,'GIF preview uses its still poster, not animated media')
# Loading a shared draft creates no preview records or permanent source snapshots.
check(query('SELECT COUNT(*) FROM posts')[0][0]==before_share+3,'Only three explicitly submitted fixture posts were created')
with app.app_context():
    from neonrest_sandbox.sharing import prepare
    with app.test_request_context('/'):
        info=prepare(core.get_db(),'circle',hidden_opaque,users['Owner'])
        check(info['preview']['title'].startswith('Fixture Circle#') and info['preview']['audience']=='Hidden · invitation only','Hidden Circle preview shows exact numbered name and privacy')
        info=prepare(core.get_db(),'vibe','Fresh Starts',users['Owner'])
        check(info['preview']['title']=='Fresh Starts' and info['preview']['kind']=='vibe','Vibe preview uses verified source metadata')
print('SHARING FULL APPLICATION PASS' ,checks,'total checks; link-only reposts; original privacy preserved; no SMTP')

# Connected cards: permission is explicit for Circle originals and checked on every read.
change('DELETE FROM rate_buckets')
change("INSERT INTO circle_members VALUES (?,?,'member','active',CURRENT_TIMESTAMP) ON CONFLICT(circle_id,user_id) DO UPDATE SET status='active',role='member'",(hidden,users['Member']))
photo=io.BytesIO();Image.new('RGB',(12,8),'green').save(photo,'PNG');photo.seek(0)
response=clients['Owner'].post('/create_post',data={'content':'CIRCLE SHARED TEXT SENTINEL','circle_id':hidden_opaque,'allow_circle_sharing':'1','theme_csrf_token':token,'post_image':(photo,'connected.png')})
check(response.status_code==302,'Author explicitly opts Circle original into external sharing')
source_id=query('SELECT MAX(post_id) FROM circle_posts WHERE circle_id=?',(hidden,))[0][0]
with app.app_context():source_public=public_ids.public(core.get_db(),'post',source_id)
check(query('SELECT external_circle FROM post_share_permissions WHERE post_id=?',(source_id,))[0][0]==1,'Explicit author decision is stored')
check(post('Member','/create_post',content='MY COMMENT SENTINEL',shared_source=source_public,shared_kind='post',audience='public',vibes='Fresh Starts').status_code==302,'Authorized member publishes connected share with commentary')
wrapper=query('SELECT MAX(share_post_id) FROM post_shares')[0][0]
with app.app_context():wrapper_public=public_ids.public(core.get_db(),'post',wrapper)
wrapper_url='/posts/'+wrapper_public
body=get('Outsider',wrapper_url)
check(body.status_code==200 and b'CIRCLE SHARED TEXT SENTINEL' in body.data and b'MY COMMENT SENTINEL' in body.data,'Nonmember sees opted-in source text and separate commentary')
check(b'@CircleFixtureOwner' in body.data and b'Original post' in body.data,'Connected card attributes the original author and links back')
check(b'Hidden' not in body.data and b'Fixture Circle#' not in body.data,'Share does not disclose hidden Circle name or rules')
check(get('Outsider','/posts/'+source_public).status_code==404,'Original Circle post remains membership restricted')
photo_name=query("SELECT filename FROM post_media WHERE post_id=? AND kind='image'",(source_id,))[0][0]
check(get('Outsider','/media-file/'+photo_name).status_code==404,'Original media URL remains private')
media_url='/shared-media/'+wrapper_public+'/image/filename'
media_response=get('Outsider',media_url)
check(media_response.status_code==200 and media_response.headers.get('Content-Type','').startswith('image/') and bool(media_response.data),'Shared photo is delivered to eligible nonmember through wrapper')
check('no-store' in media_response.headers.get('Cache-Control',''),'Shared media is not cached after revocation')
media_response.close()
check(get('Outsider','/shared-media/'+source_public+'/image/filename').status_code==404,'An original ID cannot substitute for a share capability')
check(get('Outsider','/shared-media/'+wrapper_public+'/image/no-such-field').status_code==404,'Media variants are allowlisted')
check(b'name="allow_circle_sharing"' in get('Owner','/edit_post/'+source_public).data,'Author can change external sharing on edit')
change('UPDATE posts SET content=? WHERE id=?',('CIRCLE EDITED TEXT SENTINEL',source_id))
check(b'CIRCLE EDITED TEXT SENTINEL' in get('Outsider',wrapper_url).data and b'CIRCLE SHARED TEXT SENTINEL' not in get('Outsider',wrapper_url).data,'Existing shares reflect edits without source snapshots')
check(post('Owner','/edit_post/'+source_public,content='CIRCLE EDITED TEXT SENTINEL',vibes='',circle='').status_code==302,'Author turns sharing off through normal edit form')
check(query('SELECT external_circle FROM post_share_permissions WHERE post_id=?',(source_id,))[0][0]==0,'Absent checkbox explicitly revokes external sharing')
body=get('Outsider',wrapper_url)
check(body.status_code==200 and b'CIRCLE EDITED TEXT SENTINEL' not in body.data and b'original post is unavailable' in body.data,'Revocation hides content in existing nonmember shares')
check(get('Outsider',media_url).status_code==404,'Revocation also stops shared photo delivery')
check(b'CIRCLE EDITED TEXT SENTINEL' in get('Member',wrapper_url).data,'Current Circle member retains ordinary source access after external revocation')
before=query('SELECT COUNT(*) FROM posts')[0][0]
check(post('Member','/create_post',content='',shared_source=source_public,shared_kind='post',audience='public').status_code==400,'New Circle repost is rejected when author sharing is off')
check(query('SELECT COUNT(*) FROM posts')[0][0]==before,'Rejected share creates no orphan post')
check(b'Edit sharing' in get('Owner','/posts/'+source_public).data,'Author has a clear path to enable sharing')
check(post('Outsider','/edit_post/'+source_public,content='forged',vibes='',circle='',allow_circle_sharing='1').status_code==302,'Another account cannot edit source permission')
check(query('SELECT external_circle FROM post_share_permissions WHERE post_id=?',(source_id,))[0][0]==0,'Non-author cannot enable sharing')
check(post('Owner','/edit_post/'+source_public,content='CIRCLE EDITED TEXT SENTINEL',vibes='',circle='',allow_circle_sharing='1').status_code==302,'Author may opt back in')
check(b'CIRCLE EDITED TEXT SENTINEL' in get('Outsider',wrapper_url).data,'Existing card reflects renewed author permission')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Outsider'],users['Owner']))
check(b'CIRCLE EDITED TEXT SENTINEL' not in get('Outsider',wrapper_url).data and get('Outsider',media_url).status_code==404,'Source-author blocking suppresses card and shared photo independently of wrapper author')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Outsider'],users['Owner']))
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(wrapper,))
check(get('Outsider',wrapper_url).status_code==404 and get('Outsider',media_url).status_code==404,'Wrapper audience independently restricts its media')
change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(wrapper,))
change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(source_id,users['Owner'],users['Owner'],'Fictional shared-source restriction'))
check(b'CIRCLE EDITED TEXT SENTINEL' not in get('Outsider',wrapper_url).data and get('Outsider',media_url).status_code==404,'Site moderation hides shared text and media')
change('DELETE FROM moderated_posts WHERE post_id=?',(source_id,))
change("INSERT INTO circle_content_removals(circle_id,target_type,target_id,report_id,removed_by) VALUES (?,'post',?,0,?)",(hidden,source_id,users['Owner']))
check(b'CIRCLE EDITED TEXT SENTINEL' not in get('Outsider',wrapper_url).data and get('Outsider',media_url).status_code==404,'Circle removal supersedes author sharing permission')
change("DELETE FROM circle_content_removals WHERE target_type='post' AND target_id=?",(source_id,))
change('UPDATE circles SET archived=1 WHERE id=?',(hidden,))
check(get('Outsider',media_url).status_code==404,'Archived Circle stops externally shared media')
change('UPDATE circles SET archived=0 WHERE id=?',(hidden,))
check(post('Outsider','/create_post',content='',shared_source=source_public,shared_kind='post',audience='public').status_code==404,'Knowing shareable Circle original ID does not bypass membership to create a new source share')
# Public originals include full text and all supported uploaded attachments.
photo=io.BytesIO();Image.new('RGB',(10,10),'red').save(photo,'PNG');photo.seek(0)
check(clients['Owner'].post('/create_post',data={'content':'PUBLIC FULL TEXT SENTINEL','audience':'public','theme_csrf_token':token,'post_image':(photo,'public.png')}).status_code==302,'Create public source')
public_source=query('SELECT MAX(id) FROM posts')[0][0]
with app.app_context():public_token=public_ids.public(core.get_db(),'post',public_source)
check(post('Member','/create_post',content='',shared_source=public_token,shared_kind='post',audience='public').status_code==302,'Sharing a public post needs no boilerplate or extra comment')
public_wrapper=query('SELECT MAX(share_post_id) FROM post_shares')[0][0]
with app.app_context():public_wrapper_token=public_ids.public(core.get_db(),'post',public_wrapper)
pub_url='/posts/'+public_wrapper_token
check(b'PUBLIC FULL TEXT SENTINEL' in get('Outsider',pub_url).data,'Public shared post includes original text')
check(get('Outsider','/shared-media/'+public_wrapper_token+'/image/filename').status_code==200,'Public shared post includes photo')
with app.app_context():
    mf=media_folder();midi_name='a'*40+'.mid';(mf/midi_name).write_bytes(b'MThd'+b'\x00'*10)
change("INSERT INTO post_media(post_id,kind,filename,title) VALUES (?,'midi',?,'MIDI share fixture')",(public_source,midi_name))
check(b'MIDI share fixture' in get('Outsider',pub_url).data,'Shared card includes MIDI controls and title')
check(get('Outsider','/shared-media/'+public_wrapper_token+'/midi/filename').data.startswith(b'MThd'),'MIDI is served through the same permission gate')
# GIF playback variants remain under the same source-and-wrapper gate.
poster=query("SELECT filename FROM post_media WHERE post_id=? AND kind='image'",(public_source,))[0][0]
with app.app_context():
    mf=media_folder();gif_once='b'*40+'-once.gif';gif_loop='b'*40+'-loop.gif'
    Image.new('RGB',(8,8),'purple').save(mf/gif_once,'GIF');(mf/gif_loop).write_bytes((mf/gif_once).read_bytes())
change("UPDATE post_media SET kind='gif',poster=filename,filename=?,loop_filename=? WHERE post_id=? AND kind='image'",(gif_once,gif_loop,public_source))
check(b'data-gif-action="play"' in get('Outsider',pub_url).data,'Connected GIF has playback controls')
for variant in ('poster','filename','loop_filename'):
    streamed=get('Outsider','/shared-media/'+public_wrapper_token+'/gif/'+variant)
    check(streamed.status_code==200 and bool(streamed.data),'GIF '+variant+' delivered through share permission checks')
    streamed.close()
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(public_source,))
check(b'PUBLIC FULL TEXT SENTINEL' not in get('Outsider',pub_url).data and get('Outsider','/shared-media/'+public_wrapper_token+'/midi/filename').status_code==404,'Changing public source audience revokes shared text and other attachments')
change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(public_source,))
check(b'PUBLIC FULL TEXT SENTINEL' in get('Outsider','/feed').data,'Connected card renders in the shared feed')
check(b'CIRCLE EDITED TEXT SENTINEL' in get('Outsider','/vibe/Fresh%20Starts').data,'Opted-in Circle source renders only inside its public Vibe wrapper')
# A report of the wrapper preserves what was shown, without private source replies.
check(post('Owner','/create_comment',post_id=source_public,content='PRIVATE CIRCLE REPLY SENTINEL').status_code==201,'Create unshared source reply fixture')
with app.app_context():
    with app.test_request_context('/'):
        from flask import session
        session['user_id']=users['Outsider']
        db=core.get_db();case=cf.ensure_case(db,'post',wrapper,users['Member']);cf.preserve(db,case,'post',wrapper);db.commit()
        snapshots=[json.loads(x[0]) for x in db.execute('SELECT snapshot FROM case_evidence WHERE case_id=?',(case,))]
        check(any(x.get('source_id')==source_id and 'CIRCLE EDITED TEXT SENTINEL' in json.dumps(x) for x in snapshots),'Reporting a share preserves its displayed original as case evidence')
        check(not any('PRIVATE CIRCLE REPLY SENTINEL' in json.dumps(x) for x in snapshots),'Shared-source evidence excludes private original replies')
change('DELETE FROM posts WHERE id=?',(source_id,))
check(b'CIRCLE EDITED TEXT SENTINEL' not in get('Outsider',wrapper_url).data and get('Outsider',media_url).status_code==404,'Deleting original source removes existing shared content')
check(bool(query('SELECT 1 FROM posts WHERE id=?',(wrapper,))),'Source deletion preserves sharer commentary')
check(not query('SELECT 1 FROM post_share_permissions WHERE post_id=?',(source_id,)),'Deleting source cleans up author permission')
import gc
gc.collect()
work.cleanup()
print('CONNECTED SHARES PASS',checks,'total checks; public attachments, Circle opt-in/revocation, original-route isolation; no SMTP')
