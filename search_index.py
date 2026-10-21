"""External-content trigram indexes. Candidate matching never grants visibility."""
SCHEMAS={'users':('handle','location'),'posts':('content',),'circles':('name','description')}


def install(db):
    db.execute('SAVEPOINT growth_search_install')
    try:
        for table,fields in SCHEMAS.items():
            name='growth_'+table+'_fts'
            exists=db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone()
            columns=','.join(fields)
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS "+name+" USING fts5("+columns+",content='"+table+"',content_rowid='id',tokenize='trigram')")
            new=','.join('new.'+f for f in fields);old=','.join('old.'+f for f in fields)
            db.execute('CREATE TRIGGER IF NOT EXISTS '+name+'_ai AFTER INSERT ON '+table+' BEGIN INSERT INTO '+name+'(rowid,'+columns+') VALUES(new.id,'+new+'); END')
            db.execute('CREATE TRIGGER IF NOT EXISTS '+name+'_ad AFTER DELETE ON '+table+" BEGIN INSERT INTO "+name+'('+name+",rowid,"+columns+") VALUES('delete',old.id,"+old+'); END')
            db.execute('CREATE TRIGGER IF NOT EXISTS '+name+'_au AFTER UPDATE OF id,'+columns+' ON '+table+' BEGIN INSERT INTO '+name+'('+name+",rowid,"+columns+") VALUES('delete',old.id,"+old+'); INSERT INTO '+name+'(rowid,'+columns+') VALUES(new.id,'+new+'); END')
            if not exists:db.execute('INSERT INTO '+name+'('+name+") VALUES('rebuild')")
        db.execute('RELEASE growth_search_install')
    except Exception:
        db.execute('ROLLBACK TO growth_search_install');db.execute('RELEASE growth_search_install');raise


def candidates(table, field, term, alias, db=None):
    # Two-character terms retain the original substring scan. Quoted MATCH is literal,
    # and the ordinary escaped LIKE remains the final semantic check.
    if len(term)<3 or '\x00' in term:return '',[]
    assert table in SCHEMAS and (field is None or field in SCHEMAS[table])
    name='growth_'+table+'_fts'
    phrase='"'+term.replace('"','""')+'"'
    match=(field+' : ' if field else '')+phrase
    # Common terms are cheaper through the ordered timeline index. This bounded
    # probe chooses the plan without counting every matching document.
    if db is not None and len(db.execute('SELECT rowid FROM '+name+' WHERE '+name+' MATCH ? LIMIT 201',[match]).fetchall())>200:
        return '',[]
    return ' AND '+alias+'.id IN (SELECT rowid FROM '+name+' WHERE '+name+' MATCH ?)',[match]
