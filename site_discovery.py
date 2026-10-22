"""Canonical crawler hints. Public eligibility is rechecked without viewer privileges."""
import math
from pathlib import Path
from xml.etree.ElementTree import Element,SubElement,tostring
from flask import abort,make_response,request,send_file,url_for,render_template
from . import circles
from .social_previews import public_post

ORIGIN='https://www.neonrest.com'
NS='http://www.sitemaps.org/schemas/sitemap/0.9'
CHUNK=250
PAGES=('/', '/about', '/guide', '/explore', '/circles', '/privacy', '/terms', '/markdown-guide', '/advertising')

def xml(kind,locations):
    root=Element(kind,xmlns=NS)
    for location in locations:
        item=SubElement(root,'sitemap' if kind=='sitemapindex' else 'url')
        SubElement(item,'loc').text=ORIGIN+location
    response=make_response(b'<?xml version="1.0" encoding="UTF-8"?>\n'+tostring(root,encoding='utf-8'))
    response.headers.update({'Content-Type':'application/xml; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    return response

def register(app,core):
    sandbox='sandbox' in app.import_name
    @app.context_processor
    def advertising_environment():return {'advertising_sandbox':sandbox}
    @app.get('/advertising')
    def advertising_policy():return render_template('advertising_policy.html')
    @app.get('/ads.txt')
    def authorized_ad_sellers():
        if sandbox or request.script_root:abort(404)
        response=make_response('google.com, pub-6365201061952837, DIRECT, f08c47fec0942fa0\n')
        response.headers.update({'Content-Type':'text/plain; charset=utf-8','Cache-Control':'public, max-age=3600','X-Content-Type-Options':'nosniff'})
        return response
    @app.get('/favicon.ico')
    def site_favicon():
        return send_file(Path(app.static_folder)/'favicon.ico',mimetype='image/vnd.microsoft.icon',max_age=86400)
    @app.get('/robots.txt')
    def site_robots():
        if sandbox or request.script_root.rstrip('/')=='/sandbox':body='User-agent: *\nDisallow: /\n'
        else:
            private=('/sandbox','/account','/manage','/staff','/login','/logout','/signup','/password-reset','/verify','/recover','/family','/document','/privacy/submit','/analytics','/create_post','/edit_post','/delete_post')
            body='User-agent: *\n'+''.join('Disallow: '+p+'\n' for p in private)+'Sitemap: '+ORIGIN+'/sitemap.xml\n'
        response=make_response(body)
        response.headers.update({'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        return response
    @app.get('/sitemap.xml')
    def site_sitemap():
        if sandbox or request.script_root:return xml('urlset',[])
        db=core.get_db();locations=['/sitemap/pages.xml']
        # Index partition sizes bound each eligibility pass. Empty partitions expose no identities.
        for kind,table in (('posts','posts'),('circles','circles'),('vibes','vibes')):
            count=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            for page in range(1,math.ceil(count/CHUNK)+1):locations.append(url_for('site_sitemap_part',kind=kind,page=page))
        if len(locations)>50000:abort(503)
        return xml('sitemapindex',locations)
    @app.get('/sitemap/pages.xml')
    def site_sitemap_pages():
        return xml('urlset',[] if sandbox or request.script_root else PAGES)
    @app.get('/sitemap/<kind>-<int:page>.xml')
    def site_sitemap_part(kind,page):
        if kind not in ('posts','circles','vibes') or not 1<=page<=50000:abort(404)
        if sandbox or request.script_root:return xml('urlset',[])
        db=core.get_db();locations=[];offset=(page-1)*CHUNK
        # IDs only, in stable order; no request account is supplied to public eligibility.
        rows=db.execute('SELECT id FROM '+kind+' ORDER BY id LIMIT ? OFFSET ?',(CHUNK,offset)).fetchall()
        if not rows:abort(404)
        for row in rows:
            key=row['id']
            if kind=='posts':
                token=db.execute("SELECT public_id FROM public_ids WHERE kind='post' AND internal_id=?",(key,)).fetchone()
                if token and public_post(db,token[0]) is not None:locations.append(url_for('post_detail',post_id=token[0]))
            elif kind=='circles':
                circle=db.execute('SELECT * FROM circles WHERE id=?',(key,)).fetchone()
                token=db.execute('SELECT public_id FROM circle_public_ids WHERE circle_id=?',(key,)).fetchone()
                if token and circles.public_info_allowed(db,circle,None):locations.append(url_for('circle_page',circle_id=token[0]))
            else:
                vibe=db.execute('SELECT name FROM vibes WHERE id=? AND id NOT IN (SELECT vibe_id FROM pending_vibes) AND id NOT IN (SELECT vibe_id FROM vibe_management WHERE archived=1)',(key,)).fetchone()
                if vibe:locations.append(url_for('vibe_page',vibe_name=vibe['name']))
        return xml('urlset',locations)
    @app.after_request
    def sandbox_noindex(response):
        if sandbox or request.script_root.rstrip('/')=='/sandbox':response.headers['X-Robots-Tag']='noindex, nofollow'
        return response
