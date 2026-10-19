"""Bounded lookup reuse during one read-only HTTP request, never across requests."""
from functools import wraps
from flask import g, has_request_context, request


def request_lookup(function):
    """Reuse scalar/Row-keyed lookups; writes and transactions bypass reuse.

    Connection identity separates databases. SQLite's change counter invalidates
    results after writes, including rolled-back writes. POST and background jobs
    always execute the original function. No authorization result survives a
    request or is reused while a database transaction is open.
    """
    @wraps(function)
    def lookup(db, *args, **kwargs):
        if (not has_request_context() or request.method not in ('GET', 'HEAD')
                or db.in_transaction):
            return function(db, *args, **kwargs)
        key = (function, args, tuple(sorted(kwargs.items())))
        try:
            hash(key)
        except TypeError:
            return function(db, *args, **kwargs)
        stores = g.setdefault('_render_lookup_stores', {})
        generation = db.total_changes
        state = stores.get(db)
        if state is None or state[0] != generation:
            state = (generation, {})
            stores[db] = state
        cache = state[1]
        if key in cache:
            return cache[key]
        value = function(db, *args, **kwargs)
        if not db.in_transaction and db.total_changes == generation:
            if len(cache) >= 4096:
                cache.clear()
            cache[key] = value
        return value
    return lookup
