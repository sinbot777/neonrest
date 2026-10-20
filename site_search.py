"""Signed-in search with the same content boundaries as ordinary site listings."""
import json
from flask import abort, make_response, redirect, render_template, request, session, url_for
from neonrest import age_policy as ages, circles, community_features as community

SCOPES = ('username', 'posts', 'circles', 'city')
LABELS = {'username': 'Username', 'posts': 'Posts', 'circles': 'Circles', 'city': 'City'}


def selections():
    if 'scopes_present' not in request.args:
        return set(SCOPES)
    return set(request.args.getlist('scope')) & set(SCOPES)


def register(app, core):
    @app.context_processor
    def search_context():
        return {'search_scope_labels': LABELS, 'search_selected_scopes': selections() if request.endpoint == 'site_search' else set(SCOPES)}

    @app.get('/search')
    def site_search():
        uid = session.get('user_id')
        if not uid:
            return redirect(url_for('login'))
        query = request.args.get('q', '').strip()
        selected = selections()
        try:
            page = int(request.args.get('page', '1'))
        except ValueError:
            abort(400)
        if not 1 <= page <= 1000 or len(query) > 120:
            abort(400)
        groups = []
        message = ''
        has_more = False
        if not selected:
            message = 'Choose at least one search category.'
        elif len(query) < 2:
            message = 'Enter at least two characters to search.'
        else:
            limited = app.extensions['community_auth_helpers']['limited']('site_search', 60, 60)
            if limited:
                return limited
            db = core.get_db()
            def pattern(value):
                return '%' + value.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
            def circle_visible(cid):
                circle = db.execute('SELECT * FROM circles WHERE id=?', (cid,)).fetchone()
                return int(bool(circle and circles.info_allowed(db, circle, uid)))
            def location_visible(owner):
                if ages.limited_staff_profile(db, owner, uid):
                    return 0
                fields = json.loads(community.settings(db, owner)['field_audiences'])
                audience = fields.get('location', 'public')
                return int(owner == uid or audience == 'public' or audience == 'friends' and (community.friends(db, owner, uid) or ages.family(db, owner, uid)))
            db.create_function('search_circle_visible', 1, circle_visible)
            db.create_function('search_location_visible', 1, location_visible)
            from .search_index import candidates
            offset = (page - 1) * 20
            for kind in SCOPES:
                if kind not in selected:
                    continue
                if kind in ('username', 'city'):
                    field = 'handle' if kind == 'username' else 'location'
                    term = query[1:] if kind == 'username' and query.startswith('@') else query
                    candidate, match_args = candidates('users',field,term,'u',db)
                    extra = ' AND search_location_visible(u.id)=1' if kind == 'city' else ''
                    rows = db.execute('SELECT u.id,u.handle' + (',u.location' if kind == 'city' else '') + ' FROM users u WHERE u.'+field+" LIKE ? ESCAPE '!' AND community_profile_visible(u.id)=1 AND community_member_visible(u.id)=1 AND NOT EXISTS(SELECT 1 FROM account_disables ad WHERE ad.user_id=u.id AND ad.disabled=1) AND NOT EXISTS(SELECT 1 FROM account_safety a WHERE a.user_id=u.id AND a.inactive=1)"+extra+candidate+' ORDER BY u.handle COLLATE NOCASE,u.id LIMIT 21 OFFSET ?', [pattern(term)]+match_args+[offset]).fetchall()
                    items = [{'title': row['handle'], 'url': url_for('user_by_handle',handle=row['handle'].lstrip('@')), 'text': row['location'] if kind == 'city' else ''} for row in rows[:20]]
                elif kind == 'posts':
                    candidate, match_args = candidates('posts','content',query,'p',db)
                    rows = db.execute("SELECT p.id,p.content,p.created_at,u.handle FROM posts p JOIN users u ON u.id=p.user_id WHERE p.content LIKE ? ESCAPE '!' AND community_post_visible(p.id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id)"+candidate+" ORDER BY p.created_at DESC,p.id DESC LIMIT 21 OFFSET ?", [pattern(query)]+match_args+[offset]).fetchall()
                    items = [{'title':'Post by '+row['handle'], 'url':url_for('post_detail',post_id=row['id']), 'text':row['content'][:240]+('…' if len(row['content'])>240 else ''), 'date':row['created_at']} for row in rows[:20]]
                else:
                    candidate, match_args = candidates('circles',None,query,'circles',db)
                    rows = db.execute("SELECT * FROM circles WHERE (name LIKE ? ESCAPE '!' OR description LIKE ? ESCAPE '!') AND search_circle_visible(id)=1"+candidate+" ORDER BY name COLLATE NOCASE,id LIMIT 21 OFFSET ?", [pattern(query),pattern(query)]+match_args+[offset]).fetchall()
                    items = [{'title':circles.label(row), 'url':url_for('circle_page',circle_id=row['id']), 'text':row['description']} for row in rows[:20]]
                more = len(rows)>20
                has_more |= more
                groups.append({'kind':kind,'label':LABELS[kind], 'items':items, 'more':more})
        def page_url(number):
            return url_for('site_search',q=query,scopes_present='1',scope=[kind for kind in SCOPES if kind in selected],page=number)
        response = make_response(render_template('search.html',query=query,groups=groups,message=message,page=page,has_more=has_more,previous_url=page_url(page-1) if page>1 else None,next_url=page_url(page+1) if has_more and page<1000 else None))
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response
