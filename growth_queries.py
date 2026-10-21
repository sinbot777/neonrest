"""Bounded timeline hydration and comment windows; visibility precedes LIMIT."""
from flask import abort, request, url_for


def timeline_rows(db, page, post_id=None, circle_id=None, query='', pinned_id=None, vibe_id=None):
    where=["NOT EXISTS(SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id)","community_post_visible(p.id)=1"]
    args=[]
    if post_id is not None:
        where.append('p.id=?');args.append(post_id)
    if circle_id is not None:
        where.append('p.id IN (SELECT post_id FROM circle_posts WHERE circle_id=?)');args.append(circle_id)
    if vibe_id is not None:
        where.append('EXISTS(SELECT 1 FROM post_vibes pv WHERE pv.post_id=p.id AND pv.vibe_id=?)');args.append(vibe_id)
    if query:
        where.append("p.content LIKE ? ESCAPE '!'")
        args.append('%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%')
    predicate=' AND '.join(where)
    # Read the pin separately so an expression sort cannot scan the entire Feed.
    pin=db.execute('SELECT p.id FROM posts p WHERE p.id=? AND '+predicate,[pinned_id]+args).fetchone() if pinned_id is not None else None
    offset=(page-1)*20
    limit=21
    if pin:
        predicate+=' AND p.id<>?';args.append(pin['id'])
        offset=max(0,offset-1)
        if page==1:limit-=1
    ids=[r['id'] for r in db.execute('SELECT p.id FROM posts p WHERE '+predicate+' ORDER BY p.created_at DESC,p.id DESC LIMIT ? OFFSET ?',args+[limit,offset])]
    if pin and page==1:ids.insert(0,pin['id'])
    more=len(ids)>20
    ids=ids[:20]
    if not ids:
        if page>1:abort(404)
        return [],False
    # Only this page receives author metadata and Vibe aggregation.
    rows=db.execute("SELECT p.*,u.handle,u.handle AS author_handle,u.codename AS author_codename,u.avatar_path,(SELECT GROUP_CONCAT(v.name,', ') FROM post_vibes pv JOIN vibes v ON v.id=pv.vibe_id WHERE pv.post_id=p.id) AS vibes FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id IN ("+','.join('?' for _ in ids)+')',ids).fetchall()
    by_id={row['id']:row for row in rows}
    return [by_id[pid] for pid in ids],more


def comment_windows(db, post_ids, identifiers, single=False):
    output=[];navigation={}
    visible="NOT EXISTS(SELECT 1 FROM moderated_comments mc WHERE mc.comment_id=c.id) AND community_member_visible(c.user_id)=1 AND age_comment_visible(c.id)=1"
    for pid in post_ids:
        size=50 if single else 5
        after=request.args.get('comments_after') if single else None
        before=request.args.get('comments_before') if single else None
        target=request.args.get('comment') if single else None
        if sum(bool(x) for x in (after,before,target))>1:abort(400)
        boundary=after or before or target
        args=[pid];predicate='';descending=bool(before) or not single
        if boundary:
            try:cid=identifiers.resolve(db,'comment',boundary)
            except (ValueError,TypeError):
                try:cid=identifiers.resolve(db,'comment',boundary,anchor=True)
                except (ValueError,TypeError):abort(404)
            row=db.execute('SELECT c.created_at,c.id FROM comments c WHERE c.id=? AND c.post_id=? AND '+visible,(cid,pid)).fetchone()
            if row is None:abort(404)
            predicate=' AND (c.created_at,c.id) '+('<' if before else '>=' if target else '>')+' (?,?)'
            args.extend((row['created_at'],row['id']))
        rows=db.execute('SELECT c.id,c.post_id,c.user_id,c.content,c.parent_comment_id,c.last_edited,c.created_at,u.handle,u.avatar_path FROM comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? AND '+visible+predicate+' ORDER BY c.created_at '+('DESC,c.id DESC' if descending else 'ASC,c.id ASC')+' LIMIT ?',args+[size+1]).fetchall()
        more=len(rows)>size;rows=rows[:size]
        if descending:rows.reverse()
        public=identifiers.public(db,'post',pid)
        def link(key,row):return url_for('post_detail',post_id=public,**{key:identifiers.public(db,'comment',row['id'])})+'#comments-'+public
        navigation[public]={'more':more if not single else False,'all':url_for('post_detail',post_id=public)+'#comments-'+public,'previous':link('comments_before',rows[0]) if single and rows and (boundary and not before or before and more) else None,'next':link('comments_after',rows[-1]) if single and rows and (before or more) else None}
        output.extend(rows)
    return output,navigation


def install(db):
    db.execute('CREATE INDEX IF NOT EXISTS idx_posts_created_id ON posts(created_at DESC,id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_comments_post_created ON comments(post_id,created_at,id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_post_vibes_vibe_post ON post_vibes(vibe_id,post_id)')
    db.commit()
