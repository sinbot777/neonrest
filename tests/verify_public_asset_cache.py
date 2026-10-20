"""Test the public-artwork cache policy without opening any account database."""
import ast
from pathlib import Path
import tempfile
from flask import Flask, request

def main():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'app.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'protect_management_responses')
    fn.decorator_list = []
    names = next(ast.literal_eval(n.comparators[0]) for n in ast.walk(fn) if isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.In) and isinstance(n.comparators[0], ast.Tuple) and all(isinstance(x, ast.Constant) and str(x.value).startswith('optimized/') for x in n.comparators[0].elts))
    namespace = {'request': request}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'public-asset-policy', 'exec'), namespace)
    with tempfile.TemporaryDirectory(prefix='neonrest-public-assets-') as folder:
        app = Flask(__name__, static_folder=folder, static_url_path='/static')
        app.after_request(namespace['protect_management_responses'])
        @app.after_request
        def optional_cookie(response):
            if request.args.get('cookie') == '1':
                response.set_cookie('fixture', '1')
            return response
        @app.get('/manage')
        def manage():
            return 'private'
        for name in (*names, 'default-avatar.png', 'uploads/fixture.png'):
            path = Path(folder) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture asset')
        client = app.test_client()
        checks = 0
        for name in names:
            url = '/static/' + name
            response = client.get(url)
            assert response.status_code == 200
            assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable'
            etag = response.headers['ETag']
            response.close()
            for method in ('HEAD', 'GET'):
                response = client.open(url, method=method, headers={'If-None-Match': etag})
                assert response.status_code == 304
                assert 'immutable' in response.headers['Cache-Control']
                response.close()
            response = client.get(url + '?cookie=1')
            assert 'immutable' not in response.headers.get('Cache-Control', '')
            response.close()
            response = client.post(url)
            assert 'immutable' not in response.headers.get('Cache-Control', '')
            checks += 5
        for url in ('/static/default-avatar.png', '/static/uploads/fixture.png', '/static/optimized/missing.webp', '/manage'):
            response = client.get(url)
            assert 'immutable' not in response.headers.get('Cache-Control', '')
            if url == '/manage':
                assert response.headers['Cache-Control'] == 'no-store'
            response.close()
            checks += 1
        stats_tree = ast.parse((root / 'statistics_suite.py').read_text())
        clear = next(n for n in ast.walk(stats_tree) if isinstance(n, ast.FunctionDef) and n.name == 'clear')
        namespace['names'] = lambda: 'nr_analytics_'
        exec(compile(ast.Module(body=[clear], type_ignores=[]), 'analytics-cookie-cleanup', 'exec'), namespace)
        for cookies, expected in [('', 0), ('nr_analytics_choice=no', 0), ('nr_analytics_visitor=stale', 1), ('nr_analytics_visitor=stale; nr_analytics_session=stale', 2)]:
            with app.test_request_context('/', headers={'Cookie': cookies}):
                response = app.make_response('')
                namespace['clear'](response)
                assert len(response.headers.getlist('Set-Cookie')) == expected
                checks += 1
        print({'passed': True, 'checks': checks})

if __name__ == '__main__':
    main()
