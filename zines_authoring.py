"""Issue-owned stories, named typography and reusable master elements."""
import json, secrets, copy, re
from . import zines_core as z

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS zine_authoring(issue_id TEXT PRIMARY KEY REFERENCES zine_issues(id),settings TEXT NOT NULL)')

def get(db,iid):
    row=db.execute('SELECT settings FROM zine_authoring WHERE issue_id=?',(iid,)).fetchone()
    return json.loads(row[0]) if row else dict(stories={},styles={},masters={})

def put(db,iid,state):
    raw=json.dumps(state,ensure_ascii=False)
    if len(raw.encode())>192000:raise z.ZineError('This issue’s stories and reusable settings exceed 192 KiB.')
    db.execute('INSERT INTO zine_authoring VALUES (?,?) ON CONFLICT(issue_id) DO UPDATE SET settings=excluded.settings',(iid,raw))

def documents(db,iid):
    return [(r,json.loads(r['content'])) for r in z.pages(db,iid)]

def catalog(docs):
    return {r['id']+':'+b['id']:(r,d,b) for r,d in docs if d.get('design')=='composition' for b in d.get('composition',{}).get('blocks',[])}

def prefix(text,b):
    """Find a complete-word prefix fitting the exact print Paragraph geometry."""
    from . import zines_pdf  # register the same fonts used by print
    from .zines_composition import FONTS
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from xml.sax.saxutils import escape
    style=ParagraphStyle('story',fontName=FONTS[b['font']],fontSize=b['size'],leading=b['size']*b['leading'],splitLongWords=True)
    def fits(n):
        if not text[:n].strip():return True
        p=Paragraph(escape(text[:n]).replace('\n','<br/>'),style)
        return p.wrap(b['w']-8,20000)[1]<=b['h']-8-.5
    lo,hi=0,min(6000,len(text))
    while lo<hi:
        mid=(lo+hi+1)//2
        if fits(mid):lo=mid
        else:hi=mid-1
    if lo<len(text) and lo and not text[lo-1].isspace() and not text[lo].isspace():
        cut=max(text.rfind(' ',0,lo),text.rfind('\n',0,lo),text.rfind('\t',0,lo))
        if cut>=0:lo=cut+1
    return lo

def reconcile(db,p,issue,user):
    state=get(db,issue['id'])
    if not any(state.values()):return
    docs=documents(db,issue['id']);by_page={r['id']:(r,d) for r,d in docs}
    # Replace only the tracked copies, preserving each page's other elements.
    for mid,master in state['masters'].items():
        master['pages']=[pid for pid in master['pages'] if pid in by_page]
        for pid in master['pages']:
            row,data=by_page[pid];page=data.get('composition')
            if data.get('design')!='composition' or not page:raise z.ZineError('A page with master elements must keep visual composition. Detach the master first.',409)
            page['blocks']=[b for b in page['blocks'] if not b['id'].startswith('m'+mid+'_')]
            number=next(i for i,(r,_) in enumerate(docs,1) if r['id']==pid)
            blocks=copy.deepcopy(master['blocks'])
            for i,b in enumerate(blocks):
                b['id']='m'+mid+'_'+str(i);b['locked']=True;b['group']=''
                if b['type']=='text':
                    for token,value in [('{page}',str(number)),('{pages}',str(len(docs))),('{title}',issue['title'])]:b['text']=b['text'].replace(token,value)
            page['blocks']=blocks+page['blocks']
    entries=catalog(docs)
    for style in state['styles'].values():
        style['frames']=[ref for ref in style['frames'] if ref in entries]
        for ref in style['frames']:
            b=entries[ref][2]
            if b['type']!='text':raise z.ZineError('A styled text frame changed type. Detach its style first.',409)
            b.update(style['values'])
    for story in state['stories'].values():
        remaining=story['text']
        if any(ref not in entries for ref in story['frames']):raise z.ZineError('A linked story frame was removed. Unlink the story in Publishing tools first.',409)
        # Follow current page/column order after pages move.
        order={r['id']:i for i,(r,_) in enumerate(docs)}
        story['frames'].sort(key=lambda ref:(order[ref.split(':')[0]],entries[ref][2]['y'],entries[ref][2]['x']))
        for ref in story['frames']:
            b=entries[ref][2]
            if b['type']!='text' or b.get('insets') or b['rotation']:raise z.ZineError('Linked stories need unrotated text frames without inline artwork.')
            n=prefix(remaining,b);b['text']=remaining[:n];remaining=remaining[n:]
        if remaining.strip():raise z.ZineError('Story overflow: '+str(len(remaining))+' characters need another frame. Add space or reduce type size; nothing was saved.',409)
    for row,data in docs:
        payload=z.content(db,p['id'],user,data)
        db.execute('UPDATE zine_pages SET content=? WHERE id=?',(payload,row['id']))
    put(db,issue['id'],state)

