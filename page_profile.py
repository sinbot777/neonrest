"""Page presentation and bounded artwork; existing identity permissions apply."""
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

ACCENTS = ('teal', 'violet', 'rose', 'amber', 'blue', 'green')
FIELDS = ('tagline', 'website', 'accent', 'avatar_file', 'cover_file')


def initialize(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(identity_pages)')}
    for name in FIELDS:
        if name not in columns:
            default = 'teal' if name == 'accent' else ''
            db.execute("ALTER TABLE identity_pages ADD COLUMN " + name + " TEXT NOT NULL DEFAULT '" + default + "'")


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
    result = db.execute('''UPDATE identity_pages SET tagline=?,website=?,accent=?,avatar_file=?,cover_file=?,
        revision=revision+1,updated_at=? WHERE id=? AND revision=?''',
        (tagline, website, accent, names['avatar'], names['cover'], int(pages.time.time()), page_id, revision))
    if result.rowcount != 1:
        raise pages.PageError('The page changed. Reload it before saving.', 409)
    pages.event(db, page_id, uid, 'profile_edited')


def register_artwork(bp, app, core, pages):
    from flask import abort, send_from_directory, session

    @bp.get('/pages/<page_id>/artwork/<slot>/<filename>')
    def artwork(page_id, slot, filename):
        if slot not in ('avatar', 'cover') or not re.fullmatch(r'[a-f0-9]{48}\.png', filename):
            abort(404)
        db = core.get_db()
        page = pages.get(db, page_id)
        if not pages.visible(db, page, session.get('user_id')) or page[slot + '_file'] != filename:
            abort(404)
        response = send_from_directory(artwork_folder(app), filename, mimetype='image/png')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
