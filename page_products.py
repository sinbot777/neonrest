"""Read-only Page storefronts using the Marketplace's existing publication grants."""


def browse(db, viewer, page, number='1'):
    from . import identity_pages as pages, marketplace_catalog as catalog
    _, _, number = catalog.options(page=number)
    result = dict(items=[], has_next=False, page=number)
    # Owning a private Page never makes its shop drafts public.
    if page['state'] != 'published' or not pages.visible(db, page, viewer) or pages.hidden(db, page['id']):
        return result
    # Pages also run in installations without the optional Marketplace tables.
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('seller_shops','seller_listings','marketplace_publications')")}
    if len(tables) != 3:
        return result
    rows = db.execute(catalog.SELECT + ''' AND s.identity_kind='page' AND s.linked_page_id=? AND s.owner_id=?
        ORDER BY p.published_at DESC,l.id LIMIT ? OFFSET ?''',
        (page['id'], page['owner_id'], catalog.PAGE_SIZE + 1, (number - 1) * catalog.PAGE_SIZE)).fetchall()
    result.update(items=[dict(row) for row in rows[:catalog.PAGE_SIZE] if catalog.allowed(db, row, viewer)],
                  has_next=len(rows) > catalog.PAGE_SIZE)
    for item in result['items']:
        item['gallery_images'] = catalog.images(item)
    return result
