"""Page presentation and bounded artwork; existing identity permissions apply."""
from pathlib import Path
import json
import math
import re
import secrets
from urllib.parse import urlsplit

ACCENTS = ('teal', 'violet', 'rose', 'amber', 'blue', 'green')
FIELDS = ('tagline', 'website', 'accent', 'avatar_file', 'cover_file')


def frame_defaults(slot):
    return dict(mode='logo' if slot == 'avatar' else 'portrait', shape='rounded' if slot == 'avatar' else 'square',
                zoom=1, x=50, y=50, padding=0, background='transparent', trim=slot == 'avatar')


def frame_settings(value, slot):
    if isinstance(value, str):
        if len(value) > 2048:
            raise ValueError('Artwork framing settings are too large.')
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            raise ValueError('Invalid artwork framing settings.') from None
    if not isinstance(value, dict) or set(value) - set(frame_defaults(slot)):
        raise ValueError('Invalid artwork framing settings.')
    result = dict(frame_defaults(slot), **value)
    if result['mode'] not in ('logo', 'portrait') or result['shape'] not in ('square', 'rounded', 'circle'):
        raise ValueError('Choose an available artwork mode and frame.')
    if not isinstance(result['background'], str) or not re.fullmatch(r'transparent|#[0-9a-fA-F]{6}', result['background']):
        raise ValueError('Choose a valid artwork background color.')
    if type(result['trim']) is not bool:
        raise ValueError('Invalid transparent margin setting.')
    for name, low, high in (('zoom', 1, 4), ('x', 0, 100), ('y', 0, 100), ('padding', 0, 24)):
        number = result[name]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError('Artwork framing values are out of range.')
        result[name] = round(number, 3)
    if slot == 'cover':
        result.update(mode='portrait', shape='square', padding=0, trim=False)
    return result


def page_frame(page, slot):
    try:
        frame = frame_settings(page[slot + '_frame'], slot)
    except (ValueError, TypeError, KeyError, IndexError):
        frame = frame_defaults(slot)
    radius = dict(square='0', rounded='1rem', circle='50%')[frame['shape']]
    padding = frame['padding'] if frame['mode'] == 'logo' else 0
    frame['style'] = ('--art-fit:' + ('contain' if frame['mode'] == 'logo' else 'cover')
        + ';--art-zoom:' + str(frame['zoom']) + ';--art-x:' + str(frame['x']) + '%;--art-y:' + str(frame['y'])
        + '%;--art-padding:' + str(padding) + '%;--art-background:' + frame['background'] + ';border-radius:' + radius)
    return frame


