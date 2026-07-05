"""Same-origin hermes-webui proxy (/hermes-ui/*) — routes/hermes_proxy.py.

The upstream is stubbed at the `requests.request` seam, so these verify the
proxy's own contract: auth gating, header hygiene (X-Frame-Options stripped,
frame-ancestors removed, hop-by-hop dropped), Location rewriting, body
passthrough, and clean 404/502 degradation.
"""

import pytest

import routes.hermes_proxy as proxy_mod
from conftest import login

UPSTREAM = 'http://hermes-webui:8787'


class StubUpstream:
    """Minimal requests.Response stand-in for the streaming proxy path."""

    def __init__(self, status_code=200, headers=None, body=b'hello from webui'):
        self.status_code = status_code
        self.headers = headers or {'Content-Type': 'text/html'}
        self._body = body

    def iter_content(self, chunk_size=8192):
        yield self._body


@pytest.fixture
def proxied(app, monkeypatch):
    """Enable the proxy and capture outgoing upstream calls."""
    app.config['HERMES_WEBUI_INTERNAL_URL'] = UPSTREAM
    calls = {}

    def fake_request(method, url, **kwargs):
        calls['method'] = method
        calls['url'] = url
        calls['kwargs'] = kwargs
        return calls.pop('response', None) or StubUpstream()

    monkeypatch.setattr(proxy_mod.requests, 'request', fake_request)
    return calls


def test_requires_authentication(client, app):
    app.config['HERMES_WEBUI_INTERNAL_URL'] = UPSTREAM
    resp = client.get('/hermes-ui/')
    assert resp.status_code == 401


def test_404_when_not_configured(client, app):
    app.config['HERMES_WEBUI_INTERNAL_URL'] = None
    login(client)
    resp = client.get('/hermes-ui/')
    assert resp.status_code == 404


def test_forwards_and_streams_body(client, proxied):
    login(client)
    resp = client.get('/hermes-ui/static/app.js?v=1')
    assert resp.status_code == 200
    assert resp.data == b'hello from webui'
    assert proxied['method'] == 'GET'
    assert proxied['url'] == f'{UPSTREAM}/static/app.js'
    assert proxied['kwargs']['params'] == b'v=1'


def test_root_path_proxies_upstream_root(client, proxied):
    login(client)
    client.get('/hermes-ui/')
    assert proxied['url'] == f'{UPSTREAM}/'


def test_strips_frame_headers_keeps_rest_of_csp(client, proxied):
    proxied['response'] = StubUpstream(headers={
        'Content-Type': 'text/html',
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'",
        'X-Content-Type-Options': 'nosniff',
        'Transfer-Encoding': 'chunked',
    })
    login(client)
    resp = client.get('/hermes-ui/')
    assert 'X-Frame-Options' not in resp.headers
    assert resp.headers['Content-Security-Policy'] == "default-src 'self'"
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'


def test_drops_csp_that_was_only_frame_ancestors(client, proxied):
    proxied['response'] = StubUpstream(headers={
        'Content-Type': 'text/html',
        'Content-Security-Policy': "frame-ancestors 'none'",
    })
    login(client)
    resp = client.get('/hermes-ui/')
    assert 'Content-Security-Policy' not in resp.headers


def test_rewrites_redirects_under_the_prefix(client, proxied):
    # root-absolute upstream redirect
    proxied['response'] = StubUpstream(status_code=302,
                                       headers={'Location': '/login'})
    login(client)
    resp = client.get('/hermes-ui/private')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/hermes-ui/login'
    resp.close()  # release the streamed body's preserved request context

    # absolute redirect to the upstream itself
    proxied['response'] = StubUpstream(status_code=302,
                                       headers={'Location': f'{UPSTREAM}/session/new'})
    resp = client.get('/hermes-ui/other')
    assert resp.headers['Location'] == '/hermes-ui/session/new'


def test_post_body_and_502_on_upstream_down(client, proxied, monkeypatch):
    login(client)
    client.post('/hermes-ui/api/chat', data=b'{"q":1}',
                content_type='application/json')
    assert proxied['method'] == 'POST'
    assert proxied['kwargs']['data'] == b'{"q":1}'

    def boom(*a, **k):
        raise proxy_mod.requests.ConnectionError('down')
    monkeypatch.setattr(proxy_mod.requests, 'request', boom)
    resp = client.get('/hermes-ui/')
    assert resp.status_code == 502


def test_index_embeds_proxy_src_when_internal_url_set(client, app):
    app.config['HERMES_WEBUI_INTERNAL_URL'] = UPSTREAM
    app.config['HERMES_WEBUI_URL'] = 'https://ignored.example.com'
    login(client)
    page = client.get('/').data.decode()
    assert 'data-src="/hermes-ui/"' in page


def test_index_hides_tab_when_nothing_configured(client, app):
    app.config['HERMES_WEBUI_INTERNAL_URL'] = None
    app.config['HERMES_WEBUI_URL'] = None
    login(client)
    page = client.get('/').data.decode()
    assert 'view-hermes' not in page
