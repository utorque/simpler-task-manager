"""Native web tools: search (DDGS, no API key) + fetch-and-read.

Registered on every turn's toolbox unless CHAT_WEB_TOOLS=0. fetch_url keeps
a deliberately blunt SSRF guard — the assistant runs next to the app's
loopback API, so anything private-looking is refused (workspace access goes
through the Simpler MCP tools, never through raw HTTP).
"""

import asyncio
import html
import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

MAX_PAGE_CHARS = 20_000

SEARCH_SCHEMA = {
    'type': 'object',
    'properties': {
        'query': {'type': 'string', 'description': 'The search query'},
        'max_results': {'type': 'integer', 'description': 'How many results (default 5, max 10)'},
    },
    'required': ['query'],
}

FETCH_SCHEMA = {
    'type': 'object',
    'properties': {
        'url': {'type': 'string', 'description': 'The http(s) URL to fetch'},
    },
    'required': ['url'],
}


# ===== HTML -> text ===========================================================

class _TextExtractor(HTMLParser):
    _SKIP = {'script', 'style', 'noscript', 'template', 'svg', 'head'}
    _BREAKERS = {'p', 'div', 'br', 'li', 'tr', 'section', 'article',
                 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAKERS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAKERS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(markup)
    except Exception:
        return html.unescape(re.sub(r'<[^>]+>', ' ', markup))
    text = ''.join(extractor.parts)
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n\s*\n+', '\n\n', text).strip()


# ===== SSRF guard =============================================================

def is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ('localhost',) or host.endswith('.local') or host.endswith('.internal'):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a public-looking DNS name


# ===== Tools ==================================================================

def _format_results(results: list[dict]) -> str:
    if not results:
        return 'No results.'
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get('title') or '(untitled)'
        url = r.get('href') or r.get('url') or ''
        body = (r.get('body') or '').strip()
        lines.append(f'{i}. **{title}**\n   {url}\n   {body}')
    return '\n'.join(lines)


async def web_search(query: str, max_results: int = 5) -> str:
    from ddgs import DDGS

    max_results = max(1, min(int(max_results or 5), 10))

    def _search():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    results = await asyncio.to_thread(_search)
    return _format_results(results)


async def fetch_url(url: str) -> str:
    if not is_public_http_url(url):
        return 'TOOL ERROR: refusing to fetch non-public or non-http(s) URLs.'
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0,
                                 headers={'User-Agent': 'SimplerAssistant/1.0'}) as client:
        resp = await client.get(url)
    content_type = resp.headers.get('content-type', '')
    text = html_to_text(resp.text) if 'html' in content_type else resp.text
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + f'\n… (truncated at {MAX_PAGE_CHARS} characters)'
    return f'[{resp.status_code}] {url}\n\n{text}'


def register(toolbox):
    toolbox.add_native(
        'web_search',
        'Search the web (DuckDuckGo). Returns titles, URLs and snippets; '
        'follow up with fetch_url to read a result.',
        SEARCH_SCHEMA, web_search)
    toolbox.add_native(
        'fetch_url',
        'Fetch a public http(s) URL and return its readable text content.',
        FETCH_SCHEMA, fetch_url)
