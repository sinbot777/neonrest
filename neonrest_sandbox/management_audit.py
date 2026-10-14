"""Bounded, literal Management searches; retained event IDs survive account deletion."""
import re
from flask import abort, request

def identity_query(raw):
    query=(raw or '').strip()
    if len(query)>60: abort(400,description='Use at most 60 characters in the account filter.')
    match=re.fullmatch(r'(?:NUID\s*[:#]?\s*#?\s*|#\s*)?([0-9]+)',query,re.IGNORECASE)
    return query,str(int(match.group(1))) if match else None

def literal_pattern(query):
    value=query.lstrip('@')
    if not value: abort(400,description='Enter a handle or numeric NUID.')
    return '%'+value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'

def history_filters(db):
    action=request.args.get('mod_type','').strip()
    if len(action)>100: abort(400,description='Invalid action filter.')
    who=request.args.get('who','either')
    if who not in ('either','actor','subject'): abort(400,description='Invalid account filter scope.')
    if action and not db.execute('SELECT 1 FROM moderation_events WHERE action=? LIMIT 1',(action,)).fetchone():
        abort(400,description='Unknown moderation action filter.')
    query,identifier=identity_query(request.args.get('q',''))
    clauses,params=['1=1'],[]
    if action:clauses.append('e.action=?');params.append(action)
    if query:
        columns=[('actor.handle','e.actor_id'),('target.handle','e.target_user_id')]
        if who=='actor':columns=columns[:1]
        if who=='subject':columns=columns[1:]
        choices=[]
        for handle,uid in columns:
            if identifier is not None:choices.append('CAST('+uid+' AS TEXT)=?');params.append(identifier)
            else:choices.append(handle+" LIKE ? ESCAPE '\\'");params.append(literal_pattern(query))
        clauses.append('('+' OR '.join(choices)+')')
    return ' AND '.join(clauses),params,action,query,who
