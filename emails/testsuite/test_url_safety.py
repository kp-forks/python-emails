import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote, unquote

import pytest

import emails
import emails.utils
from emails.exc import HTTPLoaderError, UnsafeURLError
from emails.utils import fetch_url, default_url_validator, DEFAULT_REQUESTS_PARAMS


def _start_server():
    """HTTP server on 127.0.0.1 that records requested paths and headers."""
    requested = []
    headers = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            headers.append(dict(self.headers))
            if self.path.startswith('/redirect'):
                self.send_response(302)
                self.send_header('Location', '/secret')
                self.end_headers()
                return
            if self.path.startswith('/goto/'):
                self.send_response(302)
                self.send_header('Location', unquote(self.path.split('?')[0][len('/goto/'):]))
                self.end_headers()
                return
            body = b'body { color: red; }' if self.path.endswith('.css') else b'secret'
            self.send_response(200)
            self.send_header('Content-Type', 'text/css' if self.path.endswith('.css') else 'image/png')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.port = server.server_address[1]
    server.base = 'http://127.0.0.1:%s' % server.port
    server.requested = requested
    server.headers = headers
    return server


@pytest.fixture
def local_server():
    server = _start_server()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def other_server():
    server = _start_server()
    yield server
    server.shutdown()
    server.server_close()


def test_tls_verification_enabled_by_default():
    assert DEFAULT_REQUESTS_PARAMS['verify'] is True


@pytest.mark.parametrize('url', [
    'http://127.0.0.1/',
    'http://localhost/',
    'http://10.0.0.1/',
    'http://192.168.1.1/',
    'http://172.16.0.1/',
    'http://169.254.169.254/latest/meta-data/',
    'http://[::1]/',
    'http://0.0.0.0/',
    'http://2130706433/',
    'http://[::ffff:127.0.0.1]/',
    'http://[fec0::1]/',                          # deprecated site-local
    'http://[64:ff9b::7f00:1]/',                  # NAT64 -> 127.0.0.1
    'http://[64:ff9b::a00:1]/',                   # NAT64 -> 10.0.0.1
    'http://[2002:7f00:1::1]/',                   # 6to4 -> 127.0.0.1
    'http://[2001:4860:4860::8888%25en0]/',       # zone id
    'file:///etc/passwd',
    'ftp://example.com/',
])
def test_default_validator_rejects_unsafe_urls(url):
    with pytest.raises(UnsafeURLError):
        default_url_validator(url)


@pytest.mark.parametrize('url', [
    'http://8.8.8.8/',
    'https://[2001:4860:4860::8888]/',
    'http://[64:ff9b::808:808]/',                 # NAT64 -> 8.8.8.8
])
def test_default_validator_allows_public_addresses(url):
    default_url_validator(url)


def test_unsafe_url_error_is_http_loader_error():
    assert issubclass(UnsafeURLError, HTTPLoaderError)


def test_fetch_url_blocks_private_host(local_server):
    with pytest.raises(UnsafeURLError):
        fetch_url(local_server.base + '/secret')
    assert local_server.requested == []


def test_fetch_url_validates_redirect_targets(local_server, monkeypatch):
    # Allow only the first hop; the redirect target must be validated again.
    def validator(url):
        if not url.startswith(local_server.base + '/redirect'):
            raise UnsafeURLError(url)

    monkeypatch.setattr(emails.utils, 'url_validator', validator)
    with pytest.raises(UnsafeURLError):
        fetch_url(local_server.base + '/redirect')
    assert local_server.requested == ['/redirect']


def test_fetch_url_follows_allowed_redirects(local_server, monkeypatch):
    monkeypatch.setattr(emails.utils, 'url_validator', None)
    r = fetch_url(local_server.base + '/redirect')
    assert r.content == b'secret'
    assert local_server.requested == ['/redirect', '/secret']


def test_fetch_url_respects_allow_redirects_false(local_server, monkeypatch):
    monkeypatch.setattr(emails.utils, 'url_validator', None)
    r = fetch_url(local_server.base + '/redirect', valid_http_codes=(302, ),
                  requests_args={'allow_redirects': False})
    assert r.status_code == 302
    assert local_server.requested == ['/redirect']


def test_transform_does_not_fetch_private_css(local_server):
    html = '<html><head><link rel="stylesheet" href="%s/x.css"></head><body>x</body></html>' % local_server.base
    m = emails.html(html=html, mail_from='a@b.com', subject='s')
    with pytest.raises(UnsafeURLError):
        m.transform()
    assert local_server.requested == []


def test_transform_does_not_fetch_private_images(local_server):
    html = '<html><body><img src="%s/x.png"></body></html>' % local_server.base
    m = emails.html(html=html, mail_from='a@b.com', subject='s')
    with pytest.raises(UnsafeURLError):
        m.transform(images_inline=True)
        m.as_string()
    assert local_server.requested == []


def test_transform_fetches_private_css_when_validator_disabled(local_server, monkeypatch):
    monkeypatch.setattr(emails.utils, 'url_validator', None)
    html = '<html><head><link rel="stylesheet" href="%s/x.css"></head><body><p>x</p></body></html>' % local_server.base
    m = emails.html(html=html, mail_from='a@b.com', subject='s')
    m.transform()
    assert local_server.requested == ['/x.css']
    assert 'color:red' in m.html.replace(' ', '')


def test_fetch_url_blocks_backslash_authority(local_server):
    # urlparse sees host 8.8.8.8, but requests/urllib3 connect to 127.0.0.1
    with pytest.raises(UnsafeURLError):
        fetch_url('http://127.0.0.1:%s\\@8.8.8.8/secret' % local_server.port)
    assert local_server.requested == []


def test_transform_does_not_fetch_private_css_import(local_server):
    html = ('<html><head><style>@import url("%s/x.css"); p { color: blue }</style></head>'
            '<body><p>x</p></body></html>' % local_server.base)
    m = emails.html(html=html, mail_from='a@b.com', subject='s')
    m.transform()
    assert local_server.requested == []
    assert 'color:blue' in m.html.replace(' ', '')


def test_redirect_to_other_host_drops_credentials(local_server, other_server, monkeypatch):
    monkeypatch.setattr(emails.utils, 'url_validator', None)
    # 127.0.0.1 -> localhost is a different host for requests
    target = 'http://localhost:%s/secret' % other_server.port
    fetch_url(local_server.base + '/goto/' + quote(target, safe=''),
              requests_args={'headers': {'Authorization': 'Basic dXNlcjpwYXNz', 'Cookie': 'sid=1'},
                             'params': {'token': 'secret'}})
    assert other_server.requested == ['/secret']
    sent = {k.lower(): v for k, v in other_server.headers[0].items()}
    assert 'authorization' not in sent
    assert 'cookie' not in sent
