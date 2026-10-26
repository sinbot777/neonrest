"""Post images, animated GIFs, MIDI files, and account playback preferences."""

import io
import os
import secrets
import sqlite3
import struct
import re
from pathlib import Path

from flask import abort, current_app, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from . import storage_uploads as storage
from .storage_writers import OutputTooLarge

IMAGE_LIMIT = 25 * 1024 * 1024
GIF_LIMIT = 5 * 1024 * 1024
MIDI_LIMIT = 256 * 1024
FILTERS = {'original', 'mono', 'sepia', 'negative', 'faded', 'contrast', 'blue'}
GIF_MODES = {'system', 'once', 'loop', 'off'}


def init_media_tables(db):
    if getattr(g, 'media_schema_ready', False):
        return
    db.execute('''CREATE TABLE IF NOT EXISTS post_media (
        post_id INTEGER NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
        poster TEXT, loop_filename TEXT, alt_text TEXT NOT NULL DEFAULT '',
        filter_name TEXT NOT NULL DEFAULT 'original', title TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (post_id,kind))''')
    columns = db.execute('PRAGMA table_info(post_media)').fetchall()
    if [(column[1], column[5]) for column in columns if column[5]] == [('post_id', 1)]:
        db.execute('''CREATE TABLE post_media_new (
            post_id INTEGER NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
            poster TEXT, loop_filename TEXT, alt_text TEXT NOT NULL DEFAULT '',
            filter_name TEXT NOT NULL DEFAULT 'original', title TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (post_id,kind))''')
        db.execute('''INSERT INTO post_media_new
            SELECT post_id,kind,filename,poster,loop_filename,alt_text,filter_name,title FROM post_media''')
        db.execute('DROP TABLE post_media')
        db.execute('ALTER TABLE post_media_new RENAME TO post_media')
    db.execute('''CREATE TABLE IF NOT EXISTS media_settings (
        user_id INTEGER PRIMARY KEY, gif_mode TEXT NOT NULL DEFAULT 'system',
        midi_autoplay INTEGER NOT NULL DEFAULT 0, profile_midi TEXT,
        profile_midi_title TEXT NOT NULL DEFAULT '')''')
    db.commit()
    g.media_schema_ready = True


def media_folder():
    folder = Path(current_app.instance_path) / 'media'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _limited_bytes(upload, limit):
    raw = upload.stream.read(limit + 1)
    if len(raw) > limit:
        abort(413, description='That attachment is too large.')
    if not raw:
        abort(400, description='The attachment is empty.')
    return raw


def _media_title(upload, entered):
    title = entered.strip()
    if len(title) > 100:
        abort(400, description='Attachment titles must be 100 characters or fewer.')
    if title:
        return title
    basename = upload.filename.replace('\\', '/').rsplit('/', 1)[-1]
    stem = Path(basename).stem
    return ''.join(character for character in stem if character.isprintable()).strip()[:100] or 'Untitled attachment'


def _save_image(upload, alt, filter_name, title):
    title = _media_title(upload, title)
    alt = alt or title
    if len(alt) > 180:
        abort(400, description='Describe the image in 180 characters or fewer.')
    raw = _limited_bytes(upload, IMAGE_LIMIT)
    folder = name = None
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in {'JPEG', 'PNG', 'WEBP', 'GIF'} or image.width * image.height > 20_000_000:
            abort(400, description='Choose a JPEG, PNG, WebP or GIF under 20 megapixels.')
        name = secrets.token_hex(20)
        folder = media_folder()
        if image.format == 'GIF' and getattr(image, 'n_frames', 1) > 1:
            if len(raw) > GIF_LIMIT:
                abort(413, description='Animated GIFs must be 5 MB or smaller.')
            if image.n_frames > 120 or image.n_frames * image.width * image.height > 60_000_000:
                abort(400, description='Animated GIFs are limited to 120 frames and 60 million total pixels.')
            frames = []
            durations = []
            for frame in ImageSequence.Iterator(image):
                picture = frame.convert('RGBA')
                picture.thumbnail((1200, 1200))
                frames.append(picture.convert('RGB'))
                durations.append(max(30, min(int(frame.info.get('duration', 100)), 1000)))
            if sum(durations) > 90_000:
                abort(400, description='Animated GIFs must be 90 seconds or shorter.')
            poster = name + '.jpg'
            once = name + '-once.gif'
            loop = name + '-loop.gif'
            poster_data = storage.encode_image(frames[0], 4*1024*1024, 'JPEG', quality=85)
            once_data = storage.encode_image(frames[0], 16*1024*1024, 'GIF', save_all=True, append_images=frames[1:], duration=durations, optimize=True, disposal=2)
            loop_data = storage.encode_image(frames[0], 16*1024*1024, 'GIF', save_all=True, append_images=frames[1:], duration=durations, optimize=True, disposal=2, loop=0)
            storage.write([(folder/poster,poster_data),(folder/once,once_data),(folder/loop,loop_data)], 'media')
            return dict(kind='gif', filename=once, poster=poster, loop_filename=loop,
                        alt_text=alt, filter_name=filter_name, title=title)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((2200, 2200))
        filename = name + '.webp'
        if image.mode in {'RGBA', 'LA'} or 'transparency' in image.info:
            storage.image(folder / filename, image.convert('RGBA'), 20*1024*1024, 'WEBP', 'media', lossless=True, method=4)
        else:
            storage.image(folder / filename, image.convert('RGB'), 20*1024*1024, 'WEBP', 'media', quality=88, method=4)
        return dict(kind='image', filename=filename, poster=None, loop_filename=None,
                    alt_text=alt, filter_name=filter_name, title=title)
    except OutputTooLarge:
        abort(413, description='The processed animation is too large. Choose a smaller animation.')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        from .resource_errors import discard_files, raise_if_storage_full
        if folder is not None and name:
            discard_files(*(folder / (name + suffix) for suffix in ('.jpg', '.webp', '-once.gif', '-loop.gif')))
        raise_if_storage_full(error)
        abort(400, description='The selected image could not be read.')


