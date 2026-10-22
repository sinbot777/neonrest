"""Owner-run, idempotent publication of the approved HelpLine onboarding copy.

Ordinary public posts only: no session forging, roles or staff-announcement bypass.
Call after a database backup and explicit owner authorization to publish.
"""
from datetime import datetime,timezone
POSTS = ['## Welcome to Neonrest\n\nWelcome! Start with your profile: choose a handle, optional codename, avatar, and the details you want to share. Your actual name and date of birth stay private. Optional public profile fields are visible wherever your profile is available, so leave anything blank that you would rather keep to yourself. The User guide is linked at the bottom of every page.', "## Your welcome friend and Top 9\n\nYou may start with @brendoom as a welcome friend and in Top 9. You can rearrange Top 9, remove the entry, or remove the friendship from Friends. It won't be added back just because you visit again. Friendship doesn't bypass age or privacy rules; younger members may see a limited staff support profile rather than someone's personal content.", "## Vibes, Circles and audiences\n\nVibes connect conversations by interest or feeling. Fresh Starts is a good first stop. New Vibes normally open after three distinct people tag posts with the same name. Circles are separate communities with membership and their own rules. Before posting, check the audience. Tagging a Vibe doesn't publish a private post, and joining a Circle doesn't grant access to every person's content. Never share someone else's private content without permission.", "## Find your pace and get help\n\nFeed preferences let you choose a chronological view and save a default. Bookmark a post to find it again, or save a private text draft before publishing. Drafts don't save file attachments. Use a post's options menu to report a concern, and use Account safety for password and session controls. Contact ToS@neonrest.com for help; don't send passwords, authenticator codes, recovery codes or identity documents by email."]


def publish(db,identifiers,actor_id):
    from . import app as core
    from .utils.vibe_lifecycle import canonical_vibe,add_post_vibes
    from .vibe_tools import state
    from .age_policy import ready
    if actor_id!=1 or not core.has_staff_permission(db,actor_id,'moderate_posts'):
        raise ValueError('Only the site owner can publish this maintenance batch.')
    author=db.execute("SELECT id,verified FROM users WHERE lower(handle)='@helpline'").fetchone()
    if not author or not author['verified'] or not ready(db,author['id']):raise ValueError('HelpLine must be verified and age-ready.')
    uid=author['id']
    for table,flag in [('account_safety','inactive'),('account_disables','disabled'),('user_moderation','banned'),('user_moderation','posting_restricted')]:
        if db.execute('SELECT 1 FROM '+table+' WHERE user_id=? AND '+flag+'=1',(uid,)).fetchone():raise ValueError('HelpLine is unavailable.')
    vibe=canonical_vibe(db,'Fresh Starts')
    if not vibe or state(db,vibe['id'])['archived'] or db.execute('SELECT 1 FROM pending_vibes WHERE vibe_id=?',(vibe['id'],)).fetchone():raise ValueError('Fresh Starts is unavailable.')
    result=[]
    # Caller owns the transaction; this function never commits a partial batch.
    for content in POSTS:
        existing=db.execute('SELECT id FROM posts WHERE user_id=? AND target_user_id=? AND content=?',(uid,uid,content)).fetchall()
        if len(existing)>1:raise ValueError('Duplicate guidance needs owner review.')
        if existing:
            pid=existing[0]['id'];privacy=db.execute('SELECT audience FROM post_privacy WHERE post_id=?',(pid,)).fetchone()
            if not privacy or privacy[0]!='public' or not db.execute('SELECT 1 FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vibe['id'])).fetchone():raise ValueError('Existing guidance settings differ; no automatic overwrite.')
        else:
            pid=identifiers.next_post_key(db)
            db.execute("INSERT INTO posts(id,user_id,target_user_id,content,circle,created_at) VALUES(?,?,?,?,'public',?)",(pid,uid,uid,content,datetime.now(timezone.utc).replace(tzinfo=None).isoformat()))
            identifiers.ensure(db,'post',pid);db.execute("INSERT INTO post_privacy(post_id,audience) VALUES(?,'public')",(pid,));add_post_vibes(db,pid,['Fresh Starts'])
            db.execute("INSERT INTO operations_events(kind,detail) VALUES('onboarding-guidance',?)",('owner:'+str(actor_id)+':HelpLine:'+str(pid),))
        result.append(identifiers.public(db,'post',pid))
    return result
