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
        return scoped(page['custom_css'])
    except (ValueError, KeyError, IndexError):
        return ''


def scoped(css):
    """Compile ordinary rules and media groups into rooted selectors, without @scope."""
    validate(css)
    source = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    root = '.identity-page.page-profile'

    def selectors(header):
        parts = []; start = depth = 0; quote = None
        for i, char in enumerate(header):
            if quote:
                if char == quote: quote = None
            elif char in "\"'": quote = char
            elif char in '([': depth += 1
            elif char in ')]':
                depth -= 1
                if depth < 0: raise ValueError('Check CSS selector parentheses.')
            elif char in '+~':
                raise ValueError('Sibling combinators are not supported in Page CSS. Use descendant or child selectors.')
            elif char == ',' and depth == 0:
                parts.append(header[start:i]); start = i + 1
        if depth or quote: raise ValueError('Close all CSS selector parentheses and quotes.')
        parts.append(header[start:]); output = []
        for part in parts:
            part = part.strip()
            if not part or any(c in part for c in ';{}&@'):
                raise ValueError('Use ordinary CSS selectors without nesting.')
            match = re.match(r'(?:\.page-profile|:scope)(?![\w-])', part)
            output.append(root + part[match.end():] if match else root + ' ' + part)
        return ', '.join(output)

    def blocks(text, level=0):
        if level > 8: raise ValueError('Use at most eight nested media groups.')
        output = []; start = 0; opening = None; depth = 0; quote = None
        for i, char in enumerate(text):
            if quote:
                if char == quote: quote = None
                continue
            if char in "\"'": quote = char
            elif char == '{':
                if depth == 0: opening = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    header = text[start:opening].strip(); body = text[opening + 1:i]
                    if re.match(r'@media\b', header, re.I):
                        if ';' in header: raise ValueError('Check the media query.')
                        output.append(header + '{' + blocks(body, level + 1) + '}')
                    else:
                        # Braces in quoted content values are fine; nested CSS rules are not.
                        plain = re.sub(r'"[^"\n]*"|\x27[^\x27\n]*\x27', '', body)
                        if '{' in plain or '}' in plain: raise ValueError('Use separate CSS rules instead of nested rules.')
                        output.append(selectors(header) + '{' + body + '}')
                    start = i + 1
        if text[start:].strip(): raise ValueError('Every CSS rule needs braces.')
        return '\n'.join(output)
    return blocks(source)


def save(db, pages, uid, page_id, revision, css):
    page = pages.get(db, page_id)
    pages.require_role(db, page, uid, ('owner', 'manager', 'editor'))
    if page['state'] == 'archived':
        raise pages.PageError('Restore this Page before editing its CSS.', 409)
    try:
        css = validate(css)
        scoped(css)
    except ValueError as error:
        raise pages.PageError(str(error)) from None
    changed = db.execute('UPDATE identity_pages SET custom_css=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?',
                         (css, int(pages.time.time()), page_id, revision))
    if changed.rowcount != 1:
        raise pages.PageError('This Page changed. Reload before saving CSS.', 409)
    pages.event(db, page_id, uid, 'css_edited')
