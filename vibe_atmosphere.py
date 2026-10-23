"""Mode logos and Vibe-owned MIDI, independent of private attachment access."""
import hmac
import re
import secrets
import struct
from pathlib import Path
from flask import abort, request, session, render_template, redirect, url_for, send_from_directory
from PIL import Image, UnidentifiedImageError
from .media_features import MIDI_LIMIT, _limited_bytes, validate_midi, media_folder
from .vibe_tools import find_vibe, permissions


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS vibe_atmosphere(
        vibe_id INTEGER PRIMARY KEY, day_logo TEXT, night_logo TEXT,
        logo_motion TEXT NOT NULL DEFAULT 'none' CHECK(logo_motion IN ('none','float','pulse')),
        midi_filename TEXT, midi_title TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 0, updated_by INTEGER,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_vibe_atmosphere_editor ON vibe_atmosphere(updated_by,vibe_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS atmosphere_preferences(
        user_id INTEGER PRIMARY KEY, logo_motion TEXT NOT NULL DEFAULT 'system'
        CHECK(logo_motion IN ('system','off')))''')


def settings(db, vibe_id):
    row=db.execute('SELECT * FROM vibe_atmosphere WHERE vibe_id=?',(vibe_id,)).fetchone()
    return dict(row) if row else {'vibe_id':vibe_id,'day_logo':None,'night_logo':None,
        'logo_motion':'none','midi_filename':None,'midi_title':'','revision':0}


def public_vibe(db, vibe_id):
    return bool(db.execute('SELECT 1 FROM vibes v WHERE v.id=? AND NOT EXISTS '
        '(SELECT 1 FROM pending_vibes p WHERE p.vibe_id=v.id) AND NOT EXISTS '
        '(SELECT 1 FROM vibe_management m WHERE m.vibe_id=v.id AND m.archived=1)',(vibe_id,)).fetchone())


def logo_asset(static_folder, value):
    value=(value or '').strip()
    if not value: return None
    if value.startswith('/static/'): value=value[8:]
    if not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}',value) or '..' in value.split('/'):
        abort(400,description='Choose a local static PNG, JPEG or WebP logo.')
    root=Path(static_folder).resolve();path=(root/value).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or not path.is_file() or path.stat().st_size>2*1024*1024:
        abort(400,description='Choose an existing local static logo up to 2 MiB.')
    try:
        with Image.open(path) as image:
            if image.format not in ('PNG','JPEG','WEBP') or getattr(image,'is_animated',False) or image.width>4096 or image.height>4096:
                raise ValueError()
            image.verify()
    except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError):
        abort(400,description='Use a valid still PNG, JPEG or WebP. Animate it with the logo motion control.')
    return value


def export_user(db, uid):
    pref=db.execute('SELECT logo_motion FROM atmosphere_preferences WHERE user_id=?',(uid,)).fetchone()
    rows=db.execute('SELECT vibe_id,day_logo,night_logo,logo_motion,midi_filename,midi_title,revision,updated_at FROM vibe_atmosphere WHERE updated_by=? ORDER BY vibe_id',(uid,)).fetchall()
    return {'preferences':dict(pref) if pref else {'logo_motion':'system'},
        'vibe_settings_last_saved_by_you':[dict(row) for row in rows]}


def register(app, core):
    with app.app_context():
        initialize(core.get_db());core.get_db().commit()

    def csrf():
        expected=session.get('theme_csrf_token','');submitted=request.form.get('theme_csrf_token','')
        if not expected or not hmac.compare_digest(expected.encode(),submitted.encode()): abort(400)

    def preferences():
        row=core.get_db().execute('SELECT logo_motion FROM atmosphere_preferences WHERE user_id=?',(session.get('user_id'),)).fetchone()
        return dict(row) if row else {'logo_motion':'system'}

    def appearance(vibe_id, mode):
        result=settings(core.get_db(),vibe_id)
        result['logo']=result['day_logo' if mode=='day' else 'night_logo']
        if not public_vibe(core.get_db(),vibe_id): result['midi_filename']=None
        return result

    @app.context_processor
    def atmosphere_context():
        return {'atmosphere_preferences':preferences,'vibe_atmosphere':appearance}

    @app.route('/atmosphere-preferences',methods=['POST'])
    def atmosphere_preferences_save():
        uid=session.get('user_id');db=core.get_db()
        if type(uid) is not int or not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(): abort(403)
        csrf();choice=request.form.get('logo_motion')
        if choice not in ('system','off'): abort(400)
        db.execute('INSERT INTO atmosphere_preferences(user_id,logo_motion) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET logo_motion=excluded.logo_motion',(uid,choice));db.commit()
        return redirect(url_for('media_settings'))

    @app.route('/manage/vibes/<slug>/atmosphere',methods=['GET','POST'])
    def vibe_atmosphere_edit(slug):
        db=core.get_db();vibe=find_vibe(db,slug);uid=session.get('user_id')
        if not permissions(core,db,uid,vibe['id'])['settings']: abort(403)
        current=settings(db,vibe['id'])
        if request.method=='POST':
            csrf()
            day=logo_asset(app.static_folder,request.form.get('day_logo'))
            night=logo_asset(app.static_folder,request.form.get('night_logo'))
            motion=request.form.get('logo_motion','none')
            if motion not in ('none','float','pulse'): abort(400)
            title=request.form.get('midi_title','').strip()
            if len(title)>100: abort(400)
            try:
                revision=int(request.form.get('revision',''))
                if revision<0: raise ValueError()
            except ValueError: abort(400)
            raw=None;upload=request.files.get('background_midi')
            if upload and upload.filename:
                if not upload.filename.lower().endswith(('.mid','.midi')): abort(400)
                raw=_limited_bytes(upload,MIDI_LIMIT)
                try: validate_midi(raw)
                except (ValueError,IndexError,ArithmeticError,struct.error) as error: abort(400,description=str(error))
                if not title: title='Vibe background MIDI'
            created=None
            try:
                db.execute('BEGIN IMMEDIATE')
                current=settings(db,vibe['id'])
                if current['revision']!=revision: abort(409,description='These settings changed in another window. Reload before saving.')
                filename=current['midi_filename']
                if request.form.get('remove_midi')=='yes' and raw is None: filename=None;title=''
                if raw is not None:
                    filename=secrets.token_hex(20)+'.mid';candidate=media_folder()/filename
                    target=candidate.open('xb');created=candidate
                    with target: target.write(raw)
                if not filename: title=''
                elif not title: title='Vibe background MIDI'
                db.execute('''INSERT INTO vibe_atmosphere(vibe_id,day_logo,night_logo,logo_motion,midi_filename,midi_title,revision,updated_by)
                    VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(vibe_id) DO UPDATE SET
                    day_logo=excluded.day_logo,night_logo=excluded.night_logo,logo_motion=excluded.logo_motion,
                    midi_filename=excluded.midi_filename,midi_title=excluded.midi_title,
                    revision=vibe_atmosphere.revision+1,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP''',
                    (vibe['id'],day,night,motion,filename,title,uid))
                db.commit()
            except BaseException:
                db.rollback()
                if created is not None:
                    try: created.unlink(missing_ok=True)
                    except OSError: pass
                raise
            return redirect(url_for('vibe_atmosphere_edit',slug=slug,saved=1))
        return render_template('vibe_atmosphere_edit.html',vibe=vibe,slug=slug,settings=current,token=core.theme_csrf_token())

    @app.route('/vibe-atmosphere/<int:vibe_id>/music/<filename>')
    def vibe_atmosphere_music(vibe_id,filename):
        if not re.fullmatch(r'[0-9a-f]{40}\.mid',filename): abort(404)
        db=core.get_db();row=settings(db,vibe_id)
        if row['midi_filename']!=filename or not public_vibe(db,vibe_id): abort(404)
        response=send_from_directory(media_folder(),filename)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
