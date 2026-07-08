"""Assistant tab in the unified shell (replaces the former Hermes tab).

The Chainlit app itself is mounted by asgi.py (ASGI, outside Flask); the
Flask side only decides whether the tab + iframe exist, from
Config.ASSISTANT_URL. These tests cover that seam and the Hermes removal.
"""

from conftest import login


def test_assistant_tab_hidden_without_url(client, app):
    app.config['ASSISTANT_URL'] = None
    login(client)
    page = client.get('/').get_data(as_text=True)
    assert 'view-assistant' not in page
    assert 'data-destination="assistant"' not in page


def test_assistant_tab_shown_with_url(client, app):
    app.config['ASSISTANT_URL'] = '/assistant/'
    login(client)
    page = client.get('/').get_data(as_text=True)
    assert 'data-destination="assistant"' in page
    # Lazy iframe: src comes from data-src on first switch (app.js).
    assert 'data-src="/assistant/"' in page
    assert 'id="assistantFrame"' in page


def test_hermes_is_gone(client, app):
    login(client)
    page = client.get('/').get_data(as_text=True)
    assert 'hermes' not in page.lower()
    # The reverse-proxy blueprint no longer exists.
    assert client.get('/hermes-ui/').status_code == 404
