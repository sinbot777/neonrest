"""Exercise actual image processing in a temporary instance, without app/DB startup."""
import importlib,io,sys,tempfile,types
import qrcode
from pathlib import Path
from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException
stage=Path(sys.argv[1]);package=types.ModuleType('pillow_security_fixture');package.__path__=[str(stage)];sys.modules[package.__name__]=package
media=importlib.import_module(package.__name__+'.media_features')
checks=0
def check(condition,label):
    global checks
    assert condition,label
    checks+=1
with tempfile.TemporaryDirectory(prefix='neonrest-pillow13-') as temp:
    app=Flask('pillow-security',instance_path=str(Path(temp)/'instance'))
    with app.app_context():
        qr=io.BytesIO();qrcode.make('fictional-authenticator-fixture').save(qr,format='PNG');qr.seek(0)
        with Image.open(qr) as processed:processed.load();check(processed.format=='PNG','Authenticator QR generation compatible')
        for format,mode,size in [('JPEG','RGB',(2400,2200)),('PNG','RGBA',(32,24)),('WEBP','RGB',(32,24))]:
            image=Image.new(mode,size,(40,80,120,128) if mode=='RGBA' else (40,80,120));buffer=io.BytesIO();image.save(buffer,format);buffer.seek(0)
            result=media._save_image(FileStorage(stream=buffer,filename='fictional.'+format.lower()),'Fixture','original','Fixture title')
            check(result['kind']=='image' and result['title']=='Fixture title',format+' metadata')
            path=media.media_folder()/result['filename']
            with Image.open(path) as processed:
                processed.load();check(processed.format=='WEBP' and max(processed.size)<=2200,format+' processed and bounded')
                if mode=='RGBA':check(processed.mode=='RGBA','PNG alpha retained')
        frames=[Image.new('RGB',(40,30),color) for color in ['red','blue']];buffer=io.BytesIO()
        frames[0].save(buffer,'GIF',save_all=True,append_images=frames[1:],duration=[100,150],loop=0);buffer.seek(0)
        result=media._save_image(FileStorage(stream=buffer,filename='fictional.gif'),'Fixture GIF','original','')
        check(result['kind']=='gif','Animated GIF recognized')
        for key,format in [('filename','GIF'),('loop_filename','GIF'),('poster','JPEG')]:
            with Image.open(media.media_folder()/result[key]) as processed:processed.load();check(processed.format==format,key+' readable')
        with Image.open(media.media_folder()/result['loop_filename']) as processed:check(processed.n_frames==2 and processed.info.get('loop')==0,'GIF looping and frames retained')
        original_files=set(media.media_folder().iterdir())
        tiff=io.BytesIO();Image.new('RGB',(4,4),'white').save(tiff,'TIFF');tiff.seek(0)
        for stream in [tiff,io.BytesIO(b'not an image')]:
            try:media._save_image(FileStorage(stream=stream,filename='disguised.jpg'),'Fixture','original','')
            except HTTPException as error:check(error.code==400,'Invalid/disallowed input rejected')
            else:raise AssertionError('Invalid input accepted')
        check(set(media.media_folder().iterdir())==original_files,'Rejected inputs leave no files')
print('PILLOW MEDIA PASS',Image.__version__,checks,'checks; actual JPEG/PNG/WebP/GIF pipeline; temporary media only')
