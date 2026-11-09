"""Validated per-Page section placement; products are an explicit opt-in."""
import json

DEFAULTS = dict(products_enabled=False, main='updates', secondary='sidebar', details='left')


def settings(value):
    if isinstance(value, str):
        if len(value) > 2048: raise ValueError('Page layout settings are too large.')
        try: value = json.loads(value)
        except (ValueError, RecursionError): raise ValueError('Invalid Page layout settings.') from None
    if not isinstance(value, dict) or set(value) - set(DEFAULTS): raise ValueError('Invalid Page layout settings.')
    result = dict(DEFAULTS, **value)
    if (type(result['products_enabled']) is not bool or result['main'] not in ('updates', 'products')
            or result['secondary'] not in ('sidebar', 'below', 'hidden') or result['details'] not in ('left', 'right', 'hidden')):
        raise ValueError('Choose an available Page layout option.')
    return result


def read(page):
    try: return settings(page['layout_settings'])
    except (ValueError, KeyError, IndexError): return dict(DEFAULTS)


def presentation(page):
    value = read(page)
    main = value['main'] if value['products_enabled'] else 'updates'
    secondary = ('updates' if main == 'products' else 'products') if value['products_enabled'] and value['secondary'] != 'hidden' else None
    columns = []; sizes = []; panels = []
    if value['details'] == 'left':
        columns.append('details'); sizes.append('minmax(190px,.85fr)'); panels.append(dict(kind='details', area='details'))
    columns.append('main'); sizes.append('minmax(0,2fr)'); panels.append(dict(kind=main, area='main'))
    if secondary and value['secondary'] == 'sidebar':
        columns.append('secondary'); sizes.append('minmax(230px,1fr)'); panels.append(dict(kind=secondary, area='secondary', sidebar=True))
    if value['details'] == 'right':
        columns.append('details'); sizes.append('minmax(190px,.85fr)'); panels.append(dict(kind='details', area='details'))
    rows = [' '.join(columns)]
    if secondary and value['secondary'] == 'below':
        rows.append(' '.join('details' if col == 'details' else 'secondary' for col in columns))
        panels.append(dict(kind=secondary, area='secondary'))
    return dict(panels=panels, show_products=any(p['kind']=='products' for p in panels),
                show_updates=any(p['kind']=='updates' for p in panels), show_details=value['details']!='hidden',
                style='--page-layout-columns:'+' '.join(sizes)+';--page-layout-areas:'+' '.join('"'+row+'"' for row in rows))


def initialize(db):
    if 'layout_settings' not in {row[1] for row in db.execute('PRAGMA table_info(identity_pages)')}:
        db.execute("ALTER TABLE identity_pages ADD COLUMN layout_settings TEXT NOT NULL DEFAULT '{}'")


def save(db, pages, uid, page_id, revision, form):
    page = pages.get(db, page_id)
    pages.require_role(db, page, uid, ('owner', 'manager', 'editor'))
    if page['state'] == 'archived': raise pages.PageError('Restore this Page before editing its layout.', 409)
    try:
        if form.get('products_enabled', '') not in ('', '1'): raise ValueError('Choose whether to show products.')
        value = settings(dict(products_enabled=form.get('products_enabled')=='1', main=form.get('layout_main'),
                              secondary=form.get('layout_secondary'), details=form.get('layout_details')))
    except ValueError as error: raise pages.PageError(str(error)) from None
    changed = db.execute('UPDATE identity_pages SET layout_settings=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?',
                         (json.dumps(value, separators=(',', ':')), int(pages.time.time()), page_id, revision))
    if changed.rowcount != 1: raise pages.PageError('This Page changed. Reload before saving its layout.', 409)
    pages.event(db, page_id, uid, 'layout_edited')
