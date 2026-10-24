"""Page discovery, follows, private invitations and consented ownership transfer."""
import secrets,time
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
from . import identity_pages as pages,age_policy as ages
from .community_features import blocked


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS page_followers(page_id TEXT NOT NULL REFERENCES identity_pages(id),
        user_id INTEGER NOT NULL REFERENCES users(id),created_at INTEGER NOT NULL,PRIMARY KEY(page_id,user_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS page_following ON page_followers(user_id,page_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS page_invitations(id TEXT PRIMARY KEY,page_id TEXT NOT NULL REFERENCES identity_pages(id),
        sender_id INTEGER NOT NULL REFERENCES users(id),recipient_id INTEGER NOT NULL REFERENCES users(id),
        purpose TEXT NOT NULL CHECK(purpose IN ('editor','manager','transfer')),
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','declined','revoked')),
        expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL)''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS page_invitation_pending ON page_invitations(page_id,recipient_id,purpose) WHERE status='pending'")
    db.execute('CREATE INDEX IF NOT EXISTS page_invitation_recipient ON page_invitations(recipient_id,status,created_at DESC)')


def public_read(db,page,uid):
    return page['state']=='published' and not pages.hidden(db,page['id']) and (page['kind']!='business' or pages.business_entitled(db,page)) and pages.visible(db,page,uid)


def follow(db,uid,page_id,enabled):
    page=pages.get(db,page_id)
    if not enabled:
        db.execute('DELETE FROM page_followers WHERE page_id=? AND user_id=?',(page_id,uid));return
    pages.require_eligible(db,uid,'creative')
    moderation=db.execute('SELECT interaction_restricted FROM user_moderation WHERE user_id=?',(uid,)).fetchone()
    if moderation and moderation[0]:raise pages.PageError('Interactions are restricted.',403)
    if not public_read(db,page,uid):raise pages.PageError('Page unavailable.',404)
    if db.execute('SELECT COUNT(*) FROM page_followers WHERE user_id=?',(uid,)).fetchone()[0]>=2000:
        raise pages.PageError('The following limit is 2,000 pages.',409)
    db.execute('INSERT OR IGNORE INTO page_followers VALUES (?,?,?)',(page_id,uid,int(time.time())))


def invite(db,uid,page_id,target,purpose):
    page=pages.get(db,page_id);pages.require_role(db,page,uid,('owner',))
    pages.require_eligible(db,target,page['kind'])
    if purpose not in ('editor','manager','transfer') or target==uid:raise pages.PageError('Choose a different eligible member and a valid invitation type.')
    if page['kind']=='business':raise pages.PageError('Business delegation and transfer await billing ownership integration.',409)
    if blocked(db,uid,target) or not ages.contact(db,uid,target):raise pages.PageError('Current contact permissions do not allow this invitation.',403)
    if db.execute("SELECT COUNT(*) FROM page_invitations WHERE sender_id=? AND status='pending' AND expires_at>?",(uid,int(time.time()))).fetchone()[0]>=50:
        raise pages.PageError('You have 50 pending invitations.',409)
    db.execute("UPDATE page_invitations SET status='revoked' WHERE page_id=? AND recipient_id=? AND purpose=? AND status='pending'",(page_id,target,purpose))
    ref=secrets.token_urlsafe(18);now=int(time.time())
    db.execute('INSERT INTO page_invitations(id,page_id,sender_id,recipient_id,purpose,expires_at,created_at) VALUES (?,?,?,?,?,?,?)',(ref,page_id,uid,target,purpose,now+7*86400,now))
    pages.event(db,page_id,uid,'invitation:'+purpose)
    return ref


def respond(db,uid,ref,decision):
    invitation=db.execute('SELECT * FROM page_invitations WHERE id=?',(ref,)).fetchone()
    if not invitation or uid not in (invitation['recipient_id'],invitation['sender_id']):raise pages.PageError('Invitation unavailable.',404)
    if invitation['status']!='pending':raise pages.PageError('This invitation is no longer pending.',409)
    if decision=='revoke' and uid==invitation['sender_id']:
        status='revoked'
    elif uid==invitation['recipient_id'] and decision=='decline':status='declined'
    elif uid==invitation['recipient_id'] and decision=='accept':
        page=pages.get(db,invitation['page_id']);sender=invitation['sender_id']
        if invitation['expires_at']<=time.time() or page['owner_id']!=sender:raise pages.PageError('Invitation expired or ownership changed.',409)
        pages.require_eligible(db,uid,page['kind']);pages.require_role(db,page,sender,('owner',))
        if blocked(db,sender,uid) or not ages.contact(db,sender,uid):raise pages.PageError('Current contact permissions no longer allow acceptance.',403)
        if invitation['purpose']=='transfer':
            if db.execute('SELECT COUNT(*) FROM identity_pages WHERE owner_id=?',(uid,)).fetchone()[0]>=20:raise pages.PageError('The recipient already owns 20 pages.',409)
            db.execute('UPDATE identity_pages SET owner_id=?,revision=revision+1,updated_at=? WHERE id=?',(uid,int(time.time()),page['id']))
            db.execute('DELETE FROM identity_page_members WHERE page_id=? AND user_id=?',(page['id'],uid))
            db.execute("UPDATE page_invitations SET status='revoked' WHERE page_id=? AND status='pending' AND id!=?",(page['id'],ref))
            # Prior owners receive no automatic continuing access.
        else:pages.set_member(db,sender,page['id'],uid,invitation['purpose'])
        status='accepted'
    else:raise pages.PageError('Invalid invitation action.',403)
    db.execute('UPDATE page_invitations SET status=? WHERE id=?',(status,ref));pages.event(db,invitation['page_id'],uid,'invitation:'+status)


def search(db,uid,query='',before=2**63-1,limit=21):
    db.create_function('page_discoverable',1,lambda pid:int(public_read(db,pages.get(db,pid),uid)))
    pattern='%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
    return db.execute("SELECT * FROM identity_pages WHERE rowid<? AND state='published' AND (handle LIKE ? ESCAPE '!' OR name LIKE ? ESCAPE '!' OR description LIKE ? ESCAPE '!') AND page_discoverable(id)=1 ORDER BY rowid DESC LIMIT ?",(before,pattern,pattern,pattern,limit)).fetchall()


def export_user(db,uid):
    return {'following':[dict(r) for r in db.execute('SELECT * FROM page_followers WHERE user_id=?',(uid,))],
        'invitations':[dict(r) for r in db.execute('SELECT * FROM page_invitations WHERE sender_id=? OR recipient_id=?',(uid,uid))]}


def register(app,core):
    bp=Blueprint('page_social',__name__)
    with app.app_context():initialize(core.get_db());core.get_db().commit()
    @bp.errorhandler(pages.PageError)
    def error(e):return render_template('identity_page_error.html',message=str(e)),e.status
    def actor():
        uid=session.get('user_id')
        if not uid:abort(401)
        pages.require_eligible(core.get_db(),uid,'creative');return uid
    def write(fresh=False):
        app.extensions['community_auth_helpers']['csrf']()
        if fresh and not app.extensions['community_auth_helpers']['fresh']():return redirect(url_for('community_reauth',next=request.path))
    def link(page):return url_for('identity_pages.creative' if page['kind']=='creative' else 'identity_pages.business',slug=page['handle'][1:])
    @app.context_processor
    def context():
        return {'page_is_followed':lambda page:bool(session.get('user_id') and core.get_db().execute('SELECT 1 FROM page_followers WHERE page_id=? AND user_id=?',(page['id'],session['user_id'])).fetchone())}
    @bp.get('/pages/explore')
    def explore():
        uid=actor();q=request.args.get('q','').strip();before=request.args.get('before',2**63-1,type=int)
        if len(q)>120 or before is None or not 0<before<2**63:abort(400)
        rows=search(core.get_db(),uid,q,before,21)
        # Page IDs are opaque; use the selected row's SQLite rowid only for the cursor.
        older=None
        if len(rows)>20:older=core.get_db().execute('SELECT rowid FROM identity_pages WHERE id=?',(rows[19]['id'],)).fetchone()[0]
        return render_template('page_discovery.html',pages=rows[:20],page_link=link,q=q,older_url=url_for('page_social.explore',q=q,before=older) if older else None)
    @bp.post('/pages/<page_id>/follow')
    def following(page_id):
        uid=actor();response=write()
        if response is not None:return response
        enabled=request.form.get('state')
        if enabled not in ('follow','unfollow'):abort(400)
        with core.get_db():follow(core.get_db(),uid,page_id,enabled=='follow')
        return redirect(url_for('page_social.feed'))
    @bp.get('/pages/feed')
    def feed():
        uid=actor();db=core.get_db();before=request.args.get('before',2**63-1,type=int)
        if before is None or not 0<before<2**63:abort(400)
        db.create_function('followed_page_post_visible',1,lambda pid:int((lambda post:bool(post and public_read(db,pages.get(db,post['page_id']),uid) and pages.post_visible(db,pages.get(db,post['page_id']),post,uid)))(db.execute('SELECT * FROM identity_page_posts WHERE id=?',(pid,)).fetchone())))
        rows=db.execute('''SELECT x.*,p.handle,p.kind,p.name FROM identity_page_posts x JOIN identity_pages p ON p.id=x.page_id
            JOIN page_followers f ON f.page_id=p.id AND f.user_id=? WHERE x.id<? AND followed_page_post_visible(x.id)=1 ORDER BY x.id DESC LIMIT 21''',(uid,before)).fetchall()
        return render_template('page_following_feed.html',posts=rows[:20],page_link=link,older_url=url_for('page_social.feed',before=rows[19]['id']) if len(rows)>20 else None)
    @bp.route('/pages/<page_id>/team',methods=['GET','POST'])
    def team(page_id):
        uid=actor();db=core.get_db();page=pages.get(db,page_id);pages.require_role(db,page,uid,('owner',))
        if request.method=='POST':
            response=write(True)
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE')
                if request.form.get('action')=='remove':pages.set_member(db,uid,page_id,request.form.get('member_id',type=int),None)
                else:
                    if request.form.get('purpose')=='transfer' and request.form.get('confirm_transfer')!='yes':raise pages.PageError('Confirm the ownership-transfer consequence before inviting.')
                    target=db.execute("SELECT id FROM users WHERE handle=? COLLATE NOCASE",('@'+request.form.get('handle','').strip().lstrip('@'),)).fetchone()
                    if not target:raise pages.PageError('Eligible member unavailable.',404)
                    invite(db,uid,page_id,target['id'],request.form.get('purpose'))
            return redirect(url_for('page_social.team',page_id=page_id))
        members=db.execute('SELECT m.*,u.handle FROM identity_page_members m JOIN users u ON u.id=m.user_id WHERE m.page_id=?',(page_id,)).fetchall()
        pending=db.execute("SELECT i.*,u.handle FROM page_invitations i JOIN users u ON u.id=i.recipient_id WHERE page_id=? AND status='pending' ORDER BY created_at DESC LIMIT 50",(page_id,)).fetchall()
        return render_template('page_team.html',page=page,members=members,invitations=pending)
    @bp.route('/pages/invitations',methods=['GET','POST'])
    def invitations():
        uid=actor();db=core.get_db()
        if request.method=='POST':
            response=write(True)
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE');respond(db,uid,request.form.get('invitation_id'),request.form.get('decision'))
            return redirect(url_for('page_social.invitations'))
        rows=db.execute('''SELECT i.*,p.handle,p.name FROM page_invitations i JOIN identity_pages p ON p.id=i.page_id
            WHERE (recipient_id=? OR sender_id=?) AND status='pending' AND expires_at>? ORDER BY created_at DESC LIMIT 100''',(uid,uid,int(time.time()))).fetchall()
        rows=[row for row in rows if not blocked(db,row['sender_id'],row['recipient_id']) and ages.contact(db,row['sender_id'],row['recipient_id'])]
        return render_template('page_invitations.html',invitations=rows)
    @bp.after_request
    def private(response):response.headers['Cache-Control']='private, no-store';return response
    app.register_blueprint(bp)
