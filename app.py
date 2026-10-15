from flask import Flask, render_template, request, redirect, session, flash, g, jsonify, url_for, current_app, abort
import sqlite3
import os
import logging
import re
import hmac
import secrets
import markdown2
from urllib.parse import urlparse
from neonrest.community_features import (register_db_functions, redacted_profile, attach_report, attach_appeal, attach_event, notify, settings)

from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email
from neonrest.utils.lastfm import get_now_playing  # this is the helper you created

import itsdangerous
from datetime import datetime
from neonrest.utils.friend_helpers import are_friends, get_friend_requests, get_following_map, get_top_friends
from neonrest.utils.vibe_lifecycle import (add_post_vibes, approve_vibe, can_approve_vibes,
                                  default_vibe_css, init_vibe_tables, is_pending, minimum_users,
                                  supporter_count, vibe_slug)
from neonrest.utils.image_uploads import allowed_file   # ✅ Your image upload helper

from neonrest.routes.friends import bp as friends_bp  # ✅ IMPORT FIRST
from neonrest.utils.utils import generate_unique_handle, build_comment_tree, encode_base62



VALID_REACTS = ["👍", "👎", "🕶️", "💖", "💩", "🤮", "❓", "🔥", "🐐", "🦙"]

# Basic logging setup
logging.basicConfig(level=logging.DEBUG)

# SQLite DB path
DATABASE = os.environ.get('NEONREST_PRODUCTION_DATABASE', '/home/sinbot/db/neonrest.db')

app = Flask(__name__, instance_path=os.environ.get('NEONREST_PRODUCTION_INSTANCE', '/home/sinbot/private/neonrest_production/instance'))
app.config['DATABASE'] = DATABASE

@app.template_filter('readable_badge_text')
def readable_badge_text(text, background):
    """Keep a theme color when legible; otherwise choose a contrasting badge label."""
    def luminance(value):
        if not isinstance(value, str) or not value.startswith('#'):
            return None
        digits = value[1:]
        if len(digits) == 3:
            digits = ''.join(ch * 2 for ch in digits)
        if len(digits) != 6:
            return None
        try:
            rgb = [int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        except ValueError:
            return None
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return sum(c * weight for c, weight in zip(channels, (0.2126, 0.7152, 0.0722)))

    bg = luminance(background)
    fg = luminance(text)
    if bg is None:
        return text or '#ffffff'
    if fg is not None and (max(bg, fg) + 0.05) / (min(bg, fg) + 0.05) >= 4.5:
        return text
    return '#ffffff' if (1.05 / (bg + 0.05)) >= ((bg + 0.05) / 0.05) else '#000000'



# Register blueprint AFTER app is created
app.register_blueprint(friends_bp)  # ✅ REGISTER HERE

# Secret key for token generation
# Keep sandbox sessions separate from production and persist signing across reloads.
_sandbox_key_file = os.environ.get('NEONREST_PRODUCTION_SECRET_FILE', '/home/sinbot/private/neonrest_production/session-secret')
os.makedirs(os.path.dirname(_sandbox_key_file), mode=0o700, exist_ok=True)
try:
    _key_fd = os.open(_sandbox_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(_key_fd, 'wb') as _key_stream:
        _key_stream.write(secrets.token_bytes(32))
with open(_sandbox_key_file, 'rb') as _key_stream:
    app.secret_key = _key_stream.read()
app.config.update(
    SESSION_COOKIE_NAME='neonrest_session',
    SESSION_COOKIE_PATH='/',
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)


# Purelymail SMTP configuration for the sandbox.
app.config['MAIL_SERVER'] = 'smtp.purelymail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'noreply@neonrest.com'
_purelymail_password_file = os.path.expanduser('~/.neonrest_sandbox_purelymail_password')
app.config['MAIL_PASSWORD'] = os.getenv('NEONREST_PRODUCTION_PURELYMAIL_PASSWORD')
if not app.config['MAIL_PASSWORD'] and os.path.isfile(_purelymail_password_file):
    with open(_purelymail_password_file, encoding='utf-8') as _mail_password_stream:
        app.config['MAIL_PASSWORD'] = _mail_password_stream.read()
app.config['MAIL_DEFAULT_SENDER'] = ('Neonrest', 'noreply@neonrest.com')

# Initialize Flask-Mail
mail = Mail(app)

# Token serializer
s = itsdangerous.URLSafeTimedSerializer(app.secret_key)



def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])  # <- this matters
        g.db.row_factory = sqlite3.Row
        register_db_functions(g.db)
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

from neonrest import public_ids as identifiers

def decode_prefixed_id(value):
    return identifiers.resolve(get_db(),'comment',value)

