"""Owner-managed, bounded Circle palettes and access-checked cover images."""
import io
import json
import re
import secrets
import sqlite3
from pathlib import Path

from flask import abort, flash, g, redirect, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from .resource_errors import discard_files, raise_if_storage_full

COLORS = ('background', 'panel', 'text', 'accent')
DEFAULTS = {
    'night': dict(background='#0d1728', panel='#152136', text='#edf2fa', accent='#a8dcff'),
    'day': dict(background='#f1f5fa', panel='#ffffff', text='#17263b', accent='#144a76'),
}
FONTS = {'system': 'system-ui,sans-serif', 'serif': 'Georgia,serif', 'mono': 'monospace'}
HEX = re.compile(r'#[0-9a-fA-F]{6}\Z')
FILENAME = re.compile(r'[0-9a-f]{48}\.jpg\Z')


def initialize(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(circles)')}
    for name in ('appearance', 'cover', 'cover_alt'):
        if name not in columns:
            db.execute("ALTER TABLE circles ADD COLUMN " + name + " TEXT NOT NULL DEFAULT ''")


def luminance(color):
    values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(a*b for a, b in zip(values, (.2126, .7152, .0722)))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def defaults():
    return {**{mode: dict(colors) for mode, colors in DEFAULTS.items()}, 'font': 'system', 'corners': '16'}


def validate(value):
    if not isinstance(value, dict) or set(value) != {'day', 'night', 'font', 'corners'}:
        raise ValueError('Choose a complete day and night palette.')
    result = {}
    for mode in DEFAULTS:
        colors = value[mode]
        if not isinstance(colors, dict) or set(colors) != set(COLORS) or any(not isinstance(c, str) or not HEX.fullmatch(c) for c in colors.values()):
            raise ValueError('Use six-digit hex colors such as #152136.')
        colors = {k: c.lower() for k, c in colors.items()}
        if any(contrast(colors[fg], colors[bg]) < 4.5 for fg in ('text', 'accent') for bg in ('background', 'panel')):
            raise ValueError(mode.title() + ' text and link colors must have at least 4.5:1 contrast against both backgrounds. Choose darker text on light backgrounds, or lighter text on dark backgrounds.')
        result[mode] = colors
    if value['font'] not in FONTS or value['corners'] not in ('0', '8', '16'):
        raise ValueError('Choose a listed font and corner style.')
    return dict(result, font=value['font'], corners=value['corners'])


def palette(circle):
    try:
        return validate(json.loads(circle['appearance']))
    except (ValueError, TypeError, KeyError):
        return defaults()


def style(circle):
    value = palette(circle)
    mode = request.args.get('appearance', 'night')
    mode = mode if mode in DEFAULTS else 'night'
    colors = value[mode]
    # Every emitted token is validated; arbitrary CSS, selectors and URLs are never accepted.
    properties = ['--circle-' + k + ':' + c for k, c in colors.items()]
    ink = '#000000' if contrast(colors['accent'], '#000000') >= contrast(colors['accent'], '#ffffff') else '#ffffff'
    properties += ['--circle-button-text:' + ink, '--circle-font:' + FONTS[value['font']], '--circle-radius:' + value['corners'] + 'px']
    return ';'.join(properties)


def save_cover(app):
    upload = request.files.get('cover')
    if not upload or not upload.filename:
        return None
    data = upload.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        abort(413, description='Choose a cover up to 5 MB.')
    allocated = None
    try:
        with Image.open(io.BytesIO(data)) as original:
            if original.format not in ('JPEG', 'PNG', 'WEBP') or original.width * original.height > 16000000:
                raise ValueError()
            original.load()
            image = ImageOps.exif_transpose(original).convert('RGBA')
            image.thumbnail((1600, 600))
            flattened = Image.new('RGB', image.size, 'white')
            flattened.paste(image, mask=image.getchannel('A'))
            folder = Path(app.instance_path) / 'circle_covers'
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            allocated = folder / (secrets.token_hex(24) + '.jpg')
            from .storage_uploads import image as store_image
            store_image(allocated, flattened, 4*1024*1024, 'JPEG', 'circle_covers', quality=85, optimize=True)
            return allocated
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise_if_storage_full(error)
        abort(400, description='Choose a JPEG, PNG or WebP cover up to 5 MB and 16 million pixels.')


def register(app, core, circle_for, actor, mutation, record):
    @app.context_processor
    def appearance_context():
        return dict(circle_palette=palette, circle_appearance_style=style, circle_appearance_mode=lambda: 'day' if request.args.get('appearance') == 'day' else 'night')

    @app.get('/circles/<string:circle_id>/cover')
    def circle_cover(circle_id):
        circle, _ = circle_for(circle_id, session.get('user_id'))
        name = circle['cover']
        if not FILENAME.fullmatch(name or ''):
            abort(404)
        path = Path(app.instance_path) / 'circle_covers' / name
        if not path.is_file():
            abort(404)
        if getattr(g, 'legacy_circle_route', None):
            return redirect(url_for('circle_cover', circle_id=circle_id))
        response = send_file(path, mimetype='image/jpeg')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.post('/circles/<string:circle_id>/appearance')
    def circle_appearance(circle_id):
        uid = mutation()
        circle, _ = circle_for(circle_id, uid, owner=True)
        action = request.form.get('action')
        if action not in ('save_theme', 'reset_theme', 'save_cover'):
            abort(400)
        db = core.get_db()
        allocated = None
        old_cover = None
        try:
            if action == 'save_theme':
                try:
                    value = validate({**{mode: {key: request.form.get(mode+'_'+key, '') for key in COLORS} for mode in DEFAULTS}, 'font': request.form.get('font', ''), 'corners': request.form.get('corners', '')})
                except ValueError as error:
                    abort(400, description=str(error))
                db.execute('UPDATE circles SET appearance=? WHERE id=?', (json.dumps(value), circle_id))
            elif action == 'reset_theme':
                db.execute("UPDATE circles SET appearance='' WHERE id=?", (circle_id,))
            else:
                alt = request.form.get('cover_alt', '').strip()
                if len(alt) > 200 or any(ord(c) < 32 for c in alt):
                    abort(400, description='Keep the cover description within 200 characters without control characters.')
                remove = request.form.get('remove_cover') == '1'
                if remove and request.files.get('cover') and request.files['cover'].filename:
                    abort(400, description='Choose either a replacement cover or Remove cover.')
                allocated = None if remove else save_cover(app)
                name = '' if remove else allocated.name if allocated else circle['cover']
                db.execute('UPDATE circles SET cover=?,cover_alt=? WHERE id=?', (name, '' if remove else alt, circle_id))
                if name != circle['cover'] and FILENAME.fullmatch(circle['cover'] or ''):
                    old_cover = Path(app.instance_path) / 'circle_covers' / circle['cover']
            record(circle_id, uid, action)
            db.commit()
        except BaseException:
            try:
                db.rollback()
            except (sqlite3.Error, OSError):
                pass
            discard_files(allocated)
            raise
        # Retire only this Circle's replaced image, after its reference commits.
        discard_files(old_cover)
        flash('Circle appearance updated.', 'success')
        return redirect(url_for('circle_manage', circle_id=circle_id) + '#circle-appearance')
