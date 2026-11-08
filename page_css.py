"""Bounded, Page-scoped custom CSS; remote resources and markup are prohibited."""
import re

STARTER = '''/* Page styles. These rules affect this Page's content only. */
.page-profile { background: #172032; color: #f3f4f6; }
.page-profile-about { border-radius: .7rem; }
.page-product-card { border-radius: .65rem; }
/* Example: .page-profile h2 { color: #7dd3c7; } */
'''


def validate(css):
    if not isinstance(css, str) or len(css) > 30000 or any(c in css for c in '<\\'):
        raise ValueError('Use at most 30,000 characters of CSS without markup or escapes.')
    stripped = []
    cursor = 0
    while cursor < len(css):
        start = css.find('/*', cursor)
        if start < 0:
            stripped.append(css[cursor:]); break
        stripped.append(css[cursor:start])
        end = css.find('*/', start + 2)
        if end < 0:
            raise ValueError('Close all CSS comments.')
        cursor = end + 2
    source = ''.join(stripped)
    if ('@' in re.sub(r'@media\b', '', source, flags=re.I) or '*/' in source
            or '://' in source or 'data:' in source.lower()
            or re.search(r'\b(?:url|expression|behavior|image|image-set|cross-fade|paint|src)\s*[:(]', source, re.I)):
        raise ValueError('Use local CSS rules only: no imports, URLs, fonts, or executable content. @media is supported.')
    depth = blocks = 0
    quote = None
    for char in source:
        if quote:
            if char == quote: quote = None
        elif char in "\"'": quote = char
        elif char == '{':
            depth += 1; blocks += 1
        elif char == '}':
            depth -= 1
            if depth < 0: raise ValueError('CSS braces must stay inside the Page stylesheet.')
    if depth or quote or blocks > 150:
        raise ValueError('Close all CSS braces and quotes; use at most 150 rule blocks.')
    return css


def initialize(db):
    if 'custom_css' not in {r[1] for r in db.execute('PRAGMA table_info(identity_pages)')}:
        db.execute("ALTER TABLE identity_pages ADD COLUMN custom_css TEXT NOT NULL DEFAULT ''")


def rendered(page):
    try:
        return validate(page['custom_css'])
    except (ValueError, KeyError, IndexError):
        return ''


def save(db, pages, uid, page_id, revision, css):
    page = pages.get(db, page_id)
    pages.require_role(db, page, uid, ('owner', 'manager', 'editor'))
    if page['state'] == 'archived':
        raise pages.PageError('Restore this Page before editing its CSS.', 409)
    try:
        css = validate(css)
    except ValueError as error:
        raise pages.PageError(str(error)) from None
    changed = db.execute('UPDATE identity_pages SET custom_css=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?',
                         (css, int(pages.time.time()), page_id, revision))
    if changed.rowcount != 1:
        raise pages.PageError('This Page changed. Reload before saving CSS.', 409)
    pages.event(db, page_id, uid, 'css_edited')
