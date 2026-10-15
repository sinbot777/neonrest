import sqlite3
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vibe_gallery import build_vibe_gallery

class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE post_media(post_id INTEGER,kind TEXT,filename TEXT,poster TEXT,alt_text TEXT,title TEXT)')
        self.posts=[dict(id=1,handle='Preview',content=''),dict(id=2,handle='OtherPreview',content='![old](/static/old.png)')]
    def add(self,pid,kind='image',filename='image.webp',poster=None,alt='Uploaded image',title=''):
        self.db.execute('INSERT INTO post_media VALUES (?,?,?,?,?,?)',(pid,kind,filename,poster,alt,title))
    def gallery(self,posts=None,limit=8):
        return build_vibe_gallery(self.db,self.posts if posts is None else posts,lambda f:'/sandbox/media-file/'+f,lambda f:'/sandbox/static/'+f,limit)
    def test_uploaded_and_legacy_images(self):
        self.add(1);items=self.gallery();self.assertEqual([i['url'] for i in items],['/sandbox/media-file/image.webp','/sandbox/static/old.png']);self.assertEqual(items[0]['alt'],'Uploaded image')
    def test_only_visible_input_posts(self):
        self.add(999,filename='hidden.webp');self.add(1);self.assertNotIn('hidden.webp',str(self.gallery()));self.assertEqual(self.gallery([]),[])
    def test_gif_uses_still_poster_and_excludes_midi(self):
        self.add(1,'gif','animate.gif','poster.jpg');self.add(2,'midi','music.mid');items=self.gallery();self.assertEqual(items[0]['url'],'/sandbox/media-file/poster.jpg');self.assertNotIn('animate.gif',str(items));self.assertNotIn('music.mid',str(items))
    def test_gif_without_poster_does_not_autoplay(self):
        self.add(1,'gif','animate.gif');self.assertEqual(len(self.gallery()),1)
    def test_limit_deduplication_and_order(self):
        self.posts[0]['content']=' '.join('![x](https://example.invalid/'+str(i)+'.png)' for i in range(12));items=self.gallery(limit=3);self.assertEqual(len(items),3);self.assertTrue(items[-1]['url'].endswith('/2.png'))
        self.posts[0]['content']='![x](/static/same.png) ![x](/static/same.png)';self.assertEqual(len(self.gallery()),2)
    def test_alt_falls_back_to_title(self):
        self.add(1,alt='',title='Carousel');self.assertEqual(self.gallery()[0]['alt'],'Carousel')

if __name__=='__main__':unittest.main()
