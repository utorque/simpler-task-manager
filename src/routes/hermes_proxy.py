"""Same-origin reverse proxy for the embedded hermes-webui (PRD 002 §4.2-bis).

Streams `/hermes-ui/<path>` to the `hermes-webui` compose service so the
Hermes destination iframe is SAME-ORIGIN: no sibling DNS name, no nginx
changes, no `frame-ancestors` surgery — and the whole surface rides Simpler's
session gate (one login). Enabled only when `HERMES_WEBUI_INTERNAL_URL` is
set (compose wires it to http://hermes-webui:8787); unset ⇒ the blueprint
answers 404 and the app is byte-identical to before.

Proxy rules:
- every method is forwarded with query string + body; hop-by-hop headers are
  dropped both ways (per RFC 9110 §7.6.1),
- `X-Frame-Options` is stripped and any `frame-ancestors` CSP directive
  removed from responses — framing is what this proxy exists for, and the
  iframe is same-origin so the header adds nothing,
- absolute/root-absolute `Location` redirects are rewritten under
  `/hermes-ui`, so webui-internal redirects stay inside the proxy,
- responses stream (SSE chat tokens flow through unbuffered).
"""

import re

import requests
from flask import Blueprint, Response, current_app, request, stream_with_context

from auth import login_required

hermes_proxy_bp = Blueprint('hermes_proxy', __name__)

PROXY_PREFIX = '/hermes-ui'

# RFC 9110 hop-by-hop headers, plus ones Flask/Werkzeug must recompute.
_HOP_BY_HOP = {
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailer', 'transfer-encoding', 'upgrade',
    'content-encoding', 'content-length',
}


def _upstream_base():
    url = current_app.config.get('HERMES_WEBUI_INTERNAL_URL')
    return url.rstrip('/') if url else None


def _request_headers():
    """Forward the client's headers minus hop-by-hop and Host (requests sets
    the right Host for the upstream)."""
    headers = {}
    for name, value in request.headers.items():
        if name.lower() in _HOP_BY_HOP or name.lower() == 'host':
            continue
        headers[name] = value
    return headers


def _rewrite_location(location, base):
    """Keep webui-internal redirects under the proxy prefix."""
    if location.startswith(base):
        location = location[len(base):] or '/'
    if location.startswith('/') and not location.startswith('//') \
            and not location.startswith(PROXY_PREFIX + '/') and location != PROXY_PREFIX:
        return PROXY_PREFIX + location
    return location


def _strip_frame_ancestors(csp):
    """Drop only the frame-ancestors directive; keep the rest of the policy."""
    directives = [d for d in csp.split(';')
                  if d.strip() and not d.strip().lower().startswith('frame-ancestors')]
    return ';'.join(directives).strip()


def _response_headers(upstream, base):
    headers = []
    for name, value in upstream.headers.items():
        lower = name.lower()
        if lower in _HOP_BY_HOP or lower == 'x-frame-options':
            continue
        if lower == 'location':
            value = _rewrite_location(value, base)
        elif lower in ('content-security-policy', 'content-security-policy-report-only'):
            value = _strip_frame_ancestors(value)
            if not value:
                continue
        headers.append((name, value))
    return headers


@hermes_proxy_bp.route(f'{PROXY_PREFIX}/', defaults={'subpath': ''},
                       methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
@hermes_proxy_bp.route(f'{PROXY_PREFIX}/<path:subpath>',
                       methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
@login_required
def proxy(subpath):
    base = _upstream_base()
    if not base:
        return {'error': 'Hermes webui proxy is not configured'}, 404

    try:
        upstream = requests.request(
            request.method,
            f'{base}/{subpath}',
            params=request.query_string,
            data=request.get_data(),
            headers=_request_headers(),
            stream=True,
            allow_redirects=False,
            timeout=(10, 300),  # generous read timeout: SSE streams stay open
        )
    except requests.RequestException as e:
        return {'error': f'hermes-webui unreachable: {e}'}, 502

    body = stream_with_context(upstream.iter_content(chunk_size=8192))
    return Response(
        body,
        status=upstream.status_code,
        headers=_response_headers(upstream, base),
        direct_passthrough=True,
    )
