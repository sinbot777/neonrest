"""Case-insensitive Vibe routes and display names; disposable DB only."""
from pathlib import Path
import sys
stage=Path(sys.argv[2])
exec(compile((stage/'tests/verify_onboarding_discovery.py').read_text(),
             'onboarding_discovery_regression','exec'))
for raw, expected in [('nostalgia','Nostalgia'),('iPhone Fans','IPhone Fans'),
                      ('NASA','NASA'),('...retro','...Retro'),
                      ('époque','Époque'),('',''),('123','123')]:
    check(life.capitalized_vibe_name(raw)==expected,'First letter only '+raw)
vcase=tag('Writer','case Fixture keepCAPS')
check(query('SELECT name FROM vibes WHERE id=?',(vcase,))[0][0]=='Case Fixture keepCAPS',
      'Creation capitalizes first letter and preserves remainder')
check(tag('Regular','CASE FIXTURE KEEPCAPS')==vcase,'Uppercase tag reuses ID')
check(tag('Manager','case fixture keepcaps')==vcase,'Lowercase tag reuses ID')
for spelling in ['Case Fixture keepCAPS','case fixture keepcaps','CASE FIXTURE KEEPCAPS']:
    response=get('Regular','/vibe/'+spelling,mode='night')
    check(response.status_code==200,'Case-insensitive Vibe route '+spelling)
    check(b'Case Fixture keepCAPS' in response.data,'Canonical display '+spelling)
check(life.vibe_slug('Case Fixture keepCAPS')==life.vibe_slug('case fixture keepcaps'),
      'Theme slug unchanged by capitalization')
print('VIBE CASE CHECKS',checks)

