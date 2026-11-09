from pathlib import Path
import itertools
import json
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
from verify_identity_page_routes import RouteTests,pages
from page_fixture import page_layout, page_products


class LayoutTests(RouteTests):
    def save_layout(self,**changes):
        values=dict(action='layout',revision=str(pages.get(self.db,self.page)['revision']),layout_main='updates',layout_secondary='sidebar',layout_details='left')
        values.update(changes)
        return self.post('/pages/'+self.page+'/edit',**values)

    def test_products_default_off_and_no_catalog_query(self):
        with patch.object(page_products,'browse',side_effect=AssertionError('Opt-out must not query products')):
            response=self.client.get('/_example')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'id="page-updates"',response.data)
        self.assertNotIn(b'id="page-products"',response.data)
        self.assertNotIn(b'Products will appear here',response.data)
        self.assertFalse(page_layout.read(pages.get(self.db,self.page))['products_enabled'])

    def test_each_supported_layout_renders_without_duplicate_or_missing_panels(self):
        for enabled,main,secondary,details in itertools.product((True,False),('products','updates'),('sidebar','below','hidden'),('left','right','hidden')):
            with self.subTest(enabled=enabled,main=main,secondary=secondary,details=details):
                value=dict(products_enabled=enabled,main=main,secondary=secondary,details=details)
                self.db.execute('UPDATE identity_pages SET layout_settings=? WHERE id=?',(json.dumps(value),self.page));self.db.commit()
                response=self.client.get('/_example')
                self.assertEqual(response.status_code,200)
                layout=page_layout.presentation(pages.get(self.db,self.page))
                self.assertEqual(response.data.count(b'id="page-products"'),int(layout['show_products']))
                self.assertEqual(response.data.count(b'id="page-updates"'),int(layout['show_updates']))
                self.assertEqual(response.data.count(b'id="page-details"'),int(layout['show_details']))
                self.assertEqual(len({p['kind'] for p in layout['panels']}),len(layout['panels']))

    def test_save_and_opt_out_preserve_other_content(self):
        self.fresh=False
        response=self.save_layout(products_enabled='1',layout_main='products',layout_secondary='below',layout_details='right')
        self.assertEqual(response.status_code,302);self.assertNotIn('/reauth',response.location)
        page=pages.get(self.db,self.page)
        self.assertEqual(page_layout.read(page),dict(products_enabled=True,main='products',secondary='below',details='right'))
        self.assertEqual((page['description'],page['owner_id'],page['state']),('Description',1,'draft'))
        self.assertIn('layout_settings',pages.export_user(self.db,1)['owned_pages'][0])
        self.assertEqual(self.save_layout().status_code,302)
        self.assertNotIn(b'id="page-products"',self.client.get('/_example').data)

    def test_foreign_user_csrf_and_stale_revision_cannot_change_layout(self):
        self.assertEqual(self.save_layout(revision='999',products_enabled='1').status_code,409)
        self.assertEqual(self.client.post('/pages/'+self.page+'/edit',data=dict(action='layout',revision='0')).status_code,400)
        self.login(2);self.assertEqual(self.save_layout(products_enabled='1').status_code,403)
        self.assertFalse(page_layout.read(pages.get(self.db,self.page))['products_enabled'])

    def test_untrusted_values_are_rejected_and_corrupt_storage_falls_back(self):
        for values in ({'layout_main':'<script>'},{'layout_secondary':'url(evil)'},{'layout_details':'up'},{'products_enabled':'true'}):
            self.assertEqual(self.save_layout(**values).status_code,400)
        self.db.execute("UPDATE identity_pages SET layout_settings='bad json' WHERE id=?",(self.page,))
        self.assertEqual(page_layout.read(pages.get(self.db,self.page)),page_layout.DEFAULTS)
        self.assertEqual(self.client.get('/_example').status_code,200)

    def test_hidden_updates_are_not_rendered_and_links_keep_sandbox_mount(self):
        self.save_layout(products_enabled='1',layout_main='products',layout_secondary='hidden',layout_details='hidden')
        response=self.client.get('/_example',environ_overrides={'SCRIPT_NAME':'/sandbox'})
        self.assertNotIn(b'id="page-updates"',response.data)
        self.assertNotIn(b'id="page-details"',response.data)
        self.assertIn(b'href="/sandbox/marketplace"',response.data)
        self.assertIn(b'href="/sandbox/pages/',response.data)

    def test_migration_is_repeatable_and_archived_page_stays_unchanged(self):
        self.save_layout(products_enabled='1')
        before=dict(pages.get(self.db,self.page));pages.initialize(self.db);pages.initialize(self.db)
        self.assertEqual(dict(pages.get(self.db,self.page)),before)
        pages.set_state(self.db,1,self.page,1,'archived');self.db.commit()
        self.assertEqual(self.save_layout().status_code,409)

if __name__=='__main__':unittest.main()
