"""Run against an isolated account copy using the existing fixture harness.
Usage: python tests/verify_async_music.py neonrest_sandbox /path/to/package
"""
from pathlib import Path
import sys
fixture=Path(sys.argv[2])/'tests/verify_statistics_suite.py'
prefix=fixture.read_text().split("with sqlite3.connect(path) as db:db.execute('INSERT INTO counters")[0]
exec(compile(prefix,str(fixture),'exec'),globals())
change('UPDATE users SET lastfm_username=? WHERE id=?',('fictional-lagging-music',users['Owner']))
calls=[]
def stalled_music(username):
    calls.append(username)
    raise RuntimeError('External service must not run during profile rendering')
core.get_now_playing=stalled_music
r=get('Owner','/@VMFixtureOwner')
check(r.status_code==200,'Profile renders while external music is unavailable')
check(calls==[],'Profile makes no blocking music call')
check((mount+'/now_playing/fictional-lagging-music').encode() in r.data,'Music endpoint retains mount')
check(b'profile_now_playing.js' in r.data and b'Loading music' in r.data,'Separate loading state and deferred script')
change('UPDATE users SET lastfm_username=? WHERE id=?',('',users['Owner']))
r=get('Owner','/@VMFixtureOwner')
check(b'data-now-playing-url=' not in r.data and b'profile_now_playing.js' not in r.data,'No request without visible music account')
check(app.config['RETENTION_ENABLED'] is False,'Erasure remains disabled')
print(json.dumps(dict(package=package,checks=checks,passed=True)))
