"""chat/web_tools.py — search formatting, HTML extraction, SSRF guard."""

import asyncio

import pytest

from chat import web_tools
from chat.web_tools import (
    MAX_PAGE_CHARS,
    _format_results,
    fetch_url,
    html_to_text,
    is_public_http_url,
    web_search,
)


def run(coro):
    return asyncio.run(coro)


def test_html_to_text_strips_chrome():
    markup = ('<html><head><title>t</title><style>.x{}</style></head><body>'
              '<script>evil()</script><h1>Title</h1><p>Para one.</p>'
              '<div>Para <b>two</b>.</div></body></html>')
    text = html_to_text(markup)
    assert 'Title' in text and 'Para one.' in text and 'Para two.' in text
    assert 'evil' not in text and '.x{}' not in text


def test_is_public_http_url():
    assert is_public_http_url('https://example.com/page')
    assert is_public_http_url('http://93.184.216.34/')
    assert not is_public_http_url('ftp://example.com')
    assert not is_public_http_url('http://localhost:53000/api/tasks')
    assert not is_public_http_url('http://127.0.0.1:8765/mcp')
    assert not is_public_http_url('http://10.0.0.5/')
    assert not is_public_http_url('http://192.168.1.1/')
    assert not is_public_http_url('http://169.254.169.254/latest/meta-data')
    assert not is_public_http_url('http://web.internal/')
    assert not is_public_http_url('not a url')


def test_fetch_url_refuses_private():
    result = run(fetch_url('http://127.0.0.1:53000/'))
    assert 'TOOL ERROR' in result


def test_format_results():
    formatted = _format_results([
        {'title': 'One', 'href': 'https://a.example', 'body': 'snippet a'},
        {'title': 'Two', 'href': 'https://b.example', 'body': 'snippet b'},
    ])
    assert '1. **One**' in formatted and 'https://b.example' in formatted
    assert _format_results([]) == 'No results.'


def test_web_search_uses_ddgs(monkeypatch):
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results=5):
            assert query == 'chainlit'
            return [{'title': 'Chainlit', 'href': 'https://chainlit.io',
                     'body': 'build chat apps'}][:max_results]

    import ddgs
    monkeypatch.setattr(ddgs, 'DDGS', FakeDDGS)
    result = run(web_search('chainlit', max_results=3))
    assert 'Chainlit' in result and 'https://chainlit.io' in result


def test_register_adds_both_tools():
    from chat.toolbox import Toolbox
    toolbox = Toolbox()
    web_tools.register(toolbox)
    assert {s['name'] for s in toolbox.specs()} == {'web_search', 'fetch_url'}
