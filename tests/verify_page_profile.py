"""Page presentation, migrations, upload decoding and visibility boundaries."""
import io
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from verify_identity_page_routes import RouteTests, pages
from page_fixture import page_profile as profile


class ProfileTests(RouteTests):
    def appearance(self, **values):
        data = dict(action='profile', revision=pages.get(self.db, self.page)['revision'],
                    tagline='Small buttons. Big opinions.', website='https://example.com/shop', accent='rose')
        data.update(values)
        return self.post('/pages/' + self.page + '/edit', **data)

    def test_appearance_persists_without_changing_owner_or_description(self):
        self.assertEqual(self.appearance().status_code, 302)
        page = pages.get(self.db, self.page)
        self.assertEqual((page['tagline'],page['website'],page['accent']),
                         ('Small buttons. Big opinions.','https://example.com/shop','rose'))
        self.assertEqual((page['name'],page['description'],page['owner_id'],page['state']),
                         ('Example','Description',1,'draft'))

    def test_framing_round_trip_preserves_master_and_other_page_content(self):
        import json
        frame=dict(mode='portrait',shape='circle',zoom=2.3,x=25,y=60,padding=0,background='#123456',trim=False)
        response=self.appearance(avatar_frame=json.dumps(frame),cover_frame=json.dumps(dict(zoom=1.5,x=20,y=80)))
        self.assertEqual(response.status_code,302)
        page=pages.get(self.db,self.page)
        self.assertEqual(json.loads(page['avatar_frame']),frame)
        self.assertEqual(json.loads(page['cover_frame'])['zoom'],1.5)
        self.assertEqual(page['description'],'Description')
        self.assertEqual(page['avatar_file'],'')

    def test_invalid_framing_never_persists(self):
        import json
        for frame in ({'zoom':True},{'zoom':0},{'x':-1},{'y':101},{'padding':25},
                      {'zoom':float('nan')},{'background':'red;display:none'},
                      {'shape':'triangle'},{'trim':'yes'},{'unknown':'anything'}):
            self.assertEqual(self.appearance(avatar_frame=json.dumps(frame)).status_code,400)
        self.assertEqual(self.appearance(avatar_frame='[1,2,3]').status_code,400)
        self.assertEqual(self.appearance(avatar_frame='{bad json').status_code,400)
        self.assertEqual(pages.get(self.db,self.page)['revision'],0)

    def test_logo_trims_display_only_and_can_restore_full_source(self):
        import json
        name='b'*48+'.png'
        with tempfile.TemporaryDirectory() as root,patch.object(self.app,'root_path',root):
            folder=profile.artwork_folder(self.app);folder.mkdir(parents=True)
            picture=Image.new('RGBA',(80,120),(0,0,0,0))
            picture.paste((255,0,0,255),(10,15,70,75));picture.save(folder/name)
            original=(folder/name).read_bytes()
            self.db.execute('UPDATE identity_pages SET avatar_file=? WHERE id=?',(name,self.page));self.db.commit()
            url='/pages/'+self.page+'/artwork/avatar/'+name
            with self.client.get(url+'?framed=1') as response:
                self.assertEqual(response.status_code,200)
                self.assertEqual(Image.open(io.BytesIO(response.data)).size,(60,60))
            with self.client.get(url) as response:self.assertEqual(response.data,original)
            self.assertEqual((folder/name).read_bytes(),original)
            self.appearance(avatar_frame=json.dumps(dict(mode='logo',trim=False)))
            with self.client.get(url+'?framed=1') as response:
                self.assertEqual(Image.open(io.BytesIO(response.data)).size,(80,120))
            self.login(2)
            self.assertEqual(self.client.get(url+'?framed=1').status_code,404)

    def test_editor_exposes_framing_preview_reset_and_cancel(self):
        response=self.client.get('/pages/'+self.page+'/edit')
        self.assertEqual(response.status_code,200)
        for text in (b'Artwork framing',b'Logo',b'Portrait',b'Trim transparent',b'Mobile',b'data-art-reset',b'Cancel changes',b'page_artwork_editor.js'):
            self.assertIn(text,response.data)

    def test_stale_profile_and_untrusted_url_are_rejected(self):
        for website in ('javascript:alert(1)','//example.com','https://user:pass@example.com','https://example.com\\evil','https://example.com\n/secret'):
            self.assertEqual(self.appearance(website=website).status_code, 400)
        self.assertEqual(self.appearance(accent='red;display:none').status_code, 400)
        self.assertEqual(self.appearance(tagline='x'*161).status_code, 400)
        self.assertEqual(self.appearance(revision=500).status_code, 409)

    def test_profile_cannot_be_changed_by_nonmember_or_without_csrf(self):
        self.login(2)
        self.assertIn(self.appearance().status_code, (403,404))
        self.login(1)
        self.assertEqual(self.client.post('/pages/'+self.page+'/edit', data={'action':'profile','revision':0}).status_code,400)

    def test_repeated_migration_preserves_rows_and_appearance(self):
        self.appearance()
        before=dict(pages.get(self.db,self.page))
        pages.initialize(self.db);pages.initialize(self.db)
        self.assertEqual(dict(pages.get(self.db,self.page)),before)

    def test_rendered_layout_escapes_profile_text_and_website(self):
        self.appearance(tagline='<script>alert(1)</script>')
        with self.db:pages.set_state(self.db,1,self.page,1,'published')
        response=self.client.get('/_example')
        self.assertEqual(response.status_code,200)
        for text in (b'page-profile-layout',b'id="page-about"',b'Visit website',b'page-accent-rose',b'&lt;script&gt;'):
            self.assertIn(text,response.data)
        self.assertNotIn(b'<script>alert',response.data)

    def test_artwork_is_private_until_published_and_old_files_are_unreachable(self):
        name='a'*48+'.png'
        with tempfile.TemporaryDirectory() as root, patch.object(self.app,'root_path',root):
            folder=profile.artwork_folder(self.app);folder.mkdir(parents=True)
            (folder/name).write_bytes(b'fixture-image')
            self.db.execute('UPDATE identity_pages SET avatar_file=? WHERE id=?',(name,self.page));self.db.commit()
            url='/pages/'+self.page+'/artwork/avatar/'+name
            self.login(2);self.assertEqual(self.client.get(url).status_code,404)
            self.login(1)
            with self.client.get(url) as response:self.assertEqual(response.status_code,200)
            with self.db:pages.set_state(self.db,1,self.page,0,'published')
            self.login(2)
            with self.client.get(url) as response:self.assertEqual(response.status_code,200)
            self.db.execute('INSERT INTO user_blocks VALUES (1,2)');self.db.commit()
            self.assertEqual(self.client.get(url).status_code,404)
            self.login(1)
            self.db.execute("UPDATE identity_pages SET avatar_file='' WHERE id=?",(self.page,));self.db.commit()
            self.assertEqual(self.client.get(url).status_code,404)

    def test_image_decoder_bounds_size_strips_metadata_and_resizes(self):
        class Upload:
            def __init__(self,data):self.stream=io.BytesIO(data)
        raw=io.BytesIO();Image.new('RGB',(1000,800)).save(raw,format='PNG')
        picture=profile.prepare_picture(Upload(raw.getvalue()),'avatar')
        self.assertEqual(picture.size,(512,410));self.assertEqual(picture.mode,'RGBA')
        for value in (b'not an image',b'x'*(1800*1024+1)):
            with self.assertRaises(ValueError):profile.prepare_picture(Upload(value),'avatar')

    def test_actual_upload_round_trip_uses_private_storage_and_protected_route(self):
        raw=io.BytesIO();Image.new('RGB',(40,30),(40,120,160)).save(raw,format='PNG');raw.seek(0)
        with tempfile.TemporaryDirectory() as root,patch.object(self.app,'root_path',root):
            response=self.appearance(avatar=(raw,'portrait.png'))
            self.assertEqual(response.status_code,302)
            name=pages.get(self.db,self.page)['avatar_file']
            self.assertRegex(name,r'^[a-f0-9]{48}\.png$')
            folder=profile.artwork_folder(self.app)
            self.assertEqual(folder.stat().st_mode&0o777,0o700)
            with self.client.get('/pages/'+self.page+'/artwork/avatar/'+name) as result:
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.mimetype,'image/png')
                self.assertTrue(result.data.startswith(b'\x89PNG'))


if __name__=='__main__':unittest.main()