def _read_vlq(data, pos, end):
    value = 0
    for _ in range(4):
        if pos >= end:
            raise ValueError('Truncated MIDI event')
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 127)
        if not b & 128:
            return value, pos
    raise ValueError('Invalid MIDI event length')


def validate_midi(data):
    """Bound every track and event before making an uploaded MIDI public."""
    if len(data) < 22 or data[:4] != b'MThd' or struct.unpack_from('>I', data, 4)[0] != 6:
        raise ValueError('Not a Standard MIDI File')
    fmt, tracks, division = struct.unpack_from('>HHH', data, 8)
    if fmt not in (0, 1) or not 1 <= tracks <= 16 or not 1 <= division <= 9600:
        raise ValueError('Unsupported MIDI header')
    pos = 14
    events = 0
    notes = 0
    musical_events = []
    for _ in range(tracks):
        if data[pos:pos + 4] != b'MTrk' or pos + 8 > len(data):
            raise ValueError('Missing MIDI track')
        length = struct.unpack_from('>I', data, pos + 4)[0]
        pos += 8
        end = pos + length
        if end > len(data):
            raise ValueError('Truncated MIDI track')
        ticks = 0
        running = None
        while pos < end:
            delta, pos = _read_vlq(data, pos, end)
            ticks += delta
            events += 1
            if events > 30_000:
                raise ValueError('MIDI event limit exceeded')
            status = data[pos]
            if status & 128:
                pos += 1
                if status < 0xF0:
                    running = status
            elif running is not None:
                status = running
            else:
                raise ValueError('Invalid MIDI running status')
            if status == 0xFF:
                if pos >= end:
                    raise ValueError('Truncated MIDI metadata')
                kind = data[pos]
                pos += 1
                size, pos = _read_vlq(data, pos, end)
            elif status in (0xF0, 0xF7):
                raise ValueError('System exclusive MIDI events are not supported')
            elif status < 0xF0:
                size = 1 if status & 0xF0 in (0xC0, 0xD0) else 2
                if status & 0xF0 == 0x90:
                    notes += 1
            else:
                raise ValueError('Unsupported MIDI event')
            if pos + size > end:
                raise ValueError('Truncated MIDI event')
            if status == 0xFF and kind == 0x51 and size == 3:
                tempo = int.from_bytes(data[pos:pos + 3], 'big')
                if not tempo:
                    raise ValueError('Invalid MIDI tempo')
                musical_events.append((ticks, 0, tempo))
            elif status < 0xF0 and status & 0xF0 in (0x80, 0x90):
                musical_events.append((ticks, 1, 0))
            pos += size
        pos = end
    if pos != len(data) or notes == 0 or notes > 10_000:
        raise ValueError('MIDI must contain between 1 and 10,000 notes')
    tempo = 500_000
    last_tick = 0
    seconds = 0.0
    for tick, priority, value in sorted(musical_events):
        seconds += (tick - last_tick) * tempo / (division * 1_000_000)
        last_tick = tick
        if priority == 0:
            tempo = value
        elif seconds > 600:
            raise ValueError('MIDI music must be 10 minutes or shorter')


def _save_midi(upload, title):
    _media_title(upload, title)
    raw = _limited_bytes(upload, MIDI_LIMIT)
    try:
        validate_midi(raw)
    except (ValueError, IndexError, struct.error) as exc:
        abort(400, description=str(exc))
    filename = secrets.token_hex(20) + '.mid'
    storage.write([(media_folder() / filename, raw)], 'media')
    return filename


def prepare_post_media():
    image = request.files.get('post_image')
    midi = request.files.get('post_midi')
    has_image = bool(image and image.filename)
    has_midi = bool(midi and midi.filename)
    with storage.batch():
        media = []
        if has_image:
            chosen = request.form.get('image_filter', 'original')
            if chosen not in FILTERS:
                abort(400, description='Invalid image filter.')
            media.append(_save_image(image, request.form.get('image_alt', '').strip(), chosen,
                                     request.form.get('image_title', '')))
        if has_midi:
            title = _media_title(midi, request.form.get('midi_title', ''))
            media.append(dict(kind='midi', filename=_save_midi(midi, title), poster=None,
                              loop_filename=None, alt_text='', filter_name='original', title=title))
        return media


