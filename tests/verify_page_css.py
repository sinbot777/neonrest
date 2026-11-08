from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))
from verify_identity_page_routes import RouteTests, pages
from page_fixture import page_css


class CssTests(RouteTests):
    def csspost(self, **changes):
        data=dict(action='save',custom_css='.page-profile { color: hotpink; }',revision=str(pages.get(self.db,self.page)['revision']))
        data.update(changes)
        return self.post('/pages/'+self.page+'/style',**data)

    def test_editor_and_save_scope_and_export(self):
        response=self.client.get('/pages/'+self.page+'/style')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Preview CSS',response.data)
        self.assertEqual(self.csspost().status_code,302)
        self.assertIn(b'.identity-page.page-profile{ color: hotpink; }',self.client.get('/_example').data)
        self.assertIn('hotpink',str(pages.export_user(self.db,1)))

    def test_preview_is_private_and_does_not_save(self):
        response=self.csspost(action='preview')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Unsaved CSS preview',response.data)
        self.assertIn(b'hotpink',response.data)
        self.assertEqual(pages.get(self.db,self.page)['custom_css'],'')
        self.assertEqual(pages.get(self.db,self.page)['revision'],0)
        self.login(2)
        self.assertEqual(self.csspost(action='preview').status_code,403)

    def test_reset_and_stale_and_csrf(self):
        self.csspost()
        self.assertEqual(self.csspost(revision='0').status_code,400)
        self.assertEqual(self.client.post('/pages/'+self.page+'/style',data={'action':'reset','revision':'1'}).status_code,400)
        self.assertEqual(self.csspost(action='reset').status_code,302)
        self.assertEqual(pages.get(self.db,self.page)['custom_css'],'')

    def test_hostile_css_cannot_escape_style_or_scope(self):
        for css in ('</style><script>alert(1)</script>','} body{display:none} {','@import "//evil.test";',
                    '.x{background:u/**/rl(//evil.test)}','.x{background:image("//evil.test")}',
                    '.x{color:red','/* unfinished','@font-face{font-family:x}', '.x{content:"broken}',
                    '.x{background:\\75rl(x)}','a{}'*151):
            with self.subTest(css=css):
                self.assertEqual(self.csspost(custom_css=css).status_code,400)
        self.assertEqual(pages.get(self.db,self.page)['custom_css'],'')

    def test_media_comments_and_quotes_are_supported(self):
        value='/* local */ @media(max-width:700px){.page-profile{color:red}.page-profile h2::after{content:"{}"}}'
        self.assertEqual(page_css.validate(value),value)
        self.assertEqual(self.csspost(custom_css=value).status_code,302)
        self.assertEqual(pages.get(self.db,self.page)['custom_css'],value)

    def test_selector_compilation_cannot_reach_navigation(self):
        css='body{display:none}.page-profile h2, .page-product-card{color:red}@media(max-width:700px){.page-profile{color:blue}}'
        result=page_css.scoped(css)
        self.assertIn('.identity-page.page-profile body{',result)
        self.assertIn('.identity-page.page-profile h2, .identity-page.page-profile .page-product-card{',result)
        self.assertIn('@media(max-width:700px){.identity-page.page-profile{',result)
        for value in ('.page-profile + nav{display:none}', '.page-profile ~ *{display:none}', '.x{& .y{color:red}}', '.x; color:red'):
            with self.subTest(value=value),self.assertRaises(ValueError):page_css.scoped(value)

    def test_missing_login_expired_confirmation_and_archived(self):
        self.login(None)
        self.assertEqual(self.client.get('/pages/'+self.page+'/style').status_code,401)
        self.login(1);self.fresh=False
        self.assertEqual(self.csspost().status_code,302)
        self.assertIn('hotpink',pages.get(self.db,self.page)['custom_css'])
        self.fresh=True
        pages.set_state(self.db,1,self.page,1,'archived');self.db.commit()
        self.assertEqual(self.csspost().status_code,409)

    def test_routine_page_edits_do_not_require_repeat_confirmation(self):
        self.fresh=False
        response=self.post('/pages/'+self.page+'/edit',action='edit',revision='0',name='Edited without repeat confirmation',description='Fixture')
        self.assertEqual(response.status_code,302)
        self.assertNotIn('/reauth',response.location)
        response=self.post('/pages/'+self.page+'/edit',action='profile',revision='1',tagline='Updated',website='',accent='teal')
        self.assertEqual(response.status_code,302)
        self.assertNotIn('/reauth',response.location)
        response=self.post('/pages/'+self.page+'/edit',action='state',revision='2',state='published')
        self.assertIn('/reauth',response.location)
        self.assertEqual(pages.get(self.db,self.page)['state'],'draft')

if __name__=='__main__':unittest.main()
