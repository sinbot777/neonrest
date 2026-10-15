"""Staff-controlled account disabling, separate from deactivation, bans and erasure."""
from flask import request,redirect,url_for,abort,flash

def register(app,core):
    @app.post('/manage/users/<int:target_id>/disable')
    def staff_account_disable(target_id):
        actor=core.require_staff_permission('restrict_users')
        helper=app.extensions['community_auth_helpers'];helper['csrf']()
        if not helper['fresh']():return redirect(url_for('community_reauth',next=url_for('manage_user_detail',target_id=target_id)))
        db=core.get_db()
        if not db.execute('SELECT 1 FROM users WHERE id=?',(target_id,)).fetchone():abort(404)
        if target_id==1 or target_id==actor or db.execute('SELECT 1 FROM staff_roles WHERE user_id=?',(target_id,)).fetchone():abort(403)
        value=request.form.get('disabled');reason=request.form.get('reason','').strip()
        if value not in ('0','1') or not reason or len(reason)>500:abort(400)
        old=db.execute('SELECT disabled FROM account_disables WHERE user_id=?',(target_id,)).fetchone()
        if int(value)==(old[0] if old else 0):
            flash('No status change was needed.','info');return redirect(url_for('manage_user_detail',target_id=target_id))
        with db:
            db.execute('INSERT INTO account_disables(user_id,disabled,reason,updated_by) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET disabled=excluded.disabled,reason=excluded.reason,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',(target_id,int(value),reason,actor))
            db.execute('UPDATE reserved_accounts SET disabled=? WHERE user_id=?',(int(value),target_id))
            if value=='1':db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(target_id,))
            cur=db.execute('INSERT INTO moderation_events(actor_id,target_user_id,action,reason) VALUES (?,?,?,?)',(actor,target_id,'account-disable' if value=='1' else 'account-restore',reason))
            core.attach_event(db,cur.lastrowid)
        flash('Account disabled and hidden.' if value=='1' else 'Disable flag cleared. Other restrictions remain in effect.','success')
        return redirect(url_for('manage_user_detail',target_id=target_id))