def initialize(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(identity_pages)')}
    for name in FIELDS:
        if name not in columns:
            default = 'teal' if name == 'accent' else ''
            db.execute("ALTER TABLE identity_pages ADD COLUMN " + name + " TEXT NOT NULL DEFAULT '" + default + "'")
    for name in ('avatar_frame', 'cover_frame'):
        if name not in columns:
            db.execute("ALTER TABLE identity_pages ADD COLUMN " + name + " TEXT NOT NULL DEFAULT '{}'")


def details(tagline, website, accent):
    if not isinstance(tagline, str) or len(tagline.strip()) > 160:
        raise ValueError('Keep the short introduction to 160 characters.')
    if not isinstance(website, str) or len(website.strip()) > 500:
        raise ValueError('Use a website address of at most 500 characters.')
    website = website.strip()
    if website:
        try:
            url = urlsplit(website)
            if (url.scheme != 'https' or not url.hostname or '.' not in url.hostname
                    or url.username or url.password or url.port is not None
                    or any(ord(c) < 33 or c in '\\' for c in website)):
                raise ValueError
        except ValueError:
            raise ValueError('Enter a complete https:// website address without login details.') from None
    if accent not in ACCENTS:
        raise ValueError('Choose one of the available page colors.')
    return tagline.strip(), website, accent


def artwork_folder(app):
    # Not in /static: private, hidden and age-restricted Pages retain their rules.
    return Path(app.root_path) / 'instance' / 'page-artwork'


def prepare_picture(upload, slot):
    import io
    from PIL import Image, ImageOps
    raw = upload.stream.read(1800 * 1024 + 1)
    if len(raw) > 1800 * 1024:
        raise ValueError('Page artwork must be under 1.8 MB per image.')
    try:
        picture = Image.open(io.BytesIO(raw))
        if picture.format not in ('JPEG', 'PNG', 'WEBP', 'GIF') or picture.width * picture.height > 16_000_000:
            raise ValueError
        picture = ImageOps.exif_transpose(picture)
        picture.thumbnail((512, 512) if slot == 'avatar' else (1600, 700))
        picture = picture.convert('RGBA')
        picture.load()
        return picture
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('Choose a valid JPG, PNG, WebP or GIF image. Animated artwork uses its first frame.') from None


def save(db, pages, app, uid, page_id, revision, form, files):
    page = pages.get(db, page_id)
    pages.require_role(db, page, uid, ('owner', 'manager', 'editor'))
    if page['state'] == 'archived':
        raise pages.PageError('Restore this page before editing it.', 409)
    if page['revision'] != revision:
        raise pages.PageError('The page changed. Reload it before saving.', 409)
    try:
        tagline, website, accent = details(form.get('tagline', ''), form.get('website', ''), form.get('accent', 'teal'))
        frames = {slot: json.dumps(frame_settings(form.get(slot + '_frame', page[slot + '_frame']), slot),
                                  separators=(',', ':'), allow_nan=False) for slot in ('avatar', 'cover')}
        pictures = {}
        for slot in ('avatar', 'cover'):
            upload = files.get(slot)
            if upload and upload.filename:
                if form.get('remove_' + slot):
                    raise ValueError('Choose either replacement or removal for each image.')
                pictures[slot] = prepare_picture(upload, slot)
    except ValueError as error:
        raise pages.PageError(str(error)) from None
    names = {slot: '' if form.get('remove_' + slot) else page[slot + '_file'] for slot in ('avatar', 'cover')}
    if pictures:
        from .storage_uploads import batch, image
        folder = artwork_folder(app)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with batch():
            for slot, picture in pictures.items():
                names[slot] = secrets.token_hex(24) + '.png'
                image(folder / names[slot], picture, 2 * 1024 * 1024, 'PNG', 'media')
    result = db.execute('''UPDATE identity_pages SET tagline=?,website=?,accent=?,avatar_file=?,cover_file=?,avatar_frame=?,cover_frame=?,
        revision=revision+1,updated_at=? WHERE id=? AND revision=?''',
        (tagline, website, accent, names['avatar'], names['cover'], frames['avatar'], frames['cover'], int(pages.time.time()), page_id, revision))
    if result.rowcount != 1:
        raise pages.PageError('The page changed. Reload it before saving.', 409)
    pages.event(db, page_id, uid, 'profile_edited')


def register_artwork(bp, app, core, pages):
    from flask import abort, request, send_file, send_from_directory, session
    app.jinja_env.globals['page_frame'] = page_frame

    @bp.get('/pages/<page_id>/artwork/<slot>/<filename>')
    def artwork(page_id, slot, filename):
        if slot not in ('avatar', 'cover') or not re.fullmatch(r'[a-f0-9]{48}\.png', filename):
            abort(404)
        db = core.get_db()
        page = pages.get(db, page_id)
        if not pages.visible(db, page, session.get('user_id')) or page[slot + '_file'] != filename:
            abort(404)
        frame = page_frame(page, slot)
        if request.args.get('framed') == '1' and slot == 'avatar' and frame['mode'] == 'logo' and frame['trim']:
            import io
            from PIL import Image
            # A display derivative only. The original selected file is never rewritten.
            path = artwork_folder(app) / filename
            if not path.is_file():
                abort(404)
            with Image.open(path) as picture:
                picture = picture.convert('RGBA')
                bounds = picture.getchannel('A').getbbox()
                if bounds:
                    picture = picture.crop(bounds)
                output = io.BytesIO()
                picture.save(output, format='PNG')
                output.seek(0)
            response = send_file(output, mimetype='image/png')
        else:
            response = send_from_directory(artwork_folder(app), filename, mimetype='image/png')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
