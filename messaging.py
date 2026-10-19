"""Participant-only text messaging. Staff receive only participant-submitted reports."""
import json
import os
import re
import secrets
import sqlite3
import time
from functools import wraps
from flask import abort, current_app, flash, g, jsonify, make_response, redirect, render_template, request, session, url_for
from . import age_policy as ages, community_features as community, public_ids

TOKEN=public_ids.TOKEN
NONCE=re.compile(r'[A-Za-z0-9_-]{16,64}\Z',re.ASCII)
MAX_BODY=4000
PAGE_SIZE=50
STATUSES={'invisible':'Invisible','online':'Online','away':'Away','busy':'Busy'}
INBOXES={'friends':'Friends only','requests':'Allow message requests','closed':'No new conversations'}


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS dm_settings(user_id INTEGER PRIMARY KEY,
      inbox TEXT NOT NULL DEFAULT 'friends' CHECK(inbox IN ('friends','requests','closed')),
      presence TEXT NOT NULL DEFAULT 'invisible' CHECK(presence IN ('invisible','online','away','busy')),
      away TEXT NOT NULL DEFAULT '' CHECK(length(away)<=140),active_at INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS dm_threads(id INTEGER PRIMARY KEY,public_id TEXT NOT NULL UNIQUE,
      low_user INTEGER,high_user INTEGER,requested_by INTEGER,
      state TEXT NOT NULL CHECK(state IN ('pending','accepted','declined')),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(low_user,high_user),CHECK(low_user IS NULL OR high_user IS NULL OR low_user<high_user));
    CREATE TABLE IF NOT EXISTS dm_members(thread_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
      read_id INTEGER NOT NULL DEFAULT 0,muted INTEGER NOT NULL DEFAULT 0 CHECK(muted IN (0,1)),
      paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),PRIMARY KEY(thread_id,user_id));
    CREATE INDEX IF NOT EXISTS dm_members_user ON dm_members(user_id,thread_id);
    CREATE TABLE IF NOT EXISTS dm_messages(id INTEGER PRIMARY KEY,public_id TEXT NOT NULL UNIQUE,
      thread_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 4000),
      client_nonce TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),UNIQUE(sender_id,client_nonce));
    CREATE INDEX IF NOT EXISTS dm_messages_thread ON dm_messages(thread_id,id);
    CREATE TABLE IF NOT EXISTS dm_reports(id INTEGER PRIMARY KEY,thread_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
      reporter_id INTEGER,author_id INTEGER,reason TEXT NOT NULL,case_id INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),outcome TEXT,
      reviewer_id INTEGER,decision TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,reviewed_at TEXT,
      UNIQUE(message_id,reporter_id));
    CREATE INDEX IF NOT EXISTS dm_reports_case ON dm_reports(case_id,status);
    ''')
    db.commit()


def usable(db,uid):
    if not uid or not ages.ready(db,uid):return False
    row=db.execute('SELECT verified FROM users WHERE id=?',(uid,)).fetchone()
    if not row or not row['verified']:return False
    return not (db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1',(uid,)).fetchone()
      or db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND (inactive=1 OR deletion_requested_at IS NOT NULL)',(uid,)).fetchone()
      or db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1',(uid,)).fetchone())


def prefs(db,uid):
    row=db.execute('SELECT * FROM dm_settings WHERE user_id=?',(uid,)).fetchone()
    return dict(row) if row else dict(inbox='friends',presence='invisible',away='',active_at=0)


def peer_id(thread,uid):
    return thread['high_user'] if thread['low_user']==uid else thread['low_user']


def history_allowed(db,thread,uid):
    if not usable(db,uid):return False
    peer=peer_id(thread,uid)
    # A deleted peer leaves only the surviving user's own messages.
    if peer is None:return True
    # Historical access does not create new contact, but still rechecks age/parent permissions.
    return bool(usable(db,peer) and ages.contact(db,uid,peer,invitation=True))


def thread_for(db,value,uid):
    if not isinstance(value,str) or not TOKEN.fullmatch(value):abort(404)
    row=db.execute('SELECT t.* FROM dm_threads t JOIN dm_members m ON m.thread_id=t.id WHERE t.public_id=? AND m.user_id=?',(value,uid)).fetchone()
    if not row or not history_allowed(db,row,uid):abort(404)
    return row


def send_allowed(db,thread,uid):
    peer=peer_id(thread,uid)
    if not peer or thread['state']!='accepted' or not usable(db,uid) or not usable(db,peer):return False
    if community.blocked(db,uid,peer) or not ages.contact(db,uid,peer):return False
    if db.execute('SELECT 1 FROM dm_members WHERE thread_id=? AND paused=1',(thread['id'],)).fetchone():return False
    return not db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND (posting_restricted=1 OR interaction_restricted=1)',(uid,)).fetchone()


def visible_notice(db,row,uid):
    path=row['path'] or ''
    if not path.startswith('/messages/'):return False
    token=path[len('/messages/'):]
    if not TOKEN.fullmatch(token):return False
    thread=db.execute('SELECT t.* FROM dm_threads t JOIN dm_members m ON m.thread_id=t.id WHERE t.public_id=? AND m.user_id=?',(token,uid)).fetchone()
    if not thread or thread['state']=='declined' or not history_allowed(db,thread,uid):return False
    peer=peer_id(thread,uid)
    member=db.execute('SELECT muted,paused FROM dm_members WHERE thread_id=? AND user_id=?',(thread['id'],uid)).fetchone()
    return bool(peer and not community.blocked(db,uid,peer) and member and not member['muted'] and not member['paused'])


def notice(db,thread,uid,actor):
    member=db.execute('SELECT muted,paused FROM dm_members WHERE thread_id=? AND user_id=?',(thread['id'],uid)).fetchone()
    path='/messages/'+thread['public_id']
    if not member or member['muted'] or member['paused']:return
    if db.execute("SELECT 1 FROM notifications WHERE user_id=? AND kind='messages' AND path=? AND read_at IS NULL",(uid,path)).fetchone():return
    community.notify(db,uid,'messages','New message request.' if thread['state']=='pending' else 'New private message.',path,actor=actor)


def unread_threads(db,uid):
    if not usable(db,uid):return 0
    rows=db.execute('''SELECT t.* FROM dm_threads t JOIN dm_members m ON m.thread_id=t.id
      WHERE m.user_id=? AND t.state!='declined' AND m.paused=0 AND EXISTS
      (SELECT 1 FROM dm_messages x WHERE x.thread_id=t.id AND x.id>m.read_id AND x.sender_id!=?)
      ORDER BY t.id DESC LIMIT 101''',(uid,uid)).fetchall()
    return sum(history_allowed(db,t,uid) and not community.blocked(db,uid,peer_id(t,uid)) for t in rows)


def presence_for(db,peer,viewer):
    if not usable(db,viewer) or not usable(db,peer) or not community.friends(db,viewer,peer) or community.blocked(db,viewer,peer) or not ages.contact(db,viewer,peer):return dict(status='offline',label='Offline',away='')
    settings=prefs(db,peer)
    if settings['presence']=='invisible' or settings['active_at']<int(time.time())-150:return dict(status='offline',label='Offline',away='')
    return dict(status=settings['presence'],label=STATUSES[settings['presence']],away=settings['away'])


def message_payload(row,uid):
    return dict(key=row['public_id'],mine=row['sender_id']==uid,body='[Message removed by staff]' if row['hidden'] else row['body'],created=row['created_at'],hidden=bool(row['hidden']))


def export_user(db,uid):
    settings=prefs(db,uid)
    messages=[dict(key=r['public_id'],conversation=r['conversation'],body=r['body'],created_at=r['created_at'],hidden=bool(r['hidden'])) for r in db.execute('SELECT m.*,t.public_id AS conversation FROM dm_messages m JOIN dm_threads t ON t.id=m.thread_id WHERE m.sender_id=? ORDER BY m.id',(uid,))]
    return dict(settings={k:settings[k] for k in ('inbox','presence','away')},sent_messages=messages)


def erase_user(db,uid):
    """Called only after the shared preservation planner authorizes erasure."""
    db.execute('DELETE FROM dm_messages WHERE sender_id=?',(uid,))
    db.execute('DELETE FROM dm_members WHERE user_id=?',(uid,))
    db.execute('DELETE FROM dm_settings WHERE user_id=?',(uid,))
    db.execute("UPDATE dm_threads SET state='declined' WHERE low_user=? OR high_user=?",(uid,uid))
    db.execute('UPDATE dm_threads SET low_user=NULL WHERE low_user=?',(uid,))
    db.execute('UPDATE dm_threads SET high_user=NULL WHERE high_user=?',(uid,))
    db.execute('UPDATE dm_threads SET requested_by=NULL WHERE requested_by=?',(uid,))
    db.execute('UPDATE dm_reports SET reporter_id=NULL WHERE reporter_id=?',(uid,))
    db.execute('UPDATE dm_reports SET author_id=NULL WHERE author_id=?',(uid,))


def register(app,core):
    enabled=os.environ.get('NEONREST_MESSAGING_ENABLED', '1' if 'sandbox' in app.import_name else '0')=='1'
    app.config['MESSAGING_ENABLED']=enabled
    if not enabled:return
    app.config.setdefault('MESSAGING_MESSAGE_CAP',10000)
    with app.app_context():initialize(core.get_db())
    if 'messages' not in community.KINDS:community.KINDS+=('messages',)
    helpers=app.extensions['community_auth_helpers']
    def current_user():
        uid=session.get('user_id')
        if not uid:abort(401)
        if not usable(core.get_db(),uid):abort(403)
        return uid
    def limited(action,maximum,seconds=3600):
        return helpers['limited']('messages-'+action,maximum,seconds)
    def protected(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            current_user()
            if request.method=='POST':
                if request.content_length is not None and request.content_length>65536:abort(413)
                helpers['csrf']()
            try:return view(*args,**kwargs)
            except sqlite3.OperationalError:
                abort(503,description='Messages are temporarily busy. Try again shortly.')
        return wrapped
    def respond(thread):
        if request.accept_mimetypes.best=='application/json':return jsonify(ok=True,url=url_for('messaging_thread',thread_id=thread['public_id']))
        return redirect(url_for('messaging_thread',thread_id=thread['public_id']),code=303)
    def content():
        body=request.form.get('body','').replace('\r\n','\n').replace('\r','\n').strip()
        nonce=request.form.get('nonce','')
        if not 1<=len(body)<=MAX_BODY or any(ord(c)<32 and c not in '\n\t' or ord(c)==127 for c in body):abort(400,description='Write a message of 1–4,000 characters.')
        if not NONCE.fullmatch(nonce):abort(400,description='Refresh Messages before sending.')
        return body,nonce
    def insert_message(db,thread,uid,body,nonce):
        previous=db.execute('SELECT thread_id,body FROM dm_messages WHERE sender_id=? AND client_nonce=?',(uid,nonce)).fetchone()
        if previous:
            if previous['thread_id']!=thread['id']:abort(409)
            if previous['body']!=body:abort(409,description='This send was already used. Refresh before sending different text.')
            return
        if db.execute('SELECT COUNT(*) FROM dm_messages').fetchone()[0]>=app.config['MESSAGING_MESSAGE_CAP']:
            abort(503,description='Messaging storage is at capacity. Existing messages are safe; contact Neonrest support.')
        db.execute('INSERT INTO dm_messages(public_id,thread_id,sender_id,body,client_nonce) VALUES (?,?,?,?,?)',(public_ids.random_token(),thread['id'],uid,body,nonce))
        notice(db,thread,peer_id(thread,uid),uid)
    def thread_details(db,thread,uid):
        peer=peer_id(thread,uid);user=db.execute('SELECT handle FROM users WHERE id=?',(peer,)).fetchone() if peer else None
        member=db.execute('SELECT * FROM dm_members WHERE thread_id=? AND user_id=?',(thread['id'],uid)).fetchone()
        return dict(token=thread['public_id'],peer=user['handle'] if user else 'Deleted account',state=thread['state'],incoming=thread['requested_by']!=uid,
          can_send=send_allowed(db,thread,uid),blocked=bool(peer and community.blocked(db,uid,peer)),blocked_by_you=bool(peer and db.execute('SELECT 1 FROM user_blocks WHERE user_id=? AND target_id=?',(uid,peer)).fetchone()),paused=bool(member['paused']),muted=bool(member['muted']),presence=presence_for(db,peer,uid) if peer else dict(status='offline',label='Offline',away=''))
    def list_data(db,uid,box,page):
        rows=db.execute('''SELECT t.*,m.read_id,m.paused,m.muted FROM dm_threads t JOIN dm_members m ON m.thread_id=t.id
          WHERE m.user_id=? AND ((?='requests' AND t.state='pending' AND t.requested_by!=?) OR
          (?='chats' AND NOT(t.state='pending' AND t.requested_by!=?)))
          ORDER BY (SELECT MAX(x.id) FROM dm_messages x WHERE x.thread_id=t.id) DESC,t.id DESC LIMIT 51 OFFSET ?''',(uid,box,uid,box,uid,page*50)).fetchall()
        items=[]
        for t in rows[:50]:
            if not history_allowed(db,t,uid):continue
            incoming=t['state']=='pending' and t['requested_by']!=uid
            if (box=='requests')!=incoming:continue
            item=thread_details(db,t,uid);item['unread']=bool(t['state']!='declined' and not item['blocked'] and not t['paused'] and db.execute('SELECT 1 FROM dm_messages WHERE thread_id=? AND id>? AND sender_id!=? LIMIT 1',(t['id'],t['read_id'],uid)).fetchone());items.append(item)
        return items,buddy_data(db,uid),len(rows)>50
    def buddy_data(db,uid):
        peers=db.execute("SELECT DISTINCT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END AS peer FROM friend_requests WHERE status='accepted' AND (sender_id=? OR receiver_id=?) LIMIT 100",(uid,uid,uid)).fetchall()
        buddies=[]
        for row in peers:
            peer=row['peer']
            if not usable(db,peer) or community.blocked(db,uid,peer) or not ages.contact(db,uid,peer):continue
            user=db.execute('SELECT handle FROM users WHERE id=?',(peer,)).fetchone()
            buddies.append(dict(handle=user['handle'],presence=presence_for(db,peer,uid)))
        buddies.sort(key=lambda b:(b['presence']['status']=='offline',b['handle'].casefold()))
        return buddies
    def render_page(thread=None):
        uid=current_user();db=core.get_db();box=request.args.get('box','chats');page=request.args.get('page','0')
        if box not in ('chats','requests') or not page.isascii() or not page.isdecimal() or len(page)>4:abort(400)
        page=int(page);items,buddies,more=list_data(db,uid,box,page)
        detail=None;messages=[];older=None
        if thread:
            detail=thread_details(db,thread,uid);before=request.args.get('before')
            bound=2**63-1
            if before:
                row=db.execute('SELECT id FROM dm_messages WHERE public_id=? AND thread_id=?',(before,thread['id'])).fetchone()
                if not row:abort(400)
                bound=row['id']
            rows=db.execute('SELECT * FROM dm_messages WHERE thread_id=? AND id<? ORDER BY id DESC LIMIT 51',(thread['id'],bound)).fetchall()
            older=rows[49]['public_id'] if len(rows)>50 else None
            messages=[message_payload(r,uid) for r in reversed(rows[:50])]
        response=make_response(render_template('messages.html',thread=detail,messages=messages,older=older,threads=items,buddies=buddies,box=box,page=page,more=more,prefs=prefs(db,uid),statuses=STATUSES,inboxes=INBOXES,nonce=secrets.token_urlsafe(24),start_nonce=secrets.token_urlsafe(24),max_body=MAX_BODY))
        return response
    @app.context_processor
    def messaging_context():
        uid=session.get('user_id');count=unread_threads(core.get_db(),uid) if uid else 0
        return dict(messaging_enabled=True,messaging_unread=min(count,100))
    @app.after_request
    def messaging_headers(response):
        if request.path.startswith(('/messages','/manage/messages')):
            response.headers.update({'Cache-Control':'private, no-store','Referrer-Policy':'same-origin','X-Content-Type-Options':'nosniff','X-Robots-Tag':'noindex, nofollow','X-Frame-Options':'DENY'})
        return response
    @app.get('/messages')
    @protected
    def messaging_home():return render_page()
    @app.get('/messages/<thread_id>')
    @protected
    def messaging_thread(thread_id):return render_page(thread_for(core.get_db(),thread_id,current_user()))
    @app.post('/messages/start')
    @protected
    def messaging_start():
        uid=current_user();db=core.get_db();body,nonce=content();limit=limited('new',15)
        if limit is not None:return limit
        handle=request.form.get('handle','').strip().lstrip('@')
        if not 1<=len(handle)<=80:abort(400)
        with db:
            db.execute('BEGIN IMMEDIATE')
            peer=db.execute("SELECT id FROM users WHERE lower(ltrim(handle,'@'))=lower(?)",(handle,)).fetchone();peer=peer['id'] if peer else None
            if not peer or peer==uid or not usable(db,peer) or community.blocked(db,uid,peer) or not ages.contact(db,uid,peer):abort(404,description='This conversation is not available.')
            if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND (posting_restricted=1 OR interaction_restricted=1)',(uid,)).fetchone():abort(403)
            low,high=sorted((uid,peer));thread=db.execute('SELECT * FROM dm_threads WHERE low_user=? AND high_user=?',(low,high)).fetchone()
            if not thread:
                mode=prefs(db,peer)['inbox'];friends=community.friends(db,uid,peer) or ages.family(db,uid,peer)
                if mode=='closed' or mode=='friends' and not friends:abort(404,description='This conversation is not available.')
                if db.execute('SELECT COUNT(*) FROM dm_members WHERE user_id=?',(uid,)).fetchone()[0]>=500:abort(409,description='Please contact support before opening more conversations.')
                if not friends and db.execute("SELECT COUNT(*) FROM dm_threads WHERE state='pending' AND requested_by!=? AND (low_user=? OR high_user=?)",(peer,peer,peer)).fetchone()[0]>=50:abort(404,description='This conversation is not available.')
                key=public_ids.random_token();state='accepted' if friends else 'pending'
                tid=db.execute('INSERT INTO dm_threads(public_id,low_user,high_user,requested_by,state) VALUES (?,?,?,?,?)',(key,low,high,uid,state)).lastrowid
                db.executemany('INSERT INTO dm_members(thread_id,user_id) VALUES (?,?)',[(tid,uid),(tid,peer)])
                thread=db.execute('SELECT * FROM dm_threads WHERE id=?',(tid,)).fetchone()
                insert_message(db,thread,uid,body,nonce)
            elif thread['state']=='accepted' and send_allowed(db,thread,uid):insert_message(db,thread,uid,body,nonce)
            elif thread['state']=='pending' and thread['requested_by']==uid:
                previous=db.execute('SELECT body FROM dm_messages WHERE thread_id=? AND sender_id=? AND client_nonce=?',(thread['id'],uid,nonce)).fetchone()
                if not previous or previous['body']!=body:abort(409,description='Wait for this message request to be accepted before sending more.')
            else:abort(409,description='Open Messages to review this conversation first.')
        return respond(thread)
    @app.post('/messages/<thread_id>/send')
    @protected
    def messaging_send(thread_id):
        uid=current_user();db=core.get_db();body,nonce=content();limit=limited('send',60,60)
        if limit is not None:return limit
        with db:
            db.execute('BEGIN IMMEDIATE');thread=thread_for(db,thread_id,uid)
            if not send_allowed(db,thread,uid):abort(403,description='Sending is not available for this conversation.')
            insert_message(db,thread,uid,body,nonce)
        return respond(thread)
    @app.post('/messages/<thread_id>/decision')
    @protected
    def messaging_decision(thread_id):
        uid=current_user();db=core.get_db();action=request.form.get('action');limit=limited('decision',60)
        if limit is not None:return limit
        if action not in ('accept','decline','mute','unmute','pause','resume','block'):abort(400)
        with db:
            db.execute('BEGIN IMMEDIATE');thread=thread_for(db,thread_id,uid);peer=peer_id(thread,uid)
            if action in ('accept','decline'):
                if thread['state']!='pending' or thread['requested_by']==uid:abort(409)
                if action=='accept' and (community.blocked(db,uid,peer) or not ages.contact(db,uid,peer)):abort(403)
                db.execute('UPDATE dm_threads SET state=? WHERE id=?',('accepted' if action=='accept' else 'declined',thread['id']))
            elif action in ('mute','unmute'):db.execute('UPDATE dm_members SET muted=? WHERE thread_id=? AND user_id=?',(int(action=='mute'),thread['id'],uid))
            elif action in ('pause','resume'):db.execute('UPDATE dm_members SET paused=? WHERE thread_id=? AND user_id=?',(int(action=='pause'),thread['id'],uid))
            elif peer:
                db.execute('INSERT OR IGNORE INTO user_blocks(user_id,target_id) VALUES (?,?)',(uid,peer))
                db.execute('DELETE FROM friend_requests WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)',(uid,peer,peer,uid))
                db.execute('DELETE FROM top_friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)',(uid,peer,peer,uid))
                db.execute('UPDATE follows SET revoked=1 WHERE (follower_id=? AND followed_id=?) OR (follower_id=? AND followed_id=?)',(uid,peer,peer,uid))
            db.execute("UPDATE notifications SET read_at=COALESCE(read_at,CURRENT_TIMESTAMP) WHERE user_id=? AND kind='messages' AND path=?",(uid,'/messages/'+thread_id))
        return redirect(url_for('messaging_thread',thread_id=thread_id),code=303)
    @app.post('/messages/<thread_id>/read')
    @protected
    def messaging_read(thread_id):
        uid=current_user();db=core.get_db()
        with db:
            db.execute('BEGIN IMMEDIATE');thread=thread_for(db,thread_id,uid)
            row=db.execute('SELECT id FROM dm_messages WHERE public_id=? AND thread_id=?',(request.form.get('through',''),thread['id'])).fetchone()
            if not row:abort(400)
            db.execute('UPDATE dm_members SET read_id=max(read_id,?) WHERE thread_id=? AND user_id=?',(row['id'],thread['id'],uid))
            pending=db.execute('SELECT 1 FROM dm_messages x JOIN dm_members m ON m.thread_id=x.thread_id WHERE m.user_id=? AND x.thread_id=? AND x.id>m.read_id AND x.sender_id!=? LIMIT 1',(uid,thread['id'],uid)).fetchone()
            if not pending:db.execute("UPDATE notifications SET read_at=COALESCE(read_at,CURRENT_TIMESTAMP) WHERE user_id=? AND kind='messages' AND path=?",(uid,'/messages/'+thread_id))
        if request.accept_mimetypes.best=='application/json':
            notifications=sum(community.notification_visible(db,r,uid) for r in db.execute('SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL',(uid,)))
            return jsonify(ok=True,unread=min(unread_threads(db,uid),100),notifications=notifications)
        return redirect(url_for('messaging_thread',thread_id=thread_id),code=303)
    @app.get('/messages/overview')
    @protected
    def messaging_overview():
        limit=limited('poll',1200)
        if limit is not None:return limit
        uid=current_user();db=core.get_db()
        return jsonify(buddies=buddy_data(db,uid),unread=min(unread_threads(db,uid),100))
    @app.get('/messages/<thread_id>/updates')
    @protected
    def messaging_updates(thread_id):
        limit=limited('poll',1200)
        if limit is not None:return limit
        uid=current_user();db=core.get_db();thread=thread_for(db,thread_id,uid);after=request.args.get('after');bound=0
        if after:
            row=db.execute('SELECT id FROM dm_messages WHERE public_id=? AND thread_id=?',(after,thread['id'])).fetchone()
            if not row:abort(400)
            bound=row['id']
        rows=db.execute('SELECT * FROM dm_messages WHERE thread_id=? AND id>? ORDER BY id LIMIT 51',(thread['id'],bound)).fetchall()
        removed=[r[0] for r in db.execute('SELECT public_id FROM dm_messages WHERE thread_id=? AND hidden=1 ORDER BY id DESC LIMIT 200',(thread['id'],))]
        payload=[]
        for row in rows[:50]:
            item=message_payload(row,uid)
            if not item['mine']:item['report_url']=url_for('messaging_report',thread_id=thread_id,message_id=item['key'])
            payload.append(item)
        return jsonify(messages=payload,removed=removed,more=len(rows)>50,state=thread['state'],can_send=send_allowed(db,thread,uid),unread=min(unread_threads(db,uid),100))
    @app.post('/messages/settings')
    @protected
    def messaging_settings():
        uid=current_user();db=core.get_db();inbox=request.form.get('inbox');presence=request.form.get('presence');away=request.form.get('away','').strip()
        if inbox not in INBOXES or presence not in STATUSES or len(away)>140 or any(ord(c)<32 or ord(c)==127 for c in away):abort(400)
        limit=limited('settings',60)
        if limit is not None:return limit
        db.execute('INSERT INTO dm_settings(user_id,inbox,presence,away,active_at) VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET inbox=excluded.inbox,presence=excluded.presence,away=excluded.away,active_at=excluded.active_at',(uid,inbox,presence,away,int(time.time()) if presence!='invisible' else 0));db.commit()
        flash('Message and presence settings saved.','success');return redirect(url_for('messaging_home'),code=303)
    @app.post('/messages/presence')
    @protected
    def messaging_presence():
        limit=limited('presence',180)
        if limit is not None:return limit
        db=core.get_db();uid=current_user();db.execute("UPDATE dm_settings SET active_at=? WHERE user_id=? AND presence!='invisible'",(int(time.time()),uid));db.commit();return jsonify(ok=True)
    @app.post('/messages/<thread_id>/report/<message_id>')
    @protected
    def messaging_report(thread_id,message_id):
        uid=current_user();db=core.get_db();reason=request.form.get('reason','').strip()
        if not 1<=len(reason)<=1000:abort(400,description='Explain why you are reporting this message.')
        limit=limited('report',10)
        if limit is not None:return limit
        with db:
            db.execute('BEGIN IMMEDIATE');thread=thread_for(db,thread_id,uid)
            message=db.execute('SELECT * FROM dm_messages WHERE public_id=? AND thread_id=?',(message_id,thread['id'])).fetchone()
            if not message or message['sender_id']==uid:abort(404)
            prior=db.execute('SELECT id FROM dm_reports WHERE message_id=? AND reporter_id=?',(message['id'],uid)).fetchone()
            if not prior:
                case=community.ensure_case(db,'message',message['id'],message['sender_id'])
                rid=db.execute('INSERT INTO dm_reports(thread_id,message_id,reporter_id,author_id,reason,case_id) VALUES (?,?,?,?,?,?)',(thread['id'],message['id'],uid,message['sender_id'],reason,case)).lastrowid
                db.execute("INSERT INTO case_links VALUES (?,'message-report',?)",(case,rid))
                db.execute("UPDATE moderation_cases SET status='open',closed_at=NULL WHERE id=?",(case,))
                snapshot=json.dumps(dict(source_type='message',source_id=message['public_id'],content=dict(user_id=message['sender_id'],target_user_id=uid,body=message['body'],created_at=message['created_at']),report_reason=reason,preserved_files=[]),ensure_ascii=False,sort_keys=True)
                db.execute("INSERT INTO case_evidence(case_id,source_type,source_id,snapshot,sha256) VALUES (?,'message',?,?,?)",(case,message['id'],snapshot,community.digest(snapshot)))
        flash('Reported message submitted for staff review. No other messages were included.','success')
        return redirect(url_for('messaging_thread',thread_id=thread_id),code=303)
    @app.route('/manage/messages/reports',methods=['GET','POST'])
    def messaging_reports():
        actor=core.require_staff_permission('review_reports');db=core.get_db()
        if request.method=='POST':
            helpers['csrf']();rid=request.form.get('report_id','');decision=request.form.get('decision');reason=request.form.get('reason','').strip()
            if decision not in ('keep','remove') or not 1<=len(reason)<=1000:abort(400)
            with db:
                db.execute('BEGIN IMMEDIATE');report=db.execute('SELECT * FROM dm_reports WHERE id=?',(rid,)).fetchone()
                if not report or report['status']!='open':abort(409)
                if actor in (report['reporter_id'],report['author_id']):abort(403,description='Another staff member must review reports involving your messages.')
                if decision=='remove':db.execute('UPDATE dm_messages SET hidden=1 WHERE id=?',(report['message_id'],))
                db.execute("UPDATE dm_reports SET status='closed',outcome=?,reviewer_id=?,decision=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(decision,actor,reason,report['id']))
                db.execute('INSERT INTO case_notes(case_id,actor_id,body) VALUES (?,?,?)',(report['case_id'],actor,'Message report #'+str(report['id'])+': '+decision+'. '+reason))
            flash('Decision recorded. Complete the linked case disposition separately.','success');return redirect(url_for('messaging_reports'),code=303)
        rows=db.execute('SELECT r.*,a.handle AS author,b.handle AS reporter FROM dm_reports r LEFT JOIN users a ON a.id=r.author_id LEFT JOIN users b ON b.id=r.reporter_id ORDER BY r.id DESC LIMIT 100').fetchall()
        return render_template('message_reports.html',reports=rows)