def guard_page(db,iid,pid,before,after):
    state=get(db,iid);old={b['id']:b for b in before.get('composition',{}).get('blocks',[])};new={b['id']:b for b in after.get('composition',{}).get('blocks',[])}
    for mid,master in state['masters'].items():
        if pid in master['pages']:
            for bid,b in old.items():
                if bid.startswith('m'+mid+'_') and new.get(bid)!=b:raise z.ZineError('This is a master element. Update or detach its master in Publishing tools before editing it here.',409)
    for style in state['styles'].values():
        for ref in style['frames']:
            page,bid=ref.split(':')
            if page==pid and bid in old and bid in new and any(new[bid].get(k)!=old[bid].get(k) for k in style['values']):raise z.ZineError('A named style controls this frame. Update the style or detach the frame in Publishing tools first.',409)
    for story in state['stories'].values():
        for ref in story['frames']:
            page,bid=ref.split(':')
            if page==pid and bid in new and new[bid].get('text','').strip()!=old.get(bid,{}).get('text','').strip():raise z.ZineError('Edit this linked article’s source text in Publishing tools. Frame geometry can be edited here.',409)

def edit(db,p,issue,user,form):
    state=get(db,issue['id']);docs=documents(db,issue['id']);entries=catalog(docs);action=form.get('studio_action');ident=form.get('item_id','')
    name=z.text(form.get('name',''),60,True) if action in ('story','style','master') else ''
    refs=form.getlist('frames');valid=lambda refs:len(refs)==len(set(refs)) and all(ref in entries and entries[ref][2]['type']=='text' for ref in refs)
    if action=='story':
        if not 2<=len(refs)<=32 or not valid(refs):raise z.ZineError('Select two to thirty-two text frames from this issue.')
        if ident and ident not in state['stories']:raise z.ZineError('Story unavailable.',404)
        for sid,story in state['stories'].items():
            if sid!=ident and set(refs)&set(story['frames']):raise z.ZineError('A frame can belong to only one story.')
        if not ident and len(state['stories'])>=12:raise z.ZineError('Use at most twelve stories per issue.')
        ident=ident or secrets.token_hex(6);state['stories'][ident]=dict(name=name,text=z.text(form.get('story_text',''),24000,True),frames=refs)
    elif action=='unlink':
        if ident not in state['stories']:raise z.ZineError('Story unavailable.',404)
        del state['stories'][ident]
    elif action=='style':
        from .zines_composition import number,color,FONTS
        if not valid(refs):raise z.ZineError('Choose valid text frames.')
        if ident and ident not in state['styles']:raise z.ZineError('Style unavailable.',404)
        if not ident and len(state['styles'])>=24:raise z.ZineError('Use at most twenty-four styles per issue.')
        try:values=dict(font=form.get('font'),size=number(float(form.get('size','12')),6,72,'size'),leading=number(float(form.get('leading','1.35')),1,2,'line spacing'),align=form.get('align'),color=color(form.get('color')))
        except (ValueError,TypeError):raise z.ZineError('Choose valid typography values.')
        if values['font'] not in FONTS or values['align'] not in ('left','center','right'):raise z.ZineError('Unsupported typography.')
        for sid,style in state['styles'].items():
            if sid!=ident:style['frames']=[ref for ref in style['frames'] if ref not in refs]
        state['styles'][ident or secrets.token_hex(6)]=dict(name=name,values=values,frames=refs)
    elif action=='delete_style':
        if ident not in state['styles']:raise z.ZineError('Style unavailable.',404)
        del state['styles'][ident]
    elif action=='master':
        if ident and ident not in state['masters']:raise z.ZineError('Master unavailable.',404)
        if not ident and len(state['masters'])>=8:raise z.ZineError('Use at most eight masters per issue.')
        source=form.get('source_page');source_data=next((d for r,d in docs if r['id']==source),None)
        if not source_data:raise z.ZineError('Choose a source page.')
        blocks=[copy.deepcopy(b) for b in source_data.get('composition',{}).get('blocks',[]) if b.get('locked') and not re.match(r'^m[0-9a-f]{12}_',b['id'])]
        if not 1<=len(blocks)<=8:raise z.ZineError('Lock one to eight source elements to define this master. Existing master copies are excluded.')
        assigned=form.getlist('master_pages')
        if source in assigned:raise z.ZineError('The source already contains the original master elements. Select other target pages.')
        pages={r['id'] for r,_ in docs}
        if len(assigned)!=len(set(assigned)) or not set(assigned)<=pages:raise z.ZineError('Choose pages from this issue.')
        if ident:
            for row,data in docs:
                if 'composition' in data:data['composition']['blocks']=[b for b in data['composition']['blocks'] if not b['id'].startswith('m'+ident+'_')]
                db.execute('UPDATE zine_pages SET content=? WHERE id=?',(z.content(db,p['id'],user,data),row['id']))
        state['masters'][ident or secrets.token_hex(6)]=dict(name=name,blocks=blocks,pages=assigned,source=source)
    elif action=='detach_master':
        if ident not in state['masters']:raise z.ZineError('Master unavailable.',404)
        # Keep existing copies as ordinary editable elements.
        for row,data in docs:
            for b in data.get('composition',{}).get('blocks',[]):
                if b['id'].startswith('m'+ident+'_'):b['id']='e'+secrets.token_hex(6);b['locked']=False
            db.execute('UPDATE zine_pages SET content=? WHERE id=?',(z.content(db,p['id'],user,data),row['id']))
        del state['masters'][ident]
    else:raise z.ZineError('Unsupported publishing-tool action.')
    put(db,issue['id'],state);reconcile(db,p,issue,user)