def attach_post_media(db, post_id, media):
    if media:
        init_media_tables(db)
        for item in media:
            if item['kind'] in ('image', 'gif'):
                db.execute("DELETE FROM post_media WHERE post_id=? AND kind IN ('image','gif')", (post_id,))
            else:
                db.execute('DELETE FROM post_media WHERE post_id=? AND kind=?', (post_id, 'midi'))
            db.execute('''INSERT INTO post_media
                (post_id,kind,filename,poster,loop_filename,alt_text,filter_name,title)
                VALUES (?,?,?,?,?,?,?,?)''', (post_id, item['kind'], item['filename'],
                item['poster'], item['loop_filename'], item['alt_text'], item['filter_name'], item['title']))


def update_post_media_labels(db, post_id, form):
    fields = (('image_title', 'title', "kind IN ('image','gif')", 100),
              ('image_alt', 'alt_text', "kind IN ('image','gif')", 180),
              ('midi_title', 'title', "kind='midi'", 100))
    for input_name, column, kind_filter, maximum in fields:
        value = form.get(input_name, '').strip()
        if value:
            if len(value) > maximum:
                abort(400, description=f'{input_name} is too long.')
            db.execute(f'UPDATE post_media SET {column}=? WHERE post_id=? AND {kind_filter}',
                       (value, post_id))


def register_media(app, get_db):
    def preferences():
        db = get_db()
        init_media_tables(db)
        user_id = session.get('user_id')
        row = db.execute('SELECT * FROM media_settings WHERE user_id=?', (user_id,)).fetchone() if user_id else None
        return dict(row) if row else {'gif_mode': 'system', 'midi_autoplay': 0}

    def post_media(post_id):
        db = get_db()
        init_media_tables(db)
        rows = db.execute('SELECT * FROM post_media WHERE post_id=?', (post_id,)).fetchall()
        return {'image': next((dict(row) for row in rows if row['kind'] in ('image', 'gif')), None),
                'midi': next((dict(row) for row in rows if row['kind'] == 'midi'), None)}

    def profile_midi(user_id):
        db = get_db()
        init_media_tables(db)
        row = db.execute('SELECT profile_midi,profile_midi_title FROM media_settings WHERE user_id=?', (user_id,)).fetchone()
        return dict(row) if row and row['profile_midi'] else None

    @app.context_processor
    def media_context():
        return dict(media_preferences=preferences, media_for_post=post_media, profile_midi=profile_midi)

    @app.route('/media-file/<filename>')
    def media_file(filename):
        if not re.fullmatch(r'[0-9a-f]{40}(?:-once|-loop)?\.(?:mid|jpg|png|webp|gif)', filename):
            abort(404)
        db = get_db()
        init_media_tables(db)
        used = db.execute('''SELECT 1 FROM post_media JOIN posts ON posts.id=post_media.post_id
            WHERE (filename=? OR poster=? OR loop_filename=?) AND community_post_visible(posts.id)=1
            UNION SELECT 1 FROM media_settings WHERE profile_midi=? AND community_personal_profile_visible(user_id)=1''',
            (filename, filename, filename, filename)).fetchone()
        if not used:
            abort(404)
        response = send_from_directory(media_folder(), filename)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/media-settings', methods=['GET', 'POST'])
    def media_settings():
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))
        db = get_db()
        init_media_tables(db)
        token = session.setdefault('media_csrf', secrets.token_urlsafe(24))
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf_token', ''), token):
                abort(403)
            gif_mode = request.form.get('gif_mode', 'system')
            if gif_mode not in GIF_MODES or request.form.get('midi_autoplay', '') not in ('0', '1'):
                abort(400)
            current = db.execute('SELECT profile_midi, profile_midi_title FROM media_settings WHERE user_id=?', (user_id,)).fetchone()
            filename = current['profile_midi'] if current else None
            title = current['profile_midi_title'] if current else ''
            if request.form.get('remove_profile_midi') == '1':
                filename, title = None, ''
            upload = request.files.get('profile_midi')
            if upload and upload.filename:
                title = _media_title(upload, request.form.get('profile_midi_title', ''))
                filename = _save_midi(upload, title)
            db.execute('''INSERT INTO media_settings
                (user_id,gif_mode,midi_autoplay,profile_midi,profile_midi_title)
                VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                gif_mode=excluded.gif_mode,midi_autoplay=excluded.midi_autoplay,
                profile_midi=excluded.profile_midi,profile_midi_title=excluded.profile_midi_title''',
                (user_id, gif_mode, int(request.form['midi_autoplay']), filename, title))
            db.commit()
            flash('Media settings saved.', 'success')
            return redirect(url_for('media_settings'))
        return render_template('media_settings.html', prefs=preferences(), csrf_token=token)
