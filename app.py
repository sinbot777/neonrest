from flask import Flask, render_template, request, redirect, session, flash, g, jsonify, url_for
import sqlite3
import os
import logging
import re

from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email
import itsdangerous

from utils import generate_unique_handle

# Basic logging setup
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Secret key for token generation
app.secret_key = os.urandom(24)

# MailerSend SMTP configuration
app.config['MAIL_SERVER'] = 'smtp.mailersend.net'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'MS_xnbgGG@neonrest.com'
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')  # Set this in environment
app.config['MAIL_DEFAULT_SENDER'] = ('Neonrest', 'MS_xnbgGG@neonrest.com')

# Initialize Flask-Mail
mail = Mail(app)

# Token serializer
s = itsdangerous.URLSafeTimedSerializer(app.secret_key)

# SQLite DB path
DATABASE = '/home/sinbot/db/neonrest.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            handle TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            bio TEXT
        );
    ''')
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
    db.commit()


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

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email'].strip()
        handle = request.form['handle'].strip()
        password = request.form['password']

        # Ensure email is valid
        try:
            validate_email(email)
        except Exception as e:
            flash(str(e), 'error')
            return redirect('/signup')

        hashed = generate_password_hash(password)

        db = get_db()

        # Check if email or handle already exists
        existing = db.execute('SELECT 1 FROM users WHERE handle = ? OR email = ?', (handle, email)).fetchone()
        if existing:
            flash("That handle or email is already in use. Try something else!", 'error')
            return redirect('/signup')

        # Insert the user with verified = 0
        avatar_filename = None  # placeholder until avatar uploads are implemented

        db.execute('''
            INSERT INTO users (email, handle, password_hash, verified, avatar)
            VALUES (?, ?, ?, 0, ?)
        ''', (email, handle, hashed, avatar_filename))
        db.commit()

        # Send the verification email
        token = s.dumps(email, salt="email-verification")
        verification_url = url_for('verify_email', token=token, _external=True)

        msg = Message(
            subject="Please verify your email",
            recipients=[email]
        )
        msg.body = f"""Hi there!

Thanks for signing up for Neonrest ✨

Click the link below to verify your email address:

{verification_url}

If you didn’t create this account, feel free to ignore this message.
"""

        mail.send(msg)

        flash("A verification email has been sent. Please check your inbox.", 'success')
        return redirect('/login')

    return render_template('signup.html')

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
                # Resend verification email
                token = s.dumps(user['email'], salt="email-verification")
                verification_url = url_for('verify_email', token=token, _external=True)

                msg = Message(
                    subject="Resend: Please verify your email",
                    recipients=[user['email']]
                )
                msg.body = f"""Hi again!

                You tried to log into Neonrest, but your email hasn't been verified yet.

                Click the link below to finish verification:

                {verification_url}

                If you didn’t create this account, feel free to ignore this message.
                """
                mail.send(msg)
                flash("A new verification email has been sent.", "info")

                flash('Please verify your email before logging in.', 'error')
                return redirect('/login')

            # If the email is verified, log them in
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            session['user_handle'] = user['handle']

            flash('Logged in successfully.', 'success')
            return redirect('/feed')  # Redirect to the user's feed or homepage

        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')


@app.route('/@<handle>')
def user_by_handle(handle):
    if not handle.startswith("@"):
        handle = "@" + handle

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE handle = ?', (handle,)).fetchone()
    if not user:
        flash("User not found.", "error")
        return redirect("/")

    posts = db.execute('''
        SELECT * FROM posts
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user['id'],)).fetchall()

    return render_template("user.html", user=user, posts=posts)


@app.route('/user/<int:user_id>')
def user_page(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('User not found.', 'error')
        return redirect('/')

    posts = db.execute('''
        SELECT posts.id, posts.user_id, posts.content, posts.circle, posts.created_at,
               GROUP_CONCAT(vibes.name, ', ') AS vibes
        FROM posts
        LEFT JOIN post_vibes ON posts.id = post_vibes.post_id
        LEFT JOIN vibes ON post_vibes.vibe_id = vibes.id
        WHERE posts.user_id = ?
        GROUP BY posts.id
        ORDER BY posts.created_at DESC
    ''', (user_id,)).fetchall()

    return render_template('user.html', user=user, posts=posts)


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
    return redirect(f"/@{session['user_handle'].lstrip('@')}")


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
                    db.commit()
                    session['user_handle'] = new_handle
                    flash("Handle updated successfully.", 'success')

        if 'new_password' in request.form:
            new_password = request.form['new_password'].strip()
            if new_password:
                new_hash = generate_password_hash(new_password)
                db.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user['id']))
                db.commit()
                flash("Password updated successfully.", 'success')

    return render_template('account.html', user=user)