def register(bp,core,actor,writing,revision,render,budget):
    from flask import request,redirect,url_for
    @bp.post('/zines/<zid>/issues/<iid>/restore/<int:old_revision>')
    def restore_issue(zid,iid,old_revision):
        user=actor();db=core.get_db();p=z.publication(db,zid);z.require(db,p,user)
        response=writing()
        if response is not None:return response
        with db:
            db.execute('BEGIN IMMEDIATE');issue=z.get_issue(db,p,iid);z.check_revision(issue,revision());z.draft(issue)
            if request.form.get('restore_confirm')!='1':raise z.ZineError('Confirm replacing this draft with the selected snapshot.')
            row=db.execute('SELECT snapshot FROM zine_revisions WHERE issue_id=? AND revision=? ORDER BY id DESC LIMIT 1',(iid,old_revision)).fetchone()
            if not row:raise z.ZineError('This snapshot is no longer retained.',404)
            saved=json.loads(row['snapshot']);pages=saved['pages']
            if not 2<=len(pages)<=64 or pages[0]['kind']!='cover' or pages[-1]['kind']!='back':raise z.ZineError('This snapshot has no complete issue layout.')
            prepared=[]
            for page in pages:
                if not z.compatible(db,page['author_id'],user):raise z.ZineError('A snapshot contributor is no longer eligible.',404)
                conflict=db.execute('SELECT issue_id FROM zine_pages WHERE id=?',(page['id'],)).fetchone()
                if conflict and conflict[0]!=iid:raise z.ZineError('Snapshot page unavailable.',409)
                prepared.append((page,z.content(db,zid,user,json.loads(page['content']))))
            z.touch_issue(db,issue,user)
            db.execute('DELETE FROM zine_pages WHERE issue_id=?',(iid,))
            for page,payload in prepared:db.execute('INSERT INTO zine_pages VALUES (?,?,?,?,?,?)',(page['id'],iid,page['author_id'],page['position'],page['kind'],payload))
            db.execute('UPDATE zine_issues SET title=?,allow_print=? WHERE id=?',(z.text(saved['issue']['title'],160,True),int(bool(saved['issue']['allow_print'])),iid))
            from . import zines_sizes
            db.execute('DELETE FROM zine_issue_sizes WHERE issue_id=?',(iid,))
            if saved.get('page_size'):
                size=saved['page_size'];db.execute('INSERT INTO zine_issue_sizes VALUES (?,?,?,?)',(iid,size['width'],size['height'],size['content_scale']))
            put(db,iid,saved.get('authoring',dict(stories={},styles={},masters={})))
            reconcile(db,p,z.get_issue(db,p,iid),user);budget(db,p['owner_id'])
        return redirect(url_for('zines.issue_edit',zid=zid,iid=iid,saved=1))
    @bp.route('/zines/<zid>/issues/<iid>/studio',methods=['GET','POST'])
    def studio(zid,iid):
        user=actor();db=core.get_db();p=z.publication(db,zid);z.require(db,p,user);issue=z.get_issue(db,p,iid)
        if request.method=='POST':
            if not z.visible(db,p,issue,user):raise z.ZineError('An issue contributor or image is unavailable.',404)
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE');issue=z.get_issue(db,p,iid);z.check_revision(issue,revision());z.draft(issue);z.touch_issue(db,issue,user);edit(db,p,issue,user,request.form);budget(db,p['owner_id'])
            return redirect(url_for('zines.studio',zid=zid,iid=iid,saved=1))
        docs=documents(db,iid)
        if not z.visible(db,p,issue,user):raise z.ZineError('An issue contributor or image is unavailable.',404)
        frames=[dict(ref=r['id']+':'+b['id'],label='Page '+str(i)+' · '+(b.get('name') or b['id'])+' · '+b.get('text','')[:45]) for i,(r,d) in enumerate(docs,1) if d.get('design')=='composition' for b in sorted(d.get('composition',{}).get('blocks',[]),key=lambda b:(b['y'],b['x'])) if b['type']=='text' and not re.match(r'^m[0-9a-f]{12}_',b['id'])]
        return render('authoring',publication=p,issue=issue,studio=get(db,iid),frames=frames,studio_pages=[dict(id=r['id'],label='Page '+str(i)+' · '+(d.get('heading') or r['kind'])) for i,(r,d) in enumerate(docs,1)])
