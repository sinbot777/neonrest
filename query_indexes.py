"""Additive non-unique indexes for existing profile, discussion and relationship queries."""
INDEXES = (
    ('idx_reactions_post_emoji_user', 'post_reactions', ('post_id', 'emoji', 'user_id'), 'CREATE INDEX IF NOT EXISTS idx_reactions_post_emoji_user ON post_reactions(post_id, emoji, user_id)'),
    ('idx_posts_author_created', 'posts', ('user_id', 'created_at', 'id'), 'CREATE INDEX IF NOT EXISTS idx_posts_author_created ON posts(user_id, created_at DESC, id DESC)'),
    ('idx_posts_target_created', 'posts', ('target_user_id', 'created_at', 'id'), 'CREATE INDEX IF NOT EXISTS idx_posts_target_created ON posts(target_user_id, created_at DESC, id DESC)'),
    ('idx_comments_post_created', 'comments', ('post_id', 'created_at', 'id'), 'CREATE INDEX IF NOT EXISTS idx_comments_post_created ON comments(post_id, created_at, id)'),
    ('idx_post_vibes_vibe_post', 'post_vibes', ('vibe_id', 'post_id'), 'CREATE INDEX IF NOT EXISTS idx_post_vibes_vibe_post ON post_vibes(vibe_id, post_id)'),
    ('idx_follows_active', 'follows', ('follower_id', 'revoked', 'followed_id'), 'CREATE INDEX IF NOT EXISTS idx_follows_active ON follows(follower_id, revoked, followed_id)'),
    ('idx_friend_requests_incoming', 'friend_requests', ('receiver_id', 'status', 'sender_id'), 'CREATE INDEX IF NOT EXISTS idx_friend_requests_incoming ON friend_requests(receiver_id, status, sender_id)'),
)

def install(db):
    """Install once at startup; leave existing row data and constraints unchanged."""
    db.execute('SAVEPOINT neonrest_query_indexes')
    try:
        for name, table, columns, sql in INDEXES:
            db.execute(sql)
            installed = tuple(row[2] for row in db.execute('PRAGMA index_info("' + name + '")'))
            if installed != columns:
                raise RuntimeError('Conflicting query index definition: ' + name)
    except Exception:
        db.execute('ROLLBACK TO neonrest_query_indexes')
        db.execute('RELEASE neonrest_query_indexes')
        raise
    db.execute('RELEASE neonrest_query_indexes')