@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    print("🟢 This is the updated /create_post route")
    if 'user_id' not in session:
        flash("Please log in to post.", 'error')
        return redirect('/login')

    if request.method == 'POST':
        content = request.form['content'].strip()
        vibes_input = request.form['vibes'].strip()  # Fix: using 'vibes' instead of 'vibe'
        circle = request.form['circle'].strip()

        if not content:
            flash("Post content cannot be empty.", 'error')
        else:
            db = get_db()
            # Insert post (no post_vibe column anymore)
            db.execute('''
                INSERT INTO posts (user_id, content, circle)
                VALUES (?, ?, ?)
            ''', (session['user_id'], content, circle))
            db.commit()

            post_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

            # Associate vibes
            vibe_names = [v.strip() for v in vibes_input.split(',') if v.strip()]
            for vibe_name in vibe_names:
                vibe = db.execute('SELECT id FROM vibes WHERE name = ?', (vibe_name,)).fetchone()
                if not vibe:
                    db.execute('INSERT INTO vibes (name) VALUES (?)', (vibe_name,))
                    db.commit()
                    vibe = db.execute('SELECT id FROM vibes WHERE name = ?', (vibe_name,)).fetchone()
                db.execute('INSERT INTO post_vibes (post_id, vibe_id) VALUES (?, ?)', (post_id, vibe['id']))
            db.commit()

            flash("Post created!", 'success')
            return redirect('/feed')

    return render_template('create_post.html')


@app.route('/markdown-guide')
def markdown_guide():
    return render_template('markdown-guide.html')

@app.route('/feed')
def feed():
    if 'user_id' not in session:
        flash("Please log in to view your feed.", "error")
        return redirect('/login')

    db = get_db()
    posts = db.execute('''
    SELECT posts.id, posts.user_id, posts.content, posts.circle, posts.created_at, posts.last_edited, users.handle,
           GROUP_CONCAT(vibes.name, ', ') AS vibes
    FROM posts
    JOIN users ON users.id = posts.user_id
    LEFT JOIN post_vibes ON posts.id = post_vibes.post_id
    LEFT JOIN vibes ON post_vibes.vibe_id = vibes.id
    GROUP BY posts.id
    ORDER BY posts.created_at DESC
    ''').fetchall()

    return render_template('feed.html', posts=posts, vibe_slug='mixed')

@app.route('/edit_post/<int:post_id>', methods=['GET', 'POST'])
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
        new_content = request.form['content'].strip()
        new_vibe = request.form['vibes'].strip()
        new_circle = request.form['circle'].strip()

        if not new_content:
            flash("Post content cannot be empty.", 'error')
        else:
            db.execute('''
                UPDATE posts
                SET content = ?, vibe = ?, circle = ?, last_edited = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_content, new_vibe, new_circle, post_id))
            db.commit()
            flash("Post updated successfully!", 'success')
            return redirect('/feed')

    return render_template('edit_post.html', post=post)

@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        flash("Please log in to delete posts.", "error")
        return redirect('/login')

    db = get_db()
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()

    if not post or post['user_id'] != session['user_id']:
        flash("You do not have permission to delete this post.", "error")
        return redirect('/feed')

    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()
    flash("Post deleted successfully.", "success")
    return redirect('/feed')

@app.route('/vibe/<vibe_name>')
def vibe_page(vibe_name):
    db = get_db()
    vibe = db.execute('SELECT * FROM vibes WHERE name = ?', (vibe_name,)).fetchone()
    if not vibe:
        flash("That vibe doesn't exist yet.", "error")
        return redirect('/feed')

    posts = db.execute('''
        SELECT posts.id, posts.user_id, posts.content, posts.circle, posts.created_at,
               posts.last_edited, users.handle,
               GROUP_CONCAT(vibes.name, ', ') AS vibes
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN post_vibes ON posts.id = post_vibes.post_id
        LEFT JOIN vibes ON post_vibes.vibe_id = vibes.id
        WHERE posts.id IN (
            SELECT post_id FROM post_vibes WHERE vibe_id = ?
        )
        GROUP BY posts.id
        ORDER BY posts.created_at DESC
    ''', (vibe['id'],)).fetchall()

    vibe_slug = vibe_name.lower().replace(" ", "-")
    return render_template('vibe_page.html', vibe_name=vibe_name, vibe_slug=vibe_slug, posts=posts)

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


if __name__ == '__main__':
    app.run(debug=True)
