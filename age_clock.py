"""Per-account local birthday clocks, separate from editable display timezones."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from flask import request,session,abort,redirect,url_for,render_template,flash

def valid_zone(value):
    try:
        if not isinstance(value,str) or len(value)>80:return None
        ZoneInfo(value);return value
    except (ValueError,ZoneInfoNotFoundError):return None

def local_date(zone,instant=None):
    instant=instant or datetime.now(timezone.utc)
    if instant.tzinfo is None:raise ValueError('Clock requires an aware instant')
    return instant.astimezone(ZoneInfo(valid_zone(zone) or 'UTC')).date()

def initialize(db):
    db.executescript("""CREATE TABLE IF NOT EXISTS age_clocks(user_id INTEGER PRIMARY KEY,zone TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0);
    CREATE TRIGGER IF NOT EXISTS immutable_age_clock BEFORE UPDATE ON age_clocks WHEN OLD.confirmed=1 AND (NEW.zone IS NOT OLD.zone OR NEW.confirmed!=1) BEGIN SELECT RAISE(ABORT,'Birthday timezone is locked'); END;""")
    for row in db.execute('SELECT id,timezone FROM users').fetchall():
        zone=valid_zone(row['timezone'])
        db.execute('INSERT OR IGNORE INTO age_clocks VALUES (?,?,?)',(row['id'],zone or 'UTC',int(bool(zone))))
    protect_history(db)
    db.commit()

def date_for(db,uid,instant=None):
    row=db.execute('SELECT zone FROM age_clocks WHERE user_id=?',(uid,)).fetchone()
    return local_date(row[0] if row else 'UTC',instant)

def protect_history(db,target=None):
    from neonrest_sandbox.age_policy import age_of
    for table,protected,column in [('posts','protected_age_posts','post_id'),('comments','protected_age_comments','comment_id')]:
        sql='SELECT p.id,p.user_id,p.created_at,u.dob FROM '+table+' p JOIN users u ON u.id=p.user_id'+(' WHERE p.user_id=?' if target else '')
        for row in db.execute(sql,(target,) if target else ()).fetchall():
            try:
                instant=datetime.fromisoformat(str(row['created_at']))
                if instant.tzinfo is None:instant=instant.replace(tzinfo=timezone.utc)
                age=age_of(row['dob'],date_for(db,row['user_id'],instant))
                if age is not None and age<18:db.execute('INSERT OR IGNORE INTO '+protected+'('+column+') VALUES (?)',(row['id'],))
            except (ValueError,TypeError):continue

def register(app,core):
    with app.app_context():initialize(core.get_db())
    @app.post('/account/age/clock')
    def age_clock_setup():
        uid=session.get('user_id')
        if not uid:abort(401)
        helpers=app.extensions['community_auth_helpers'];helpers['csrf']()
        if not helpers['fresh']():return redirect(url_for('community_reauth',next=url_for('age_setup')))
        target=request.form.get('child_id',type=int) or uid
        if target!=uid:
            from neonrest_sandbox.age_policy import approved_parent
            if not approved_parent(core.get_db(),uid,target):abort(403)
        zone=valid_zone(request.form.get('zone','').strip())
        if not zone:abort(400,description='Choose a valid IANA timezone, such as America/Los_Angeles.')
        db=core.get_db();row=db.execute('SELECT confirmed FROM age_clocks WHERE user_id=?',(target,)).fetchone()
        if row and row[0]:abort(400,description='Your birthday timezone is already confirmed. Contact support to request review.')
        with db:
            db.execute('INSERT INTO age_clocks VALUES (?,?,1) ON CONFLICT(user_id) DO UPDATE SET zone=excluded.zone,confirmed=1',(target,zone))
            db.execute("INSERT INTO age_policy_events(actor_id,child_id,action) VALUES (?,?,'birthday-timezone-confirmed')",(uid,target))
            protect_history(db,target)
        flash('Birthday timezone confirmed. Display timezone changes do not change age permissions.','success')
        return redirect(url_for('family_settings' if target!=uid else 'age_setup'))
    @app.context_processor
    def birthday_clock_context():
        uid=session.get('user_id');row=core.get_db().execute('SELECT zone,confirmed FROM age_clocks WHERE user_id=?',(uid,)).fetchone() if uid else None
        clocks={r['user_id']:r for r in core.get_db().execute("SELECT c.* FROM age_clocks c JOIN family_links f ON f.child_id=c.user_id WHERE f.parent_id=? AND f.status='approved'",(uid,))} if uid else {}
        return {'birthday_clock':row,'family_birthday_clocks':clocks}
