"""Physical-sheet geometry; panels never move to accommodate printer margins.

Eight-page ordering follows Chandra's one-sheet folding diagram:
https://chandra.si.edu/make/images/Zine_folding.pdf
Top row (rotated): 5,4,3,2. Bottom row: 6,7,8/back,1/front.
"""
import math
from .zines_core import ZineError

def mini8(reading):
    if not 2<=len(reading)<=8:raise ZineError('The single-sheet fold supports 2–8 pages, including covers. Use a booklet for longer issues.')
    if reading[0]['kind']!='cover' or reading[-1]['kind']!='back':raise ZineError('The single-sheet fold needs front and back covers.')
    padded=list(reading[:-1])+[None]*(8-len(reading))+[reading[-1]]
    order=[4,3,2,1,5,6,7,0]
    return [{'page':padded[index],'row':position//4,'column':position%4,'rotation':180 if position<4 else 0,'logical':index+1} for position,index in enumerate(order)]

def inset(value):
    try:value=float(value)
    except (TypeError,ValueError):raise ZineError('Enter a valid panel inset in millimeters.')
    if not math.isfinite(value) or not 0<=value<=12.7:raise ZineError('Panel inset must be 0–12.7 mm.')
    return value*72/25.4

def guides(c,width,height,cut=True):
    """Fold dashes, solid center slit; no outer trim is needed for this fold."""
    c.saveState();c.setStrokeColorRGB(.35,.35,.35);c.setLineWidth(.45);c.setDash(3,3)
    for fraction in (.25,.5,.75):c.line(width*fraction,0,width*fraction,height)
    c.line(0,height/2,width/4,height/2);c.line(width*3/4,height/2,width,height/2)
    if cut:c.setDash();c.setLineWidth(.8);c.line(width/4,height/2,width*3/4,height/2)
    c.restoreState()