def init_db():
    db = get_db()
    db.execute('CREATE TABLE IF NOT EXISTS post_edit_history (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, content TEXT NOT NULL, vibe TEXT, circle TEXT, version_at TEXT, replaced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            handle TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            bio TEXT
        );
    ''')
    # Leave historical accounts unrecorded: never infer an acceptance.
    acceptance_columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
    for column in ('legal_terms_version', 'legal_privacy_version', 'legal_accepted_at'):
        if column not in acceptance_columns:
            db.execute('ALTER TABLE users ADD COLUMN ' + column + ' TEXT')
    db.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            vibe TEXT CHECK (length(vibe) <= 100),
            circle TEXT CHECK (length(circle) <= 100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS friend_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'declined')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sender_id, receiver_id)
        );
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,
            followed_id INTEGER NOT NULL,
            revoked BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, followed_id)
        );
    ''')

    # Existing accounts keep their data when optional profile fields are added.
    user_columns = {column['name'] for column in db.execute('PRAGMA table_info(users)')}
    for column in ('relationship_status', 'location', 'pets'):
        if column not in user_columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT DEFAULT ''")
    db.execute('''CREATE TABLE IF NOT EXISTS user_moderation (
        user_id INTEGER PRIMARY KEY, banned INTEGER NOT NULL DEFAULT 0,
        posting_restricted INTEGER NOT NULL DEFAULT 0,
        interaction_restricted INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '', updated_by INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS moderated_posts (
        post_id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL,
        hidden_by INTEGER NOT NULL, reason TEXT NOT NULL,
        hidden_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS moderation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
        target_user_id INTEGER, post_id INTEGER, action TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    init_staff_workflow_tables(db)
    init_ad_tables(db)
    init_vibe_tables(db)
    db.commit()


def init_staff_workflow_tables(db):
    """Idempotent schema for reversible comment actions and staff review queues."""
    db.execute('''CREATE TABLE IF NOT EXISTS moderated_comments (
        comment_id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL,
        hidden_by INTEGER NOT NULL, reason TEXT NOT NULL,
        hidden_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS content_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL,
        target_type TEXT NOT NULL CHECK(target_type IN ('user','post','comment')),
        target_id INTEGER NOT NULL, reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','dismissed')),
        reviewed_by INTEGER, reviewed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS moderation_appeals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, appellant_id INTEGER NOT NULL,
        target_type TEXT NOT NULL CHECK(target_type IN ('ban','posting','interaction','post','comment')),
        target_id INTEGER NOT NULL, reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','upheld','overturned')),
        reviewed_by INTEGER, decision_reason TEXT, reviewed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_reports_status ON content_reports(status, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_appeals_status ON moderation_appeals(status, id DESC)')
    for column in ('comment_id', 'report_id', 'appeal_id'):
        existing = {field['name'] for field in db.execute('PRAGMA table_info(moderation_events)')}
        if column not in existing:
            db.execute(f'ALTER TABLE moderation_events ADD COLUMN {column} INTEGER')
    db.commit()
def init_ad_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ad_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL,
        destination_url TEXT NOT NULL, image_path TEXT NOT NULL DEFAULT '',
        placement TEXT NOT NULL CHECK(placement IN ('rail','banner')),
        vibe_id INTEGER, active INTEGER NOT NULL DEFAULT 0,
        starts_at TEXT, ends_at TEXT, created_by INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS ad_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL,
        event_type TEXT NOT NULL CHECK(event_type IN ('impression','click')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS ad_management_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL,
        actor_id INTEGER NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_ad_events_campaign ON ad_events(campaign_id,event_type,created_at)')
    db.commit()


def post_page():
    try:
        page = int(request.args.get('page','1'))
    except ValueError:
        abort(400)
    if page < 1 or page > 10000:
        abort(400)
    return page


def ad_selection(db, vibe_id=None):
    # Database randomness supplies a new selection on navigation without timed refreshes.
    rows = db.execute('''SELECT * FROM ad_campaigns WHERE active=1
        AND (starts_at IS NULL OR datetime(starts_at) <= CURRENT_TIMESTAMP)
        AND (ends_at IS NULL OR datetime(ends_at) > CURRENT_TIMESTAMP)
        AND (vibe_id IS NULL OR vibe_id=?) ORDER BY RANDOM() LIMIT 20''', (vibe_id,)).fetchall()
    rail = [dict(row) for row in rows if row['placement']=='rail'][:4]
    banner = next((dict(row) for row in rows if row['placement']=='banner'), None)
    # Count only selections actually rendered; no member identifier or cookie is stored.
    for ad in rail + ([banner] if banner else []):
        db.execute("INSERT INTO ad_events(campaign_id,event_type) VALUES (?,'impression')", (ad['id'],))
    if rail or banner:
        db.commit()
    return rail,banner


def validated_ad_destination(value):
    parsed=urlparse(value)
    if parsed.scheme not in ('https','http') or not parsed.netloc or parsed.username or parsed.password or len(value)>500:
        return False
    return True


def validated_ad_image(value):
    # Local static art only: external images would let sponsors track page views.
    return not value or (value.startswith('/static/') and '..' not in value and len(value)<=300)


def can_edit_vibe_settings(user_id, vibe):
    if not user_id:
        return False
    db = get_db()
    account = db.execute('SELECT verified FROM users WHERE id = ?', (user_id,)).fetchone()
    if not account or not account['verified']:
        return False
    if user_id == 1:
        return True
    if db.execute("SELECT 1 FROM staff_roles WHERE user_id = ? AND role IN ('admin', 'manager')", (user_id,)).fetchone():
        return True
    if vibe is None:
        return False
    db.execute("CREATE TABLE IF NOT EXISTS vibe_editors (vibe_id INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (vibe_id, user_id))")
    return db.execute('SELECT 1 FROM vibe_editors WHERE vibe_id = ? AND user_id = ?',
                      (vibe['id'], user_id)).fetchone() is not None


def can_edit_theme(user_id, theme):
    return user_id == 1

def get_logged_in_user():
    email = session.get('user_email')
    if not email:
        return None
    db = get_db()
    return db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

def profile_edit_token():
    if 'profile_edit_token' not in session:
        session['profile_edit_token'] = secrets.token_urlsafe(32)
    return session['profile_edit_token']


app.jinja_env.globals['profile_edit_token'] = profile_edit_token


def valid_profile_edit_token():
    expected = session.get('profile_edit_token', '')
    submitted = request.form.get('profile_edit_token', '')
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


def init_profile_styles(db):
    db.execute("""CREATE TABLE IF NOT EXISTS profile_styles (
        user_id INTEGER NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('day', 'night')),
        custom_css TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, mode))""")


def valid_profile_css(css):
    # This style is rendered on a public page; prohibit markup escapes and remote resources.
    if len(css) > 30000 or any(char in css for char in '<\\'):
        return False
    stripped = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    if '@' in re.sub(r'@media\b', '', stripped, flags=re.I):
        return False
    if ('/*' in stripped or '*/' in stripped or '://' in stripped or 'data:' in stripped.lower()
            or re.search(r'\b(?:url|expression|behavior|image-set|cross-fade|paint|src)\s*[:(]', stripped, re.I)):
        return False
    return stripped.count('{') == stripped.count('}') and stripped.count('{') <= 150


@app.route('/profile/style/<mode>', methods=['GET', 'POST'])
def edit_profile_style(mode):
    if mode not in ('day', 'night'):
        abort(404)
    viewer = get_logged_in_user()
    if not viewer or session.get('user_id') != viewer['id']:
        abort(403)
    db = get_db()
    init_profile_styles(db)
    if request.method == 'POST':
        if not valid_profile_edit_token():
            abort(400)
        css = request.form.get('custom_css', '')
        if not valid_profile_css(css):
            flash('CSS must be under 30 KB and use local style rules (no imports, URLs, or markup).', 'error')
        else:
            db.execute("""INSERT INTO profile_styles (user_id, mode, custom_css)
                VALUES (?, ?, ?) ON CONFLICT(user_id, mode) DO UPDATE SET
                custom_css = excluded.custom_css, updated_at = CURRENT_TIMESTAMP""",
                (viewer['id'], mode, css))
            db.commit()
            flash(f'{mode.capitalize()} profile style saved.', 'success')
            if request.form.get('action') == 'preview':
                return redirect(url_for('user_by_handle', handle=viewer['handle'].lstrip('@'), mode=mode))
            return redirect(url_for('edit_profile_style', mode=mode))
    from pathlib import Path
    style = db.execute('SELECT custom_css FROM profile_styles WHERE user_id = ? AND mode = ?',
                       (viewer['id'], mode)).fetchone()
    return render_template('edit_profile_style.html', user=viewer, mode=mode,
                           custom_css=style['custom_css'] if style else
                           (Path(__file__).parent / 'static' / 'profile_default.css').read_text())


@app.route('/profile/update', methods=['POST'])
def update_profile():
    viewer = get_logged_in_user()
    if not viewer or session.get('user_id') != viewer['id']:
        abort(403)
    if not valid_profile_edit_token():
        abort(400)

    field = request.form.get('field')
    db = get_db()
    if field == 'bio':
        bio = request.form.get('bio', '').strip()
        if len(bio) > 2000:
            abort(400)
        db.execute('UPDATE users SET bio = ? WHERE id = ?', (bio, viewer['id']))
        flash('Bio updated.', 'success')
    elif field == 'timezone':
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        timezone = request.form.get('timezone', '').strip()
        if timezone:
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                abort(400)
        db.execute('UPDATE users SET timezone = ? WHERE id = ?', (timezone or None, viewer['id']))
        flash('Timezone updated.', 'success')
    elif field == 'icebreakers':
        values = {name: request.form.get(name, '').strip() for name in ('relationship_status', 'location', 'pets')}
        if any(len(values[name]) > limit for name, limit in (('relationship_status', 80), ('location', 120), ('pets', 300))):
            abort(400)
        db.execute('UPDATE users SET relationship_status = ?, location = ?, pets = ? WHERE id = ?',
                   (values['relationship_status'], values['location'], values['pets'], viewer['id']))
        flash('Icebreakers updated.', 'success')
    else:
        abort(400)
    db.commit()
    return redirect(url_for('user_by_handle', handle=viewer['handle'].lstrip('@')))


with app.app_context():
    os.makedirs('db', exist_ok=True)
    init_db()

@app.route("/test")
def test():
    return "It works!"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

from datetime import datetime

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        if request.form.get('consent') not in ('on', '1'):
            abort(400, description='Agree to the Terms and acknowledge the Privacy Policy before signing up.')
        actual_name = ' '.join(request.form.get('actual_name', '').split())
        if not actual_name or len(actual_name) > 100 or any(ord(c) < 32 or ord(c) == 127 for c in actual_name):
            abort(400, description='Enter your actual name (up to 100 characters). It is kept private.')
        email = request.form['email'].strip()
        handle = '@' + request.form['handle'].strip().lstrip('@')
        password = request.form['password']

        # Ensure email is valid
        try:
            validate_email(email)
        except Exception as e:
            flash(str(e), 'error')
            return redirect(url_for('signup'))

        hashed = generate_password_hash(password)

        db = get_db()

        # Check if email or handle already exists
        existing = db.execute('SELECT 1 FROM users WHERE handle IN (?, ?) OR email = ? COLLATE NOCASE', (handle, handle.lstrip('@'), email)).fetchone()
        if existing:
            flash("That handle or email is already in use. Try something else!", 'error')
            return redirect(url_for('signup'))

        # Insert the user with verified = 0 and a created_at timestamp
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        avatar_filename = None  # placeholder until avatar uploads are implemented

        try:
            with db:
                created = db.execute('''
                    INSERT INTO users (email, handle, password_hash, verified, avatar, created_at, dob, actual_name, timezone)
                    VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)
                ''', (email, handle, hashed, avatar_filename, created_at, g.signup_dob, actual_name, g.signup_timezone))
                db.execute("UPDATE users SET legal_terms_version=?, legal_privacy_version=?, legal_accepted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                           ('2026-10-13-production', '2026-10-14-production', created.lastrowid))
                db.execute('INSERT INTO age_clocks(user_id,zone,confirmed) VALUES (?,?,1)',(created.lastrowid,g.signup_timezone))
                # Every new member starts with @brendoom as a friend and in Top 9.
                first_friend = db.execute(
                    "SELECT id FROM users WHERE lower(handle) = '@brendoom'"
                ).fetchone()
                if first_friend and first_friend['id'] != created.lastrowid:
                    db.execute('''
                        INSERT INTO friend_requests (sender_id, receiver_id, status)
                        VALUES (?, ?, 'accepted')
                    ''', (first_friend['id'], created.lastrowid))
                    db.execute('''
                        INSERT INTO top_friends (user_id, friend_id, position_t9)
                        VALUES (?, ?, 1)
                    ''', (created.lastrowid, first_friend['id']))
        except sqlite3.IntegrityError:
            flash('That handle or email is already in use. Try something else!', 'error')
            return redirect(url_for('signup'))

        from neonrest.email_verification import send_verification
        delivered = send_verification(sys.modules[__name__],db,email)
        if delivered is False:
            flash("Account created, but the verification email could not be delivered. Try Resend verification email on the sign-in page.", "error")
            return redirect(url_for("login"))

        flash("Account created. Your verification email is queued; check your inbox shortly." if delivered=='queued' else "A verification email has been sent. Please check your inbox.", 'success')
        return redirect('/login')

    return render_template('signup.html')

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    viewer = get_logged_in_user()
    if not viewer or session.get('user_id') != viewer['id']:
        abort(403)
    if not valid_profile_edit_token():
        abort(400)

    file = request.files.get('avatar')
    if not file or not file.filename:
        flash('Choose an image first.', 'error')
        return redirect(url_for('user_by_handle', handle=viewer['handle'].lstrip('@')))

    import io
    from PIL import Image, ImageOps, UnidentifiedImageError
    raw = file.stream.read(1800 * 1024 + 1)
    if len(raw) > 1800 * 1024:
        flash('Avatar images must be under 1.8 MB.', 'error')
        return redirect(url_for('user_by_handle', handle=viewer['handle'].lstrip('@')))
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in ('JPEG', 'PNG', 'WEBP', 'GIF') or image.width * image.height > 16_000_000:
            raise ValueError('Unsupported avatar')
        image = ImageOps.exif_transpose(image)
        image.thumbnail((512, 512))
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
        avatar_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'avatars')
        os.makedirs(avatar_dir, exist_ok=True)
        filename = f"user_{viewer['id']}_avatar.png"
        target = os.path.join(avatar_dir, filename)
        temporary = target + '.' + secrets.token_hex(8) + '.tmp'
        try:
            image.save(temporary, format='PNG')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        flash('Please choose a valid JPG, PNG, WebP, or GIF image.', 'error')
        return redirect(url_for('user_by_handle', handle=viewer['handle'].lstrip('@')))

    avatar_url = url_for('static', filename=f'uploads/avatars/{filename}') + '?v=' + secrets.token_hex(6)
    db = get_db()
    db.execute('UPDATE users SET avatar_path = ? WHERE id = ?', (avatar_url, viewer['id']))
    db.commit()
    flash('Avatar updated.', 'success')
    return redirect(url_for('user_by_handle', handle=viewer['handle'].lstrip('@')))


@app.route('/check_handle')
def check_handle():
    handle = request.args.get('handle', '').strip()
    if not handle.startswith("@"):
        handle = "@" + handle
    db = get_db()
    exists = db.execute('SELECT 1 FROM users WHERE handle = ?', (handle,)).fetchone()
    return jsonify({'available': not bool(exists)})

@app.route('/verify_email/<token>')
def verify_email(token):
    try:
        email = s.loads(token, salt="email-verification", max_age=3600)
    except itsdangerous.SignatureExpired:
        flash("The verification link has expired.", 'error')
        return redirect('/signup')
    except itsdangerous.BadSignature:
        flash("The verification link is invalid.", 'error')
        return redirect('/signup')

    db = get_db()
    db.execute('UPDATE users SET verified = 1 WHERE email = ?', (email,))
    db.commit()
    flash("Your email has been verified!", 'success')
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        db = get_db()

        # Fetch the user by email
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            # Check if the email is verified
            if user['verified'] == 0:
                from neonrest.email_verification import send_verification
                send_verification(sys.modules[__name__],db,user['email'])
                flash('Please verify your email before signing in.', 'info')
                return redirect(url_for('verification_request'))
        # If the email is verified, log them in
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            session['user_handle'] = user['handle']

            if db.execute('SELECT 1 FROM user_moderation WHERE user_id = ? AND banned = 1', (user['id'],)).fetchone():
                flash('This account is restricted. You can review or submit an appeal.', 'info')
                return redirect(url_for('my_appeals'))

            flash('Logged in successfully.', 'success')
            return redirect(url_for('user_by_handle', handle=user['handle'].lstrip('@')))

        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')

@app.route('/@<handle>')
def user_by_handle(handle):
    handle = handle.lstrip('@')
    user = get_db().execute('''SELECT id FROM users WHERE handle IN (?, ?)
        ORDER BY CASE WHEN handle = ? THEN 0 ELSE 1 END LIMIT 1''',
        ('@' + handle, handle, '@' + handle)).fetchone()
    if user is None:
        flash('User not found.', 'error')
        return redirect('/')
    return user_page_test(user['id'])


@app.route('/user/<int:user_id>')
def user_page(user_id):
    user = get_db().execute('SELECT handle FROM users WHERE id = ?', (user_id,)).fetchone()
    if user is None:
        flash('User not found.', 'error')
        return redirect('/')
    return redirect(url_for('user_by_handle', handle=user['handle'].lstrip('@')))


@app.route('/user_test/<int:user_id>')
def user_page_test(user_id):
    db = get_db()
    init_profile_styles(db)
    user = db.execute(
        'SELECT * FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()

    if user:
        user = redacted_profile(db, user, session.get('user_id'))
        from neonrest import age_policy as ages
        if ages.limited_staff_profile(db,user_id,session.get('user_id')):
            return render_template('staff_profile.html', staff_handle=user['handle'],
                staff_avatar=user['avatar_path'], staff_id=user_id,
                staff_role='Administrator' if has_staff_permission(db,user_id,'manage_roles') else 'Moderator')
    # -- Now Playing --
    now_playing_text = None
    now_playing_url = None
    if user and user['lastfm_username']:
        try:
            now = get_now_playing(user['lastfm_username'])
            now_playing_text = now.get('track')
            now_playing_url = now.get('url')
        except Exception as e:
            app.logger.warning(f"[Last.fm] Error: {e}")

    if not user:
        flash('User not found.', 'error')
        return redirect('/')

    viewer = get_logged_in_user()
    viewer_id = viewer['id'] if viewer and session.get('user_id') == viewer['id'] else None
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        local_hour = datetime.now(ZoneInfo(user['timezone'] or 'UTC')).hour
    except (ZoneInfoNotFoundError, ValueError):
        local_hour = datetime.now(ZoneInfo('UTC')).hour
    requested_mode = request.args.get('mode')
    profile_mode = requested_mode if requested_mode in ('day', 'night') else ('day' if 6 <= local_hour < 18 else 'night')
    profile_style = db.execute('SELECT custom_css FROM profile_styles WHERE user_id = ? AND mode = ?',
                               (user_id, profile_mode)).fetchone()
    profile_css = profile_style['custom_css'] if profile_style and valid_profile_css(profile_style['custom_css']) else ''

    # -- Friend / follow data --
    incoming, outgoing = get_friend_requests(viewer_id)
    pending_received_from = [r['sender_id'] for r in incoming]
    following_map = get_following_map(viewer_id)

    # -- Friend Status Map --
    friend_status_map = {}
    if viewer_id:
        relationships = db.execute(
            '''
            SELECT sender_id, receiver_id, status
            FROM friend_requests
            WHERE sender_id = ? OR receiver_id = ?
            ''',
            (viewer_id, viewer_id)
        ).fetchall()
        for r in relationships:
            other_id = r['receiver_id'] if r['sender_id'] == viewer_id else r['sender_id']
            friend_status_map[other_id] = r['status']

    # -- Friends & Top Friends --
    friends = db.execute(
        '''
        SELECT u.id, u.handle, u.codename
        FROM users u
        JOIN friend_requests fr ON (
            (fr.sender_id = ? AND fr.receiver_id = u.id) OR
            (fr.receiver_id = ? AND fr.sender_id = u.id)
        )
        WHERE fr.status = 'accepted' AND community_profile_visible(u.id)=1
        ''',
        (user_id, user_id)
    ).fetchall()
    top_friends = get_top_friends(db, user['id'])

    # -- Fetch posts --
    rows = db.execute(
        '''
        SELECT posts.id, posts.user_id, posts.target_user_id, posts.content,
               posts.circle, posts.created_at, posts.last_edited,
               GROUP_CONCAT(vibes.name, ', ') AS vibes,
               u.handle       AS author_handle,
               u.codename     AS author_codename,
               u.avatar_path  AS author_avatar,
               target.handle  AS target_handle
        FROM posts
        JOIN users u ON posts.user_id = u.id
        LEFT JOIN users target ON posts.target_user_id = target.id
        LEFT JOIN post_vibes ON posts.id = post_vibes.post_id
        LEFT JOIN vibes ON post_vibes.vibe_id = vibes.id
        WHERE (posts.user_id = ? OR posts.target_user_id = ?)
          AND NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id = posts.id) AND community_post_visible(posts.id)=1
        GROUP BY posts.id
        ORDER BY posts.created_at DESC
        ''',
        (user_id, user_id)
    ).fetchall()

    # -- Build posts_with_html & Base62 map --
    posts_with_html = []
    post_ids = []
    base62_map = {}
    for row in rows:
        raw_id = row['id']
        b62 = identifiers.public(db,'post',raw_id)
        post = dict(row)
        post.update({
            'id': raw_id,
            'base62_id': b62,
            'vibes': row['vibes'] or '',
            'html_content': markdown2.markdown(row['content'], safe_mode='escape'),
            'author_handle': row['author_handle'].lstrip('@'),
            'target_handle': row['target_handle'].lstrip('@') if row['target_handle'] else None,
            'author_avatar': row['author_avatar'] or '/static/default-avatar.png',
            'is_guestbook_outbound': (
                row['target_user_id'] is not None and
                row['target_user_id'] != row['user_id']
            )
        })
        posts_with_html.append(post)
        post_ids.append(raw_id)
        base62_map[raw_id] = b62

    # -- Reactions & Reactors --
    reaction_map = {}
    if post_ids:
        placeholders = ','.join(['?'] * len(post_ids))
        reaction_rows = db.execute(f'''
            SELECT post_id, emoji, COUNT(*) AS count
            FROM post_reactions
            WHERE post_id IN ({placeholders})
            GROUP BY post_id, emoji
        ''', post_ids).fetchall()
        for r in reaction_rows:
            reaction_map.setdefault(r['post_id'], {})[r['emoji']] = r['count']
    for post in posts_with_html:
        post['reaction_counts'] = reaction_map.get(post['id'], {})

    post_reactors = {}
    if post_ids:
        placeholders = ','.join(['?'] * len(post_ids))
        reactor_rows = db.execute(f'''
            SELECT pr.post_id, pr.emoji, u.handle
            FROM post_reactions pr
            JOIN users u ON pr.user_id = u.id
            WHERE pr.post_id IN ({placeholders})
        ''', post_ids).fetchall()
        for r in reactor_rows:
            b62 = base62_map.get(r['post_id'])
            post_reactors.setdefault(b62, {}).setdefault(r['emoji'], []).append(r['handle'])

    # -- Comments threaded --
    comments_raw = []
    if post_ids:
        placeholders = ','.join(['?'] * len(post_ids))
        comments_raw = db.execute(f'''
            SELECT c.id, c.post_id, c.user_id, c.content, c.parent_comment_id,
                   c.last_edited, u.handle, u.avatar_path
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.post_id IN ({placeholders})
              AND NOT EXISTS (SELECT 1 FROM moderated_comments mc WHERE mc.comment_id=c.id) AND community_member_visible(c.user_id)=1 AND age_comment_visible(c.id)=1
            ORDER BY c.created_at ASC
        ''', post_ids).fetchall()
    post_comments = {}
    for c in comments_raw:
        pid, par = c['post_id'], c['parent_comment_id']
        cid = identifiers.public(db,'comment',c['id'])
        comment = {
            'id': cid,
            'raw_id': c['id'],
            'post_id': identifiers.public(db,'post',pid),
            'parent_comment_id': identifiers.optional(db,'comment',par) if par else None,
            'user_id': c['user_id'],
            'author_handle': c['handle'].lstrip('@'),
            'avatar': c['avatar_path'] or '/static/default-avatar.png',
            'content': c['content'],
            'last_edited': c['last_edited'],
            'replies': []
        }
        post_comments.setdefault(comment['post_id'], []).append(comment)
    for post in posts_with_html:
        post['comments'] = build_comment_tree(post_comments.get(post['base62_id'], []))

    # ——— Load vibe theme metadata ———
    vibe_rows = db.execute('''
        SELECT v.name       AS vibe,
               t.bg_color   AS bg,
               t.text_color AS text,
               t.glow_color AS glow,
               t.css_class  AS css_class
        FROM vibes v
        JOIN themes t ON v.theme_id = t.id
    ''').fetchall()
    vibe_metadata = {
        row['vibe']: {
            'bg':        row['bg'],
            'text':      row['text'],
            'glow':      row['glow'],
            'css_class': row['css_class']
        }
        for row in vibe_rows
    }

    # -- Render --
    return render_template(
        'user_test.html',
        user=redacted_profile(db, user, viewer_id),
        posts=posts_with_html,
        viewer_id=viewer_id,
        following_map=following_map,
        incoming_requests=incoming,
        outgoing_requests=outgoing,
        friend_status_map=friend_status_map,
        pending_received_from=pending_received_from,
        friends=friends,
        top_friends=top_friends,
        now_playing_text=now_playing_text,
        now_playing_url=now_playing_url,
        post_reactors=post_reactors,
        VALID_REACTS=VALID_REACTS,
        vibe_metadata=vibe_metadata,
        profile_css=profile_css,
        profile_mode=profile_mode
    )



@app.route('/update_bio', methods=['POST'])
def update_bio():
    if 'user_id' not in session:
        flash("You must be logged in to edit your bio.", "error")
        return redirect("/login")

    new_bio = request.form.get("bio", "").strip()
    db = get_db()
    db.execute('UPDATE users SET bio = ? WHERE id = ?', (new_bio, session['user_id']))
    db.commit()
    flash("Bio updated!", "success")
    return redirect(f"/{session['user_handle']}")

@app.route('/account', methods=['GET', 'POST'])
def account():
    if 'user_id' not in session:
        flash("Please log in to access your account.", 'error')
        return redirect('/login')

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if request.method == 'POST':
        if 'handle' in request.form:
            new_handle = request.form['handle'].strip()
            if not new_handle.startswith("@"):
                new_handle = "@" + new_handle

            if not re.match(r'^@[\w.+-]+$', new_handle) or any(char in new_handle for char in "\\/()[]=!"):
                flash("That handle contains invalid characters.", 'error')
            else:
                existing = db.execute('SELECT * FROM users WHERE handle = ? AND id != ?',
                                      (new_handle, user['id'])).fetchone()
                if existing:
                    flash("That handle is already taken.", 'error')
                else:
                    db.execute('UPDATE users SET handle = ? WHERE id = ?', (new_handle, user['id']))
                    session['user_handle'] = new_handle
                    flash("Handle updated successfully.", 'success')

        if 'codename' in request.form:
            new_codename = request.form['codename'].strip()
            db.execute('UPDATE users SET codename = ? WHERE id = ?', (new_codename, user['id']))
            flash("Codename updated successfully.", 'success')

        if 'timezone' in request.form:
            tz = request.form['timezone'].strip() or None
            db.execute('UPDATE users SET timezone = ? WHERE id = ?', (tz, user['id']))
            flash("Timezone updated successfully.", "success")

        if 'lastfm_username' in request.form:
            new_lfm = request.form['lastfm_username'].strip()
            db.execute('UPDATE users SET lastfm_username = ? WHERE id = ?', (new_lfm, user['id']))
            flash("Last.fm username updated successfully.", "success")

        if 'new_password' in request.form:
            new_password = request.form['new_password'].strip()
            if new_password:
                new_hash = generate_password_hash(new_password)
                db.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user['id']))
                flash("Password updated successfully.", 'success')

        db.commit()

    return render_template('account.html', user=user)


@app.route("/now_playing/<username>")
def now_playing(username):
    from neonrest.utils.lastfm import get_now_playing
    import sys

    print(f"Now Playing check for {username}", file=sys.stderr)
    result = get_now_playing(username)
    print(f"Result: {result}", file=sys.stderr)

    return jsonify(result)

def save_post_image():
    """Validate and re-encode an image with required alt text."""
    upload = request.files.get('post_image')
    if not upload or not upload.filename:
        return ''
    alt = request.form.get('image_alt', '').strip()
    if not alt or len(alt) > 180:
        abort(400, description='Provide image alt text (up to 180 characters).')
    raw = upload.stream.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        abort(413, description='Post images must be 5 MB or smaller.')
    import io, uuid
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in ('JPEG', 'PNG', 'WEBP', 'GIF') or image.width * image.height > 20_000_000:
            abort(400, description='Choose a JPEG, PNG, WebP or GIF under 20 megapixels.')
        image = ImageOps.exif_transpose(image)
        image.thumbnail((2200, 2200))
        image = image.convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        abort(400, description='The selected image could not be read.')
    folder = os.path.join(app.static_folder, 'uploads', 'posts')
    os.makedirs(folder, exist_ok=True)
    filename = uuid.uuid4().hex + '.jpg'
    image.save(os.path.join(folder, filename), 'JPEG', quality=85, optimize=True)
    safe_alt = alt.replace(chr(92), "").replace("]", "").replace("[", "")
    return f"![{safe_alt}]({url_for('static', filename='uploads/posts/' + filename)})"


@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    print("🟢 This is the updated /create_post route")
    if 'user_id' not in session:
        flash("Please log in to post.", 'error')
        return redirect('/login')

    user_id = session['user_id']
    db = get_db()

    if request.method == 'POST':
        from neonrest import welcome
        welcome.validate_flag(db,user_id)
        content = request.form['content'].strip()
        media = prepare_post_media()
        init_media_tables(db)
        vibes_input = request.form.get('vibes', '').strip()
        circle = request.form.get('circle', '').strip()
        target_user_id = int(request.form.get('target_user_id', user_id))

        if not content and not media:
            flash("Add text or an attachment to post.", 'error')
        else:
            now = datetime.utcnow().isoformat()

            db.execute('BEGIN IMMEDIATE')
            post_key=identifiers.next_post_key(db)
            cursor = db.execute('''
                INSERT INTO posts (id,user_id, target_user_id, content, circle, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (post_key,user_id, target_user_id, content, circle, now))
            identifiers.ensure(db,'post',post_key)
            db.execute('INSERT INTO post_privacy(post_id,audience) VALUES (?,?)', (cursor.lastrowid, g.new_post_audience))
            from neonrest.age_policy import age
            if age(db,user_id) is not None and age(db,user_id)<18:
                db.execute('INSERT OR IGNORE INTO protected_age_posts VALUES (?)',(cursor.lastrowid,))
            if target_user_id != user_id:
                notify(db, target_user_id, 'comments', 'A member posted in your guestbook.', '/@'+session['user_handle'].lstrip('@'), user_id)
            welcome.save_flag(db,cursor.lastrowid,user_id)
            attach_post_media(db, cursor.lastrowid, media)
            vibe_names = vibes_input.split(',')
            add_post_vibes(db, cursor.lastrowid, vibe_names)
            db.commit()

            flash("Post created!", 'success')
            return redirect(url_for('user_page', user_id=target_user_id))

    # If GET, render standalone page
    return render_template('create_post.html')

@app.route('/create_comment', methods=['POST'])
def create_comment():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    # 1) Grab & validate form fields
    content        = request.form.get('content', '').strip()
    raw_b62_post   = request.form.get('post_id')
    raw_b62_parent = request.form.get('parent_comment_id') or None

    if not content or not raw_b62_post:
        return jsonify({'error': 'Missing content or post_id'}), 400

    # Resolve the public post identifier to its internal key
    try:
        post_id = identifiers.resolve(get_db(),'post',raw_b62_post)

    except ValueError:
        return jsonify({"error": "Invalid post_id"}), 400

    if raw_b62_parent:
        try:
            parent_id = decode_prefixed_id(raw_b62_parent)
        except:
            return jsonify({'error': 'Invalid parent_comment_id'}), 400
    else:
        parent_id = None

    # 3) Insert row, get its integer PK
    db = get_db()
    if db.execute('SELECT 1 FROM moderated_posts WHERE post_id=?', (post_id,)).fetchone():
        abort(404)
    if parent_id is not None and (not db.execute('SELECT 1 FROM comments WHERE id=? AND post_id=?', (parent_id, post_id)).fetchone()
            or db.execute('SELECT 1 FROM moderated_comments WHERE comment_id=?', (parent_id,)).fetchone()):
        abort(404)
    cur = db.execute(
        'INSERT INTO comments (user_id, post_id, parent_comment_id, content) VALUES (?, ?, ?, ?)',
        (session['user_id'], post_id, parent_id, content)
    )
    raw_id = cur.lastrowid
    identifiers.ensure(db,'comment',raw_id)
    from neonrest.age_policy import age
    if age(db,session['user_id']) is not None and age(db,session['user_id'])<18:
        db.execute('INSERT OR IGNORE INTO protected_age_comments VALUES (?)',(raw_id,))
    owner = db.execute('SELECT user_id FROM posts WHERE id=?', (post_id,)).fetchone()
    notify(db, owner['user_id'], 'comments', 'A member commented on your post.', f'/posts/{post_id}#comment-{raw_id}', session['user_id'])
    if parent_id:
        parent = db.execute('SELECT user_id FROM comments WHERE id=?', (parent_id,)).fetchone()
        if parent and parent['user_id'] != owner['user_id']:
            notify(db, parent['user_id'], 'replies', 'A member replied to your comment.', f'/posts/{post_id}#comment-{raw_id}', session['user_id'])
    db.commit()

    # 4) Read the stable random public comment identifier
    b62 = identifiers.public(db,'comment',raw_id)

    # 5) Return JSON (no 500s!)
    return jsonify({
        'status':            'ok',
        'id':                b62,
        'post_id':           identifiers.public(db,'post',post_id),
        'parent_comment_id': identifiers.optional(db,'comment',parent_id) if parent_id else None
    }), 201



# EDIT COMMENT
@app.route('/edit_comment/<string:comment_id>', methods=['GET', 'POST'])
def edit_comment(comment_id):
    # -- Authentication check --
    if 'user_id' not in session:
        flash('Please log in to edit comments.', 'error')
        return redirect(request.referrer or '/')

    # -- Resolve the public comment ID to the internal key --
    try:
        row_id = decode_prefixed_id(comment_id)
    except Exception:
        flash('Invalid comment ID.', 'error')
        return redirect(request.referrer or '/')

    # -- Lazy import to avoid circular dependency --
    db = get_db()

    # -- Fetch the existing comment including last_edited --
    comment = db.execute(
        'SELECT id, user_id, content, last_edited FROM comments WHERE id = ?',
        (row_id,)
    ).fetchone()
    if db.execute('SELECT 1 FROM moderated_comments WHERE comment_id=?', (row_id,)).fetchone():
        abort(404)
    if not comment:
        flash('Comment not found.', 'error')
        return redirect(request.referrer or '/')

    # -- Authorization check --
    if comment['user_id'] != session.get('user_id'):
        flash('You do not have permission to edit this comment.', 'error')
        return redirect(request.referrer or '/')

    if request.method == 'POST':
        new_content = request.form.get('content', '').strip()
        if not new_content:
            flash('Content cannot be empty.', 'error')
            return render_template('edit_comment.html', comment=comment)

        # -- Update content and last_edited timestamp --
        db.execute(
            'UPDATE comments SET content = ?, last_edited = CURRENT_TIMESTAMP WHERE id = ?',
            (new_content, row_id)
        )
        db.commit()
        flash('Comment updated.', 'success')
        return redirect(request.referrer or '/')

    # -- Render edit form --
    return render_template('edit_comment.html', comment=comment)

# DELETE COMMENT
@app.route('/delete_comment/<comment_id>', methods=['POST'])
def delete_comment(comment_id):
    db = get_db()
    try:
        real_id = decode_prefixed_id(comment_id)
    except:
        flash("Invalid comment ID format.", "error")
        return redirect('/feed')

    comment = db.execute('SELECT * FROM comments WHERE id = ?', (real_id,)).fetchone()
    if not comment or comment['user_id'] != session.get('user_id'):
        flash("Unauthorized or comment not found.", "error")
        return redirect('/feed')

    db.execute('DELETE FROM comments WHERE id = ?', (real_id,))
    db.commit()
    flash("Comment deleted.", "success")
    return redirect(request.referrer or '/feed')

@app.route('/markdown-guide')
def markdown_guide():
    return render_template('markdown-guide.html')

@app.route('/posts/<string:post_id>/history')
def post_edit_history(post_id):
    db = get_db()
    if not db.execute('SELECT 1 FROM posts WHERE id=? AND community_post_visible(id)=1', (post_id,)).fetchone():
        abort(404)
    post = db.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
    versions = db.execute('SELECT * FROM post_edit_history WHERE post_id=? ORDER BY id DESC', (post_id,)).fetchall()
    return render_template('post_edit_history.html', post=post, versions=versions)

@app.route('/feed')
@app.route('/posts/<string:post_id>', endpoint='post_detail')
def feed(post_id=None):
    if post_id is None and 'user_id' not in session:
        flash("Please log in to view your feed.", "error")
        return redirect('/login')

    db = get_db()
    page = 1 if post_id is not None else post_page()
    total_posts = db.execute('SELECT COUNT(*) FROM posts p WHERE NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id) AND community_post_visible(p.id)=1').fetchone()[0]
    total_pages = 1 if post_id is not None else max(1,(total_posts+19)//20)
    if page > total_pages:
        abort(404)
    # --- Fetch posts ---
    rows = db.execute(''' 
        SELECT posts.id, posts.user_id, posts.content, posts.circle,
               posts.created_at, posts.last_edited,
               users.handle      AS author_handle,
               users.codename    AS author_codename,
               users.avatar_path,
               GROUP_CONCAT(vibes.name, ', ') AS vibes
        FROM posts
        JOIN users ON users.id = posts.user_id
        LEFT JOIN post_vibes ON posts.id = post_vibes.post_id
        LEFT JOIN vibes      ON post_vibes.vibe_id = vibes.id
        WHERE NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id = posts.id) AND community_post_visible(posts.id)=1 AND (? IS NULL OR posts.id=?)
        GROUP BY posts.id
        ORDER BY posts.created_at DESC, posts.id DESC LIMIT 20 OFFSET ?
    ''', (post_id,post_id,(page-1)*20)).fetchall()
    if post_id is not None and not rows:
        abort(404)

    # --- Build HTML & Base62 map ---
    posts_with_html = []
    post_ids, base62_map = [], {}
    for row in rows:
        raw_id = row['id']
        b62    = identifiers.public(db,'post',raw_id)
        post   = dict(row)
        post.update({
            'base62_id':            b62,
            'html_content':         markdown2.markdown(row['content'], safe_mode='escape'),
            'author_handle':        row['author_handle'].lstrip('@') if row['author_handle'] else None,
            'author_avatar':        row['avatar_path'] or '/static/default-avatar.png',
            'is_guestbook_outbound': False
        })
        posts_with_html.append(post)
        post_ids.append(raw_id)
        base62_map[raw_id] = b62

    # --- Reaction counts ---
    reaction_map = {}
    if post_ids:
        ph = ','.join('?'*len(post_ids))
        for r in db.execute(f'''
            SELECT post_id, emoji, COUNT(*) AS count
            FROM post_reactions
            WHERE post_id IN ({ph})
            GROUP BY post_id, emoji
        ''', post_ids):
            reaction_map.setdefault(r['post_id'], {})[r['emoji']] = r['count']
    for post in posts_with_html:
        post['reaction_counts'] = reaction_map.get(post['id'], {})

    # --- Reactors (who reacted) ---
    post_reactors = {}
    if post_ids:
        ph = ','.join('?'*len(post_ids))
        for r in db.execute(f'''
            SELECT pr.post_id, pr.emoji, u.handle
            FROM post_reactions pr
            JOIN users u ON u.id = pr.user_id
            WHERE pr.post_id IN ({ph})
        ''', post_ids):
            b62 = base62_map[r['post_id']]
            post_reactors.setdefault(b62, {})\
                         .setdefault(r['emoji'], [])\
                         .append(r['handle'])

    # -- Comments threaded --
    comments_raw = []
    if post_ids:
        placeholders = ','.join(['?'] * len(post_ids))
        comments_raw = db.execute(f'''
            SELECT c.id, c.post_id, c.user_id, c.content, c.parent_comment_id,
                   c.last_edited, u.handle, u.avatar_path
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.post_id IN ({placeholders})
              AND NOT EXISTS (SELECT 1 FROM moderated_comments mc WHERE mc.comment_id=c.id) AND community_member_visible(c.user_id)=1 AND age_comment_visible(c.id)=1
            ORDER BY c.created_at ASC
        ''', post_ids).fetchall()
    post_comments = {}
    for c in comments_raw:
        pid, par = c['post_id'], c['parent_comment_id']
        cid = identifiers.public(db,'comment',c['id'])
        comment = {
            'id': cid,
            'raw_id': c['id'],
            'post_id': identifiers.public(db,'post',pid),
            'parent_comment_id': identifiers.optional(db,'comment',par) if par else None,
            'user_id': c['user_id'],
            'author_handle': c['handle'].lstrip('@'),
            'avatar': c['avatar_path'] or '/static/default-avatar.png',
            'content': c['content'],
            'last_edited': c['last_edited'],
            'replies': []
        }
        post_comments.setdefault(comment['post_id'], []).append(comment)
    for post in posts_with_html:
        post['comments'] = build_comment_tree(post_comments.get(post['base62_id'], []))


    # --- Load vibe theme metadata ---
    vibe_rows = db.execute('''
        SELECT v.name      AS vibe,
               t.bg_color   AS bg,
               t.text_color AS text,
               t.glow_color AS glow,
               t.css_class  AS css_class
        FROM vibes v
        JOIN themes t ON v.theme_id = t.id
    ''').fetchall()
    vibe_metadata = {
        row['vibe']: {
            'bg':        row['bg'],
            'text':      row['text'],
            'glow':      row['glow'],
            'css_class': row['css_class']
        }
        for row in vibe_rows
    }

    rail_ads,banner_ad = ad_selection(db)
    return render_template(
        'feed.html', single_post=post_id is not None, page=page, total_pages=total_pages, rail_ads=rail_ads, banner_ad=banner_ad,
        posts=posts_with_html,
        post_reactors=post_reactors,
        VALID_REACTS=VALID_REACTS,
        vibe_slug='mixed',             # for theming
        vibe_metadata=vibe_metadata    # ← make this available in your partial
    )


@app.route('/edit_post/<string:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    if 'user_id' not in session:
        flash("Please log in to edit posts.", 'error')
        return redirect('/login')

    db = get_db()
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()

    if not post or post['user_id'] != session['user_id']:
        flash("You don't have permission to edit this post.", 'error')
        return redirect('/feed')

    if request.method == 'POST':
        from neonrest import welcome
        welcome.validate_flag(db,session['user_id'])
        new_content = request.form['content'].strip()
        media = prepare_post_media()
        init_media_tables(db)
        existing_media = db.execute('SELECT 1 FROM post_media WHERE post_id=?', (post_id,)).fetchone()
        new_vibe = request.form['vibes'].strip()
        new_circle = request.form['circle'].strip()

        if not new_content and not media and not existing_media:
            flash("Add text or an attachment to post.", 'error')
        else:
            if (new_content, new_vibe, new_circle) != (post['content'], post['vibe'] or '', post['circle'] or ''):
                db.execute('INSERT INTO post_edit_history(post_id,content,vibe,circle,version_at) VALUES (?,?,?,?,?)', (post_id, post['content'], post['vibe'], post['circle'], post['last_edited'] or post['created_at']))
            db.execute('''
                UPDATE posts
                SET content = ?,
                    vibe = ?,
                    circle = ?,
                    last_edited = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_content, new_vibe, new_circle, post_id))
            if request.form.get('audience'):
                db.execute('INSERT INTO post_privacy VALUES (?,?) ON CONFLICT(post_id) DO UPDATE SET audience=excluded.audience', (post_id, request.form['audience']))
            db.execute('DELETE FROM post_vibes WHERE post_id = ?', (post_id,))
            add_post_vibes(db, post_id, new_vibe.split(','))
            welcome.save_flag(db,post_id,session['user_id'])
            attach_post_media(db, post_id, media)
            update_post_media_labels(db, post_id, request.form)
            selected_filter = request.form.get('image_filter')
            if selected_filter in MEDIA_FILTERS:
                db.execute("UPDATE post_media SET filter_name=? WHERE post_id=? AND kind IN ('image','gif')", (selected_filter, post_id))
            db.commit()
            flash("Post updated successfully!", 'success')
            return redirect('/feed')

    linked_vibes = db.execute('''
        SELECT vibes.name FROM post_vibes
        JOIN vibes ON vibes.id = post_vibes.vibe_id
        WHERE post_vibes.post_id = ?
        ORDER BY post_vibes.rowid
    ''', (post_id,)).fetchall()
    vibes_value = ', '.join(item['name'] for item in linked_vibes) if linked_vibes else (post['vibe'] or '')
    return render_template('edit_post.html', post=post, vibes_value=vibes_value)

@app.route('/delete_post/<string:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        flash("Please log in to delete posts.", "error")
        return redirect('/login')

    db = get_db()
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()

    if not post or post['user_id'] != session['user_id']:
        flash("You do not have permission to delete this post.", "error")
        return redirect('/feed')

    db.execute('DELETE FROM post_vibes WHERE post_id = ?', (post_id,))
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()
    flash("Post deleted successfully.", "success")
    return redirect('/feed')

@app.route('/vibe/<vibe_name>')
def vibe_page(vibe_name):
    db = get_db()
    vibe = db.execute('SELECT * FROM vibes WHERE name = ? COLLATE NOCASE', (vibe_name,)).fetchone()
    if not vibe:
        flash("That vibe doesn't exist yet.", "error")
        return redirect('/feed')

    # Use one slug for the body class, stylesheet, and theme lookup.
    if is_pending(db, vibe['id']):
        return render_template(
            'vibe_pending.html', vibe=vibe,
            supporters=supporter_count(db, vibe['id']), threshold=minimum_users(),
            can_approve=can_approve_vibes(db, session.get('user_id')),
            approval_token=get_vibe_approval_token()
        )

    slug = vibe_slug(vibe['name'])
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    user = get_logged_in_user()
    timezone = user['timezone'] if user and user['timezone'] else 'UTC'
    try:
        local_now = datetime.now(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        local_now = datetime.now(ZoneInfo('UTC'))
    automatic_mode = 'day' if 6 <= local_now.hour < 18 else 'night'
    requested_mode = request.args.get('mode')
    theme_mode = requested_mode if requested_mode in ('day', 'night') else automatic_mode

    theme = db.execute(
        'SELECT * FROM themes WHERE slug = ? AND mode = ?',
        (slug, theme_mode)
    ).fetchone()
    vibe_css = f'vibes/vibe_{slug}.css'
    if not os.path.isfile(os.path.join(app.static_folder, vibe_css)):
        vibe_css = None

    page = post_page()
    total_posts = db.execute('''SELECT COUNT(*) FROM post_vibes pv JOIN posts p ON p.id=pv.post_id
        WHERE pv.vibe_id=? AND NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id) AND community_post_visible(p.id)=1''', (vibe['id'],)).fetchone()[0]
    total_pages = max(1,(total_posts+19)//20)
    if page > total_pages:
        abort(404)
    posts = db.execute('''
        SELECT posts.id, posts.user_id, posts.content, posts.circle, posts.created_at,
               posts.last_edited, users.handle, users.avatar_path,
               GROUP_CONCAT(vibes.name, ', ') AS vibes
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN post_vibes ON posts.id = post_vibes.post_id
        LEFT JOIN vibes ON post_vibes.vibe_id = vibes.id
        WHERE posts.id IN (
            SELECT post_id FROM post_vibes WHERE vibe_id = ?
        ) AND NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id = posts.id) AND community_post_visible(posts.id)=1
        GROUP BY posts.id
        ORDER BY posts.created_at DESC, posts.id DESC LIMIT 20 OFFSET ?
    ''', (vibe['id'],(page-1)*20)).fetchall()

    # Images are currently linked in post text; there is no attachment column yet.
    import re
    gallery_items = []
    contributors = []
    for post in posts:
        if post['handle'] not in contributors and len(contributors) < 6:
            contributors.append(post['handle'])
        for alt, image_url in re.findall(r'!\[([^\]]*)\]\((https?://[^\s)]+|/(?:sandbox/)?static/[^\s)]+)\)', post['content'] or ''):
            if len(gallery_items) >= 8:
                break
            if image_url.startswith('/static/'):
                image_url = url_for('static', filename=image_url[len('/static/'):])
            gallery_items.append({'id': post['id'], 'handle': post['handle'], 'alt': alt, 'url': image_url})
    viewer_posts = db.execute('''SELECT COUNT(*) FROM posts p JOIN post_vibes pv ON pv.post_id=p.id
        WHERE pv.vibe_id=? AND p.user_id=? AND NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id) AND community_post_visible(p.id)=1''',
        (vibe['id'], user['id'])).fetchone()[0] if user else 0
    rail_ads,banner_ad=ad_selection(db,vibe['id'])
    viewer_avatar = (user['avatar_path'] if user and user['avatar_path'] else url_for('static', filename='default-avatar.png'))
    if viewer_avatar.startswith('/static/'):
        viewer_avatar = url_for('static', filename=viewer_avatar[len('/static/'):])
    return render_template(
        'vibe_page.html',
        vibe_name=vibe['name'],
        vibe_slug=slug,
        theme_slug=slug,
        theme_mode=theme_mode,
        vibe_css=vibe_css,
        bg_color=theme['bg_color'] if theme else None,
        text_color=theme['text_color'] if theme else None,
        glow_color=theme['glow_color'] if theme else None,
        background_layers=theme['background_layers'] if theme else None,
        blend_mode=theme['blend_mode'] if theme else None,
        font_stack=theme['font_stack'] if theme else None,
        custom_css=theme['custom_css'] if theme else None,
        extra_css=theme['extra_css'] if theme else None,
        posts=posts, page=page, total_pages=total_pages, rail_ads=rail_ads, banner_ad=banner_ad,
        viewer=user, viewer_avatar=viewer_avatar, viewer_posts=viewer_posts,
        gallery_items=gallery_items, contributors=contributors,
        vibe=vibe, can_manage_vibe=bool(management_scope() and can_edit_vibe_settings(session.get('user_id'), vibe)),
        skip_static_css=(slug == 'fresh-starts')
    )



@app.route("/update_mood", methods=["POST"])
def update_mood():
    if "user_id" not in session:
        flash("Please log in.", "error")
        return redirect("/login")

    new_mood = request.form.get("mood", "").strip()
    db = get_db()
    db.execute("UPDATE users SET mood = ? WHERE id = ?", (new_mood, session["user_id"]))
    db.commit()
    flash("Mood updated!", "success")
    return redirect(f"/@{session['user_handle'].lstrip('@')}")

@app.route("/update_haunts", methods=["POST"])
def update_haunts():
    if "user_id" not in session:
        flash("Please log in.", "error")
        return redirect("/login")

    new_haunts = request.form.get("haunts", "").strip()
    db = get_db()
    db.execute("UPDATE users SET frequent_haunts = ? WHERE id = ?", (new_haunts, session["user_id"]))
    db.commit()
    flash("Haunts updated!", "success")
    return redirect(f"/@{session['user_handle'].lstrip('@')}")

@app.template_filter('datetimeformat')
def datetimeformat(value, format='medium'):
    if not value:
        return ''
    from datetime import datetime
    date = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    if format == 'long':
        return date.strftime('%B %Y')
    return date.strftime('%Y-%m-%d')

@app.route('/themes/preview/<slug>/<mode>')
def theme_preview(slug, mode):
    db = get_db()
    theme = db.execute('''
        SELECT * FROM themes
        WHERE slug = ? AND mode = ?
    ''', (slug, mode)).fetchone()

    if not theme:
        abort(404)

    return render_template('theme-preview.html', theme=theme)

def get_vibe_approval_token():
    if 'vibe_approval_token' not in session:
        session['vibe_approval_token'] = secrets.token_urlsafe(32)
    return session['vibe_approval_token']


@app.route('/staff/vibes/pending')
def pending_vibes():
    db = get_db()
    if not can_approve_vibes(db, session.get('user_id')):
        abort(403)
    candidates = db.execute('''
        SELECT vibes.id, vibes.name, COUNT(DISTINCT posts.user_id) AS supporters
        FROM pending_vibes
        JOIN vibes ON vibes.id = pending_vibes.vibe_id
        LEFT JOIN post_vibes ON post_vibes.vibe_id = vibes.id
        LEFT JOIN posts ON posts.id = post_vibes.post_id
        GROUP BY vibes.id ORDER BY supporters DESC, vibes.name
    ''').fetchall()
    return render_template('pending_vibes.html', candidates=candidates,
                           threshold=minimum_users(), approval_token=get_vibe_approval_token())


@app.route('/staff/vibes/<int:vibe_id>/approve', methods=['POST'])
def staff_approve_vibe(vibe_id):
    db = get_db()
    if not can_approve_vibes(db, session.get('user_id')):
        abort(403)
    token = session.get('vibe_approval_token')
    if not token or not hmac.compare_digest(request.form.get('approval_token', ''), token):
        abort(400)
    if not approve_vibe(db, vibe_id):
        abort(404)
    db.commit()
    flash('Vibe approved.', 'success')
    return redirect(url_for('pending_vibes'))



def can_moderate(db, user_id):
    return has_staff_permission(db, user_id, 'moderate_posts')


# Roles are additive. Vibe editor assignments remain scoped to individual Vibes.
# Keeping this map in one place makes every staff route enforce the same policy.
STAFF_PERMISSIONS = {
    'admin': frozenset(('view_staff', 'moderate_posts', 'restrict_users',
                        'ban_users', 'review_history', 'approve_vibes', 'manage_roles',
                        'moderate_comments', 'review_reports', 'review_appeals', 'manage_ads')),
    'manager': frozenset(('view_staff', 'moderate_posts', 'restrict_users',
                          'ban_users', 'review_history', 'approve_vibes',
                          'moderate_comments', 'review_reports', 'review_appeals')),
    'moderator': frozenset(('view_staff', 'moderate_posts', 'restrict_users',
                            'ban_users', 'review_history', 'moderate_comments',
                            'review_reports', 'review_appeals')),
}


def staff_permissions(db, user_id):
    if not isinstance(user_id, int):
        return frozenset()
    user = db.execute('SELECT verified FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['verified']:
        return frozenset()
    if user_id == 1:
        return STAFF_PERMISSIONS['admin']
    roles = db.execute('SELECT role FROM staff_roles WHERE user_id = ?', (user_id,)).fetchall()
    return frozenset().union(*(STAFF_PERMISSIONS.get(row['role'], ()) for row in roles))


def has_staff_permission(db, user_id, permission):
    return permission in staff_permissions(db, user_id)


def require_staff_permission(permission):
    user_id = session.get('user_id')
    if not has_staff_permission(get_db(), user_id, permission):
        abort(403)
    return user_id

def require_moderator():
    return require_staff_permission('moderate_posts')

def valid_management_token():
    expected = session.get('theme_csrf_token', '')
    submitted = request.form.get('theme_csrf_token', '')
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))

@app.before_request
def enforce_moderation_status():
    user_id = session.get('user_id')
    if isinstance(user_id, int):
        row = get_db().execute('SELECT banned, posting_restricted, interaction_restricted FROM user_moderation WHERE user_id = ?', (user_id,)).fetchone()
        if row:
            if row['banned']:
                if request.endpoint not in ('my_appeals', 'appeal_form', 'logout', 'static', 'community_security', 'account_email', 'account_email_confirm', 'community_reauth', 'community_notifications', 'community_data', 'community_export', 'community_privacy', 'community_relationship'):
                    abort(403)
            if request.method == 'POST':
                if row['posting_restricted'] and request.endpoint in ('create_post', 'create_comment', 'edit_post', 'edit_comment', 'post.create_post'):
                    abort(403)
                if row['interaction_restricted'] and request.endpoint in (
                    'react_to_post', 'friends.follow', 'friends.unfollow',
                    'friends.send_request', 'friends.accept_friend',
                    'friends.decline_friend', 'friends.remove_friend',
                    'friends.update_top9'):
                    abort(403)
    post_id = None
    if request.endpoint in ('edit_post', 'delete_post', 'react_to_post'):
        post_id = (request.view_args or {}).get('post_id')
    elif request.endpoint == 'create_comment':
        try:
            post_id = int(request.form.get('post_id', ''))
        except ValueError:
            pass
    if post_id is not None and get_db().execute('SELECT 1 FROM moderated_posts WHERE post_id = ?', (post_id,)).fetchone():
        abort(404)

def management_scope():
    """Return permissions from the database, never from submitted page data."""
    user_id = session.get('user_id')
    if not isinstance(user_id, int):
        return None
    db = get_db()
    user = db.execute('SELECT id, handle, verified FROM users WHERE id = ?',
                      (user_id,)).fetchone()
    if not user or not user['verified']:
        return None
    approved = db.execute("""
        SELECT * FROM vibes
        WHERE id NOT IN (SELECT vibe_id FROM pending_vibes)
        ORDER BY name
    """).fetchall()
    editable = [
        {'id': vibe['id'], 'name': vibe['name'], 'slug': vibe_slug(vibe['name'])}
        for vibe in approved if can_edit_vibe_settings(user_id, vibe)
    ]
    approvals = can_approve_vibes(db, user_id)
    moderation = can_moderate(db, user_id)
    return {'user': user, 'editable': editable, 'approvals': approvals,
            'moderation': moderation} if editable or approvals or moderation else None


@app.context_processor
def management_navigation():
    # Used only by profile templates; the management routes check again.
    return {'can_access_manage': lambda: management_scope() is not None}


def theme_csrf_token():
    if 'theme_csrf_token' not in session:
        session['theme_csrf_token'] = secrets.token_urlsafe(32)
    return session['theme_csrf_token']


@app.after_request
def protect_management_responses(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    if request.path.startswith(('/manage', '/themes/edit')):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/manage')
def manage_home():
    scope = management_scope()
    if scope is None:
        abort(403)
    if scope['moderation']:
        db = get_db()
        scope['permissions'] = staff_permissions(db, session.get('user_id'))
        scope['user_count'] = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        scope['post_count'] = db.execute('SELECT COUNT(*) FROM posts WHERE id NOT IN (SELECT post_id FROM moderated_posts)').fetchone()[0]
        scope['ad_count'] = db.execute('SELECT COUNT(*) FROM ad_campaigns').fetchone()[0]
        scope['open_reports'] = db.execute("SELECT COUNT(*) FROM content_reports WHERE status='open'").fetchone()[0]
        scope['open_appeals'] = db.execute("SELECT COUNT(*) FROM moderation_appeals WHERE status='open'").fetchone()[0]
        filters, params, selected_action, query, who = moderation_history_filters(db)
        scope['moderation_actions'] = db.execute('SELECT DISTINCT action FROM moderation_events ORDER BY action').fetchall()
        scope['selected_action'] = selected_action
        scope['moderation_query'] = query
        scope['moderation_who'] = who
        scope['recent_events'] = db.execute('''SELECT e.action, e.reason, e.created_at, actor.handle AS actor_handle,
            target.handle AS target_handle, e.post_id, e.actor_id, e.target_user_id FROM moderation_events e
            LEFT JOIN users actor ON actor.id=e.actor_id LEFT JOIN users target ON target.id=e.target_user_id
            WHERE ''' + filters + ' ORDER BY e.id DESC LIMIT 10', params).fetchall()
    return render_template('manage_home.html', **scope)


@app.route('/manage/vibes/<slug>')
def manage_vibe(slug):
    scope = management_scope()
    if scope is None:
        abort(403)
    vibe = next((v for v in scope['editable'] if v['slug'] == slug), None)
    if vibe is None:
        abort(404)
    return render_template('manage_vibe.html', vibe=vibe)


@app.route('/manage/users')
def manage_users():
    require_staff_permission('restrict_users')
    db = get_db()
    from neonrest.management_audit import identity_query, literal_pattern
    query, identifier = identity_query(request.args.get('q', ''))
    condition = '1=1' if not query else 'CAST(u.id AS TEXT)=?' if identifier is not None else "u.handle LIKE ? ESCAPE '\\'"
    params = () if not query else (identifier,) if identifier is not None else (literal_pattern(query),)
    users = db.execute('''SELECT u.id, u.handle, u.verified,
        COALESCE(m.banned, 0) AS banned, COALESCE(m.posting_restricted, 0) AS posting_restricted,
        COALESCE(m.interaction_restricted, 0) AS interaction_restricted,
        EXISTS(SELECT 1 FROM staff_roles sr WHERE sr.user_id=u.id) AS is_staff
        FROM users u LEFT JOIN user_moderation m ON m.user_id=u.id
        WHERE ''' + condition + ' ORDER BY u.id DESC LIMIT 50', params).fetchall()
    return render_template('manage_users.html', users=users, query=query,
                           management_token=theme_csrf_token())


@app.route('/manage/users/<int:target_id>')
def manage_user_detail(target_id):
    require_staff_permission('restrict_users')
    db = get_db()
    account = db.execute('''SELECT u.id, u.handle, u.verified, u.created_at,
        COALESCE(m.banned, 0) AS banned,
        COALESCE(m.posting_restricted, 0) AS posting_restricted,
        COALESCE(m.interaction_restricted, 0) AS interaction_restricted,
        m.reason, m.updated_at, updater.handle AS updated_by,
        EXISTS(SELECT 1 FROM staff_roles WHERE user_id=u.id) AS is_staff
        FROM users u LEFT JOIN user_moderation m ON m.user_id=u.id
        LEFT JOIN users updater ON updater.id=m.updated_by WHERE u.id=?''', (target_id,)).fetchone()
    if account is None:
        abort(404)
    roles = db.execute('SELECT role FROM staff_roles WHERE user_id=? ORDER BY role', (target_id,)).fetchall()
    events = db.execute('''SELECT e.action, e.reason, e.created_at, e.post_id, e.actor_id,
        actor.handle AS actor_handle FROM moderation_events e
        LEFT JOIN users actor ON actor.id=e.actor_id
        WHERE e.target_user_id=? ORDER BY e.id DESC LIMIT 50''', (target_id,)).fetchall()
    posts = db.execute('''SELECT p.id, p.content, p.created_at,
        mp.post_id IS NOT NULL AS hidden FROM posts p
        LEFT JOIN moderated_posts mp ON mp.post_id=p.id
        WHERE p.user_id=? ORDER BY p.id DESC LIMIT 10''', (target_id,)).fetchall()
    return render_template('manage_user_detail.html', account=account, roles=roles,
                           events=events, posts=posts, disable_state=db.execute('SELECT * FROM account_disables WHERE user_id=?',(target_id,)).fetchone(), management_token=theme_csrf_token())


def moderation_history_filters(db):
    from neonrest.management_audit import history_filters
    return history_filters(db)


@app.route('/manage/history')
def manage_history():
    require_staff_permission('review_history')
    db = get_db()
    try:
        page = int(request.args.get('page', '1'))
    except ValueError:
        abort(400)
    if page < 1 or page > 10000:
        abort(400)
    filters, params, selected_action, query, who = moderation_history_filters(db)
    events = db.execute('''SELECT e.id, e.action, e.reason, e.created_at,
        e.post_id, e.comment_id, e.report_id, e.appeal_id,
        actor.handle AS actor_handle, target.handle AS target_handle,
        e.actor_id, e.target_user_id FROM moderation_events e
        LEFT JOIN users actor ON actor.id=e.actor_id
        LEFT JOIN users target ON target.id=e.target_user_id
        WHERE ''' + filters + ' ORDER BY e.id DESC LIMIT 51 OFFSET ?', (*params, (page-1)*50)).fetchall()
    return render_template('manage_history.html', events=events[:50],
                           has_next=len(events)>50, page=page, selected_action=selected_action,
                           moderation_query=query, moderation_who=who,
                           moderation_actions=db.execute('SELECT DISTINCT action FROM moderation_events ORDER BY action').fetchall())


@app.route('/manage/roles')
def manage_roles():
    require_staff_permission('view_staff')
    db = get_db()
    assignments = db.execute('''SELECT u.id, u.handle, sr.role FROM staff_roles sr
        JOIN users u ON u.id=sr.user_id ORDER BY u.handle COLLATE NOCASE, sr.role''').fetchall()
    return render_template('manage_roles.html', assignments=assignments,
                           permissions=STAFF_PERMISSIONS,
                           may_assign=has_staff_permission(db, session.get('user_id'), 'manage_roles'),
                           is_owner=session.get('user_id') == 1,
                           management_token=theme_csrf_token())


@app.route('/manage/roles/<int:target_id>', methods=['POST'])
def assign_staff_role(target_id):
    actor_id = require_staff_permission('manage_roles')
    if not valid_management_token():
        abort(400)
    role = request.form.get('role', '')
    action = request.form.get('action', '')
    reason = request.form.get('reason', '').strip()
    if role not in STAFF_PERMISSIONS or action not in ('add', 'remove') or not reason or len(reason) > 500:
        abort(400)
    # Admins can appoint moderators; the founder alone can grant higher roles.
    if actor_id != 1 and role != 'moderator':
        abort(403)
    if target_id in (actor_id, 1):
        abort(403)
    db = get_db()
    target = db.execute('SELECT id, verified FROM users WHERE id=?', (target_id,)).fetchone()
    if not target:
        abort(404)
    if not target['verified'] or db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1', (target_id,)).fetchone():
        abort(403)
    existing = db.execute('SELECT 1 FROM staff_roles WHERE user_id=? AND role=?', (target_id, role)).fetchone()
    if bool(existing) == (action == 'add'):
        flash('No role change was needed.', 'info')
        return redirect(url_for('manage_roles'))
    if action == 'add':
        db.execute('INSERT INTO staff_roles (user_id,role) VALUES (?,?)', (target_id, role))
    else:
        db.execute('DELETE FROM staff_roles WHERE user_id=? AND role=?', (target_id, role))
    event = db.execute('INSERT INTO moderation_events (actor_id,target_user_id,action,reason) VALUES (?,?,?,?)',
               (actor_id, target_id, f'role:{action}:{role}', reason))
    attach_event(db, event.lastrowid)
    db.commit()
    flash('Staff role updated.', 'success')
    return redirect(url_for('manage_roles'))


@app.route('/manage/comments')
def manage_comments():
    require_staff_permission('moderate_comments')
    query = request.args.get('q', '').strip()[:80]
    if identifiers.TOKEN.fullmatch(query):
        try:query=str(identifiers.resolve(get_db(),'comment',query))
        except ValueError:pass
    comments = get_db().execute('''SELECT c.id, c.post_id, c.user_id, c.content, c.created_at,
        u.handle, mc.comment_id IS NOT NULL AS hidden, mc.reason,
        EXISTS(SELECT 1 FROM staff_roles WHERE user_id=c.user_id) AS author_staff
        FROM comments c JOIN users u ON u.id=c.user_id
        LEFT JOIN moderated_comments mc ON mc.comment_id=c.id
        WHERE (?='' OR CAST(c.id AS TEXT)=? OR CAST(c.post_id AS TEXT)=?
               OR c.content LIKE ? OR u.handle LIKE ?)
        ORDER BY c.id DESC LIMIT 50''',
        (query, query, query, '%'+query+'%', '%'+query+'%')).fetchall()
    return render_template('manage_comments.html', comments=comments, query=query,
                           management_token=theme_csrf_token())


@app.route('/manage/comments/<int:comment_id>/moderate', methods=['POST'])
def moderate_comment(comment_id):
    actor_id = require_staff_permission('moderate_comments')
    if not valid_management_token():
        abort(400)
    action = request.form.get('action', '')
    reason = request.form.get('reason', '').strip()
    if action not in ('hide', 'restore') or not reason or len(reason) > 500:
        abort(400)
    db = get_db()
    comment = db.execute('SELECT user_id,post_id FROM comments WHERE id=?', (comment_id,)).fetchone()
    if not comment:
        abort(404)
    if comment['user_id'] in (1, actor_id) or db.execute('SELECT 1 FROM staff_roles WHERE user_id=?', (comment['user_id'],)).fetchone():
        abort(403)
    hidden = db.execute('SELECT 1 FROM moderated_comments WHERE comment_id=?', (comment_id,)).fetchone()
    if bool(hidden) == (action == 'hide'):
        flash('No visibility change was needed.', 'info')
        return redirect(url_for('manage_comments', q=str(comment_id)))
    if action == 'hide':
        db.execute('INSERT INTO moderated_comments (comment_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',
                   (comment_id, comment['user_id'], actor_id, reason))
    else:
        db.execute('DELETE FROM moderated_comments WHERE comment_id=?', (comment_id,))
    db.execute('''INSERT INTO moderation_events (actor_id,target_user_id,post_id,comment_id,action,reason)
        VALUES (?,?,?,?,?,?)''', (actor_id, comment['user_id'], comment['post_id'], comment_id,
                               'comment:'+action, reason))
    attach_event(db, db.execute('SELECT last_insert_rowid()').fetchone()[0])
    db.commit()
    flash('Comment visibility updated.', 'success')
    return redirect(url_for('manage_comments', q=str(comment_id)))

@app.route('/manage/users/<int:target_id>/moderate', methods=['POST'])
def moderate_user(target_id):
    action = request.form.get('action', '')
    actor_id = require_staff_permission('ban_users' if action == 'ban' else 'restrict_users')
    if not valid_management_token():
        abort(400)
    db = get_db()
    target = db.execute('SELECT id FROM users WHERE id = ?', (target_id,)).fetchone()
    if not target:
        abort(404)
    if target_id in (actor_id, 1) or db.execute('SELECT 1 FROM staff_roles WHERE user_id = ?', (target_id,)).fetchone():
        abort(403)
    column = {'ban': 'banned', 'posting': 'posting_restricted', 'interaction': 'interaction_restricted'}.get(action)
    state = request.form.get('state')
    reason = request.form.get('reason', '').strip()
    if not column or state not in ('0', '1') or not reason or len(reason) > 500:
        abort(400)
    old = db.execute(f'SELECT {column} FROM user_moderation WHERE user_id = ?', (target_id,)).fetchone()
    if int(state) == (old[column] if old else 0):
        flash('No status change was needed.', 'info')
        return redirect(url_for('manage_user_detail', target_id=target_id))
    db.execute('INSERT OR IGNORE INTO user_moderation (user_id) VALUES (?)', (target_id,))
    db.execute(f'UPDATE user_moderation SET {column} = ?, reason = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
               (int(state), reason, actor_id, target_id))
    db.execute('INSERT INTO moderation_events (actor_id, target_user_id, action, reason) VALUES (?, ?, ?, ?)',
               (actor_id, target_id, action + ':' + state, reason))
    attach_event(db, db.execute('SELECT last_insert_rowid()').fetchone()[0])
    db.commit()
    flash('User moderation updated.', 'success')
    return redirect(url_for('manage_user_detail', target_id=target_id))

@app.route('/manage/posts')
def manage_posts():
    require_staff_permission('moderate_posts')
    query = request.args.get('q', '').strip()[:80]
    if identifiers.TOKEN.fullmatch(query):
        try:query=str(identifiers.resolve(get_db(),'post',query))
        except ValueError:pass
    posts = get_db().execute('''SELECT p.id, p.content, p.created_at, u.handle, p.user_id,
        mp.post_id IS NOT NULL AS hidden, mp.reason,
        EXISTS(SELECT 1 FROM staff_roles sr WHERE sr.user_id=p.user_id) AS author_staff
        FROM posts p JOIN users u ON u.id=p.user_id
        LEFT JOIN moderated_posts mp ON mp.post_id=p.id
        WHERE (? = '' OR CAST(p.id AS TEXT) = ? OR p.content LIKE ? OR u.handle LIKE ?)
        ORDER BY p.id DESC LIMIT 50''',
        (query, query, '%' + query + '%', '%' + query + '%')).fetchall()
    return render_template('manage_posts.html', posts=posts, query=query,
                           management_token=theme_csrf_token())

@app.route('/manage/posts/<string:post_id>/moderate', methods=['POST'])
def moderate_post(post_id):
    actor_id = require_staff_permission('moderate_posts')
    if not valid_management_token():
        abort(400)
    db = get_db()
    post = db.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        abort(404)
    if post['user_id'] == 1 or db.execute('SELECT 1 FROM staff_roles WHERE user_id = ?', (post['user_id'],)).fetchone():
        abort(403)
    action = request.form.get('action')
    reason = request.form.get('reason', '').strip()
    if action not in ('hide', 'restore') or not reason or len(reason) > 500:
        abort(400)
    hidden = db.execute('SELECT 1 FROM moderated_posts WHERE post_id = ?', (post_id,)).fetchone()
    if bool(hidden) == (action == 'hide'):
        flash('No visibility change was needed.', 'info')
        return redirect(url_for('manage_posts', q=str(post_id)))
    if action == 'hide':
        db.execute('INSERT OR IGNORE INTO moderated_posts (post_id, author_id, hidden_by, reason) VALUES (?, ?, ?, ?)',
                   (post_id, post['user_id'], actor_id, reason))
    else:
        db.execute('DELETE FROM moderated_posts WHERE post_id = ?', (post_id,))
    db.execute('INSERT INTO moderation_events (actor_id, target_user_id, post_id, action, reason) VALUES (?, ?, ?, ?, ?)',
               (actor_id, post['user_id'], post_id, action, reason))
    attach_event(db, db.execute('SELECT last_insert_rowid()').fetchone()[0])
    db.commit()
    flash('Post visibility updated.', 'success')
    return redirect(url_for('manage_posts', q=str(post_id)))

@app.route('/themes/edit')
def edit_theme_index():
    """Open the first Vibe whose theme settings this user can edit."""
    db = get_db()
    user_id = session.get('user_id')
    for vibe in db.execute('''
        SELECT * FROM vibes WHERE id NOT IN (SELECT vibe_id FROM pending_vibes)
        ORDER BY name
    ''').fetchall():
        if can_edit_vibe_settings(user_id, vibe):
            slug = vibe_slug(vibe['name'])
            return redirect(url_for('edit_theme', slug=slug, mode='day'))
    flash("You don’t have permission to edit Vibe settings.", "error")
    return redirect('/feed')


@app.route('/themes/edit/<slug>/<mode>', methods=['GET', 'POST'])
def edit_theme(slug, mode):
    db = get_db()
    if mode not in ('day', 'night'):
        abort(404)

    vibes = db.execute('''
        SELECT * FROM vibes WHERE id NOT IN (SELECT vibe_id FROM pending_vibes)
        ORDER BY name
    ''').fetchall()
    vibe_by_slug = {vibe_slug(item['name']): item for item in vibes}
    vibe = vibe_by_slug.get(slug)
    if not vibe:
        abort(404)

    user_id = session.get('user_id')
    if not can_edit_vibe_settings(user_id, vibe):
        abort(403)

    editable_vibes = [
        {'name': item['name'], 'slug': vibe_slug(item['name']), 'mode': mode}
        for item in vibes if can_edit_vibe_settings(user_id, item)
    ]
    editable_modes = ('day', 'night')
    theme_row = db.execute(
        'SELECT * FROM themes WHERE slug = ? AND mode = ?', (slug, mode)
    ).fetchone()
    theme = dict(theme_row) if theme_row else {
        'id': None, 'name': vibe['name'], 'slug': slug, 'mode': mode,
        'custom_css': default_vibe_css(slug, mode),
        'bg_color': None, 'text_color': None,
        'glow_color': None, 'background_layers': '', 'blend_mode': '',
        'font_stack': ''
    }

    def sanitize_color(value):
        return value if value and not value.isspace() else None

    if request.method == 'POST':
        expected = session.get('theme_csrf_token', '')
        submitted = request.form.get('theme_csrf_token', '')
        if not expected or not hmac.compare_digest(submitted, expected):
            abort(400)

    if request.method == 'POST' and request.form.get('action', '').startswith('restore:'):
        if not theme['id']:
            abort(404)
        try:
            version_id = int(request.form['action'].split(':', 1)[1])
        except ValueError:
            abort(400)
        version = db.execute('SELECT * FROM theme_versions WHERE id = ? AND theme_id = ?',
                             (version_id, theme['id'])).fetchone()
        if not version:
            abort(404)
        db.execute("""INSERT INTO theme_versions
            (theme_id, bg_color, text_color, glow_color, background_layers, blend_mode, font_stack, custom_css)
            SELECT id, bg_color, text_color, glow_color, background_layers, blend_mode, font_stack, custom_css
            FROM themes WHERE id = ?""", (theme['id'],))
        db.execute("""UPDATE themes SET bg_color = ?, text_color = ?, glow_color = ?,
            background_layers = ?, blend_mode = ?, font_stack = ?, custom_css = ? WHERE id = ?""",
            (version['bg_color'], version['text_color'], version['glow_color'],
             version['background_layers'], version['blend_mode'], version['font_stack'],
             version['custom_css'], theme['id']))
        db.commit()
        return redirect(url_for('edit_theme', slug=slug, mode=mode, restored=1))

    if request.method == 'POST':
        if theme['id']:
            db.execute("""INSERT INTO theme_versions
                (theme_id, bg_color, text_color, glow_color, background_layers, blend_mode, font_stack, custom_css)
                SELECT id, bg_color, text_color, glow_color, background_layers, blend_mode, font_stack, custom_css
                FROM themes WHERE id = ?""", (theme['id'],))
        new_css = request.form.get('custom_css', '').strip()

        # Handle nullable colors
        bg_color = None if request.form.get('null_bg_color') else sanitize_color(request.form.get('bg_color'))
        text_color = None if request.form.get('null_text_color') else sanitize_color(request.form.get('text_color'))
        glow_color = None if request.form.get('null_glow_color') else sanitize_color(request.form.get('glow_color'))

        bg_layers = request.form.get('background_layers', '').strip()
        blend_mode = request.form.get('blend_mode', '').strip()
        font_stack = request.form.get('font_stack', '').strip()

        values = (new_css, bg_color, text_color, glow_color,
                  bg_layers, blend_mode, font_stack)
        if theme['id'] is None:
            cursor = db.execute('''
                INSERT INTO themes
                    (slug, name, mode, custom_css, bg_color, text_color,
                     glow_color, background_layers, blend_mode, font_stack)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (slug, vibe['name'], mode, *values))
            db.execute('UPDATE vibes SET theme_id = COALESCE(theme_id, ?) WHERE id = ?',
                       (cursor.lastrowid, vibe['id']))
        else:
            db.execute('''
                UPDATE themes SET
                    custom_css = ?, bg_color = ?, text_color = ?, glow_color = ?,
                    background_layers = ?, blend_mode = ?, font_stack = ?
                WHERE id = ?
            ''', (*values, theme['id']))
        if vibe:
            def optional_logo_field(name):
                value = request.form.get(name, '').strip()
                return None if value.lower() in ('', 'none') else value
            logo_url = optional_logo_field('logo_url')
            logo_width = optional_logo_field('logo_width')
            logo_height = optional_logo_field('logo_height')
            logo_padding = optional_logo_field('logo_padding')
            logo_align = request.form.get('logo_align', '').strip() or 'center'
            welcome_message = request.form.get('welcome_message', vibe['welcome_message'] or '').strip()
            if len(welcome_message) > 1000:
                abort(400)
            db.execute('''
                UPDATE vibes
                SET logo_url = ?, logo_width = ?, logo_height = ?, logo_padding = ?, logo_align = ?, welcome_message = ?
                WHERE id = ?
            ''', (logo_url, logo_width, logo_height, logo_padding, logo_align, welcome_message, vibe['id']))

        # Save the resulting revision after the theme and shared identity are persisted.
        saved_theme = db.execute('SELECT id FROM themes WHERE slug = ? AND mode = ?',
                                 (slug, mode)).fetchone()
        if saved_theme:
            db.execute("""INSERT INTO theme_versions
                (theme_id, bg_color, text_color, glow_color, background_layers, blend_mode, font_stack, custom_css)
                SELECT id, bg_color, text_color, glow_color, background_layers, blend_mode, font_stack, custom_css
                FROM themes WHERE id = ?""", (saved_theme['id'],))
        db.commit()

        action = request.form.get('action')
        if action == 'save_and_preview':
            if vibe:
                return redirect(url_for('vibe_page', vibe_name=vibe['name'], mode=mode))
            return redirect(url_for('theme_preview', slug=slug, mode=mode))
        else:
            return redirect(url_for('edit_theme', slug=slug, mode=mode, saved=1))

    history = db.execute("""SELECT id, saved_at FROM theme_versions
        WHERE theme_id = ? ORDER BY id DESC LIMIT 12""", (theme['id'],)).fetchall() if theme['id'] else []
    return render_template(
        'edit_theme.html', history=history, theme=theme, editable_vibes=editable_vibes,
        editable_modes=editable_modes, vibe=vibe, theme_csrf_token=theme_csrf_token()
    )

@app.route("/react/<string:post_id>", methods=["POST"])
def react_to_post(post_id):
    if 'user_id' not in session:
        if request.is_json:
            return jsonify({ "status": "unauthorized" }), 401
        return redirect("/login")

    user_id = session['user_id']
    data = request.get_json(silent=True)
    emoji = data.get('emoji') if data else request.form.get('emoji')

    if emoji not in VALID_REACTS:
        return jsonify({ "status": "error", "message": "Invalid reaction" }), 400

    db = get_db()

    # Check if this reaction already exists
    existing = db.execute("""
        SELECT 1 FROM post_reactions WHERE post_id = ? AND user_id = ? AND emoji = ?
    """, (post_id, user_id, emoji)).fetchone()

    if existing:
        # Remove reaction
        db.execute("""
            DELETE FROM post_reactions WHERE post_id = ? AND user_id = ? AND emoji = ?
        """, (post_id, user_id, emoji))
        db.commit()
        action = "removed"
    else:
        # Add reaction
        db.execute("""
            INSERT INTO post_reactions (post_id, user_id, emoji)
            VALUES (?, ?, ?)
        """, (post_id, user_id, emoji))
        db.commit()
        action = "added"

    # Get the updated count
    count = db.execute("""
        SELECT COUNT(*) FROM post_reactions
        WHERE post_id = ? AND emoji = ?
    """, (post_id, emoji)).fetchone()[0]

    return jsonify({
        "status": "ok",
        "emoji": emoji,
        "count": count,
        "action": action
    })


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect('/')

@app.route("/dev")
def dev_summary():
    return render_template("dev_summary.html")

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route("/explore")
def explore():
    return render_template("explore.html")

@app.route("/about-mailersend")
def about_mailersend():
    return render_template("about-mailersend.html")

app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 26 * 1024 * 1024  # 25 MB image plus form overhead


from neonrest.media_features import (register_media, prepare_post_media, attach_post_media,
                                            init_media_tables, update_post_media_labels, FILTERS as MEDIA_FILTERS)
register_media(app, get_db)


def workflow_member():
    user_id = session.get('user_id')
    if not isinstance(user_id, int) or not get_db().execute('SELECT 1 FROM users WHERE id=? AND verified=1', (user_id,)).fetchone():
        abort(403)
    return user_id


def report_target(db, kind, target_id):
    queries = {
        'user': 'SELECT handle AS label, id AS owner_id FROM users WHERE id=?',
        'post': '''SELECT substr(content,1,100) AS label, user_id AS owner_id FROM posts
                   WHERE id=? AND NOT EXISTS(SELECT 1 FROM moderated_posts WHERE post_id=posts.id)''',
        'comment': '''SELECT substr(c.content,1,100) AS label, c.user_id AS owner_id FROM comments c
                      WHERE c.id=? AND NOT EXISTS(SELECT 1 FROM moderated_comments WHERE comment_id=c.id)
                      AND NOT EXISTS(SELECT 1 FROM moderated_posts WHERE post_id=c.post_id)'''
    }
    if kind not in queries:
        abort(404)
    target = db.execute(queries[kind], (target_id,)).fetchone()
    if not target:
        abort(404)
    return target


@app.route('/report/<kind>/<string:target_id>', methods=['GET','POST'])
def report_content(kind, target_id):
    member = workflow_member()
    db = get_db()
    target = report_target(db, kind, target_id)
    if target['owner_id'] == member:
        abort(403)
    if request.method == 'POST':
        if not valid_management_token():
            abort(400)
        reason = request.form.get('reason', '').strip()
        if not 10 <= len(reason) <= 500:
            abort(400)
        existing = db.execute("SELECT 1 FROM content_reports WHERE reporter_id=? AND target_type=? AND target_id=? AND status='open'", (member,kind,target_id)).fetchone()
        if existing:
            flash('You already have an open report for this item.', 'info')
        else:
            created = db.execute('INSERT INTO content_reports (reporter_id,target_type,target_id,reason) VALUES (?,?,?,?)', (member,kind,target_id,reason))
            attach_report(db, created.lastrowid)
            db.commit()
            flash('Report sent to the moderation team.', 'success')
        return redirect(url_for('my_reports'))
    return render_template('workflow_form.html', heading='Report '+kind, target=target['label'],
                           token=theme_csrf_token(), action='Send report', back=url_for('my_reports'))


@app.route('/reports/mine')
def my_reports():
    member = workflow_member()
    records = get_db().execute('SELECT * FROM content_reports WHERE reporter_id=? ORDER BY id DESC LIMIT 100', (member,)).fetchall()
    return render_template('workflow_list.html', heading='My reports', records=records, kind='reports')


@app.route('/manage/reports')
def manage_reports():
    require_staff_permission('review_reports')
    status = request.args.get('status','open')
    if status not in ('open','resolved','dismissed'):
        abort(400)
    records = get_db().execute('''SELECT r.*, u.handle AS member_handle FROM content_reports r
        JOIN users u ON u.id=r.reporter_id WHERE r.status=? ORDER BY r.id DESC LIMIT 100''', (status,)).fetchall()
    return render_template('workflow_queue.html', heading='Reports', records=records, queue='reports',
                           status=status, token=theme_csrf_token())


@app.route('/manage/reports/<int:report_id>/review', methods=['POST'])
def review_report(report_id):
    actor = require_staff_permission('review_reports')
    if not valid_management_token():
        abort(400)
    decision = request.form.get('decision','')
    reason = request.form.get('reason','').strip()
    if decision not in ('resolved','dismissed') or not 1 <= len(reason) <= 500:
        abort(400)
    db = get_db()
    report = db.execute('SELECT * FROM content_reports WHERE id=?', (report_id,)).fetchone()
    if not report:
        abort(404)
    if report['status'] != 'open' or report['reporter_id'] == actor:
        abort(403)
    db.execute('UPDATE content_reports SET status=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?', (decision,actor,report_id))
    db.execute('INSERT INTO moderation_events (actor_id,target_user_id,report_id,action,reason) VALUES (?,?,?,?,?)',
               (actor,report['reporter_id'],report_id,'report:'+decision,reason))
    attach_event(db, db.execute('SELECT last_insert_rowid()').fetchone()[0])
    db.commit()
    flash('Report reviewed.', 'success')
    return redirect(url_for('manage_reports'))


def appeal_active(db, member, kind, target_id):
    if kind in ('ban','posting','interaction'):
        if target_id != member:
            return False
        column = {'ban':'banned','posting':'posting_restricted','interaction':'interaction_restricted'}[kind]
        row = db.execute(f'SELECT {column} FROM user_moderation WHERE user_id=?', (member,)).fetchone()
        return bool(row and row[column])
    if kind in ('post','comment'):
        table, key, owner = ('moderated_posts','post_id','author_id') if kind=='post' else ('moderated_comments','comment_id','author_id')
        return bool(db.execute(f'SELECT 1 FROM {table} WHERE {key}=? AND {owner}=?', (target_id,member)).fetchone())
    return False


@app.route('/appeals')
def my_appeals():
    member = workflow_member()
    db = get_db()
    records = db.execute('SELECT * FROM moderation_appeals WHERE appellant_id=? ORDER BY id DESC LIMIT 100', (member,)).fetchall()
    restrictions = db.execute('SELECT banned,posting_restricted,interaction_restricted FROM user_moderation WHERE user_id=?', (member,)).fetchone()
    hidden_posts = db.execute('SELECT post_id FROM moderated_posts WHERE author_id=? ORDER BY post_id DESC LIMIT 50', (member,)).fetchall()
    hidden_comments = db.execute('SELECT comment_id FROM moderated_comments WHERE author_id=? ORDER BY comment_id DESC LIMIT 50', (member,)).fetchall()
    return render_template('workflow_list.html', heading='My appeals', records=records, kind='appeals',
                           restrictions=restrictions, hidden_posts=hidden_posts, hidden_comments=hidden_comments,
                           banned=bool(restrictions and restrictions['banned']))


@app.route('/appeal/<kind>/<string:target_id>', methods=['GET','POST'])
def appeal_form(kind, target_id):
    member = workflow_member()
    db = get_db()
    if not appeal_active(db,member,kind,target_id):
        abort(404)
    if request.method == 'POST':
        if not valid_management_token():
            abort(400)
        reason = request.form.get('reason','').strip()
        if not 10 <= len(reason) <= 500:
            abort(400)
        existing = db.execute("SELECT 1 FROM moderation_appeals WHERE appellant_id=? AND target_type=? AND target_id=? AND status='open'", (member,kind,target_id)).fetchone()
        if existing:
            flash('An appeal for this action is already open.', 'info')
        else:
            created = db.execute('INSERT INTO moderation_appeals (appellant_id,target_type,target_id,reason) VALUES (?,?,?,?)', (member,kind,target_id,reason))
            attach_appeal(db, created.lastrowid)
            db.commit()
            flash('Appeal sent.', 'success')
        return redirect(url_for('my_appeals'))
    return render_template('workflow_form.html', heading='Appeal '+kind, target='#'+str(identifiers.public(get_db(),kind,target_id) if kind in identifiers.KINDS else target_id),
                           token=theme_csrf_token(), action='Send appeal', back=url_for('my_appeals'))


@app.route('/manage/appeals')
def manage_appeals():
    require_staff_permission('review_appeals')
    status = request.args.get('status','open')
    if status not in ('open','upheld','overturned'):
        abort(400)
    records = get_db().execute('''SELECT a.*, u.handle AS member_handle FROM moderation_appeals a
        JOIN users u ON u.id=a.appellant_id WHERE a.status=? ORDER BY a.id DESC LIMIT 100''', (status,)).fetchall()
    return render_template('workflow_queue.html', heading='Appeals', records=records, queue='appeals',
                           status=status, token=theme_csrf_token())


@app.route('/manage/appeals/<int:appeal_id>/review', methods=['POST'])
def review_appeal(appeal_id):
    actor = require_staff_permission('review_appeals')
    if not valid_management_token():
        abort(400)
    decision = request.form.get('decision','')
    reason = request.form.get('reason','').strip()
    if decision not in ('upheld','overturned') or not 1 <= len(reason) <= 500:
        abort(400)
    db = get_db()
    appeal = db.execute('SELECT * FROM moderation_appeals WHERE id=?', (appeal_id,)).fetchone()
    if not appeal:
        abort(404)
    member, kind, target = appeal['appellant_id'], appeal['target_type'], appeal['target_id']
    if appeal['status'] != 'open' or member in (actor,1) or db.execute('SELECT 1 FROM staff_roles WHERE user_id=?', (member,)).fetchone():
        abort(403)
    if decision == 'overturned':
        if not appeal_active(db,member,kind,target):
            abort(409)
        if kind in ('ban','posting','interaction'):
            column = {'ban':'banned','posting':'posting_restricted','interaction':'interaction_restricted'}[kind]
            db.execute(f'UPDATE user_moderation SET {column}=0, reason=?, updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?', (reason,actor,member))
        else:
            table, key = ('moderated_posts','post_id') if kind=='post' else ('moderated_comments','comment_id')
            db.execute(f'DELETE FROM {table} WHERE {key}=? AND author_id=?', (target,member))
    db.execute('UPDATE moderation_appeals SET status=?, reviewed_by=?, decision_reason=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?',
               (decision,actor,reason,appeal_id))
    db.execute('''INSERT INTO moderation_events (actor_id,target_user_id,post_id,comment_id,appeal_id,action,reason)
        VALUES (?,?,?,?,?,?,?)''', (actor,member,target if kind=='post' else None,target if kind=='comment' else None,
                                 appeal_id,'appeal:'+decision+':'+kind,reason))
    attach_event(db, db.execute('SELECT last_insert_rowid()').fetchone()[0])
    db.commit()
    flash('Appeal reviewed.', 'success')
    return redirect(url_for('manage_appeals'))


@app.route('/manage/ads')
def manage_ads():
    require_staff_permission('manage_ads')
    db=get_db()
    campaigns=db.execute('''SELECT a.*, v.name AS vibe_name,
        (SELECT COUNT(*) FROM ad_events e WHERE e.campaign_id=a.id AND e.event_type='impression') AS impressions,
        (SELECT COUNT(*) FROM ad_events e WHERE e.campaign_id=a.id AND e.event_type='click') AS clicks
        FROM ad_campaigns a LEFT JOIN vibes v ON v.id=a.vibe_id ORDER BY a.id DESC LIMIT 100''').fetchall()
    vibes=db.execute('SELECT id,name FROM vibes ORDER BY name').fetchall()
    events=db.execute('''SELECT e.*, u.handle FROM ad_management_events e JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT 30''').fetchall()
    return render_template('manage_ads.html',campaigns=campaigns,vibes=vibes,events=events,management_token=theme_csrf_token())


@app.route('/manage/ads/save', methods=['POST'])
def save_ad():
    actor=require_staff_permission('manage_ads')
    if not valid_management_token():
        abort(400)
    db=get_db()
    raw_id=request.form.get('campaign_id','').strip()
    if raw_id and not raw_id.isdecimal():
        abort(400)
    campaign_id=int(raw_id) if raw_id else None
    previous=db.execute('SELECT * FROM ad_campaigns WHERE id=?',(campaign_id,)).fetchone() if campaign_id else None
    if campaign_id and not previous:
        abort(404)
    title=request.form.get('title','').strip()
    body=request.form.get('body','').strip()
    destination=request.form.get('destination_url','').strip()
    image_path=request.form.get('image_path','').strip()
    placement=request.form.get('placement','')
    vibe_raw=request.form.get('vibe_id','').strip()
    vibe_id=int(vibe_raw) if vibe_raw.isdecimal() else None
    starts=request.form.get('starts_at','').strip() or None
    ends=request.form.get('ends_at','').strip() or None
    reason=request.form.get('reason','').strip()
    if (not 1<=len(title)<=80 or not 1<=len(body)<=240 or placement not in ('rail','banner')
        or not validated_ad_destination(destination) or not validated_ad_image(image_path)
        or vibe_raw and not vibe_raw.isdecimal() or not 1<=len(reason)<=500):
        abort(400)
    for stamp in (starts,ends):
        if stamp:
            try: datetime.strptime(stamp,'%Y-%m-%dT%H:%M')
            except ValueError: abort(400)
    if starts and ends and starts>=ends:
        abort(400)
    if vibe_id and not db.execute('SELECT 1 FROM vibes WHERE id=?',(vibe_id,)).fetchone():
        abort(400)
    if campaign_id:
        db.execute('''UPDATE ad_campaigns SET title=?,body=?,destination_url=?,image_path=?,placement=?,
            vibe_id=?,starts_at=?,ends_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
            (title,body,destination,image_path,placement,vibe_id,starts,ends,campaign_id))
        action='update'
    else:
        cursor=db.execute('''INSERT INTO ad_campaigns
            (title,body,destination_url,image_path,placement,vibe_id,starts_at,ends_at,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)''', (title,body,destination,image_path,placement,vibe_id,starts,ends,actor))
        campaign_id=cursor.lastrowid
        action='create'
    db.execute('INSERT INTO ad_management_events(campaign_id,actor_id,action,reason) VALUES (?,?,?,?)',
               (campaign_id,actor,action,reason))
    db.commit()
    flash('Campaign saved. It remains paused until activated.', 'success')
    return redirect(url_for('manage_ads'))


@app.route('/manage/ads/<int:campaign_id>/state', methods=['POST'])
def set_ad_state(campaign_id):
    actor=require_staff_permission('manage_ads')
    if not valid_management_token():
        abort(400)
    state=request.form.get('state')
    reason=request.form.get('reason','').strip()
    if state not in ('0','1') or not 1<=len(reason)<=500:
        abort(400)
    db=get_db()
    ad=db.execute('SELECT active FROM ad_campaigns WHERE id=?',(campaign_id,)).fetchone()
    if not ad:
        abort(404)
    if ad['active']!=int(state):
        db.execute('UPDATE ad_campaigns SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(int(state),campaign_id))
        db.execute('INSERT INTO ad_management_events(campaign_id,actor_id,action,reason) VALUES (?,?,?,?)',
                   (campaign_id,actor,'activate' if state=='1' else 'pause',reason))
        db.commit()
    return redirect(url_for('manage_ads'))


@app.route('/ad/<int:campaign_id>/click')
def ad_click(campaign_id):
    db=get_db()
    ad=db.execute('''SELECT destination_url FROM ad_campaigns WHERE id=? AND active=1
        AND (starts_at IS NULL OR datetime(starts_at)<=CURRENT_TIMESTAMP)
        AND (ends_at IS NULL OR datetime(ends_at)>CURRENT_TIMESTAMP)''',(campaign_id,)).fetchone()
    if not ad or not validated_ad_destination(ad['destination_url']):
        abort(404)
    db.execute("INSERT INTO ad_events(campaign_id,event_type) VALUES (?,'click')",(campaign_id,))
    db.commit()
    response=redirect(ad['destination_url'])
    response.headers['Referrer-Policy']='no-referrer'
    return response


# Register community tools after all existing routes and helpers are defined.
import sys
from neonrest.community_features import register as register_community
register_community(app, sys.modules[__name__])
from neonrest.email_verification import register as register_verification
register_verification(app, sys.modules[__name__])
from neonrest.retention import initialize as initialize_retention
with app.app_context():
    initialize_retention(get_db())
app.config['RETENTION_ENABLED'] = False
from neonrest.retention import register_reserved_guard
register_reserved_guard(app,sys.modules[__name__])
from neonrest.account_disabling import register as register_account_disabling
register_account_disabling(app,sys.modules[__name__])
from neonrest.age_clock import register as register_age_clock
register_age_clock(app,sys.modules[__name__])
from neonrest.family_data import register as register_family_data
register_family_data(app,sys.modules[__name__])
from neonrest.email_change import register as register_email_change
register_email_change(app,sys.modules[__name__])
from neonrest.mail_queue import register as register_mail_queue
register_mail_queue(app,sys.modules[__name__])
identifiers.register(app,sys.modules[__name__])

@app.errorhandler(404)
def unavailable_page(error):
    response = app.make_response((render_template('unavailable.html'), 404))
    response.headers['Cache-Control'] = 'private, no-store'
    return response

if __name__ == '__main__':
    app.run(debug=False)

@app.errorhandler(413)
def upload_too_large(error):
    return render_template('upload_error.html'), 413

# Initialize optional tables for legacy Production databases.
with app.app_context():
    init_media_tables(get_db())
    init_profile_styles(get_db())
    get_db().execute("CREATE TABLE IF NOT EXISTS vibe_editors(vibe_id INTEGER NOT NULL,user_id INTEGER NOT NULL,PRIMARY KEY(vibe_id,user_id))")
    get_db().commit()
