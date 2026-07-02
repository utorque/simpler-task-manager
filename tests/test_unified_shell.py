"""The unified shell: one page, one header, all destinations present."""

from conftest import login


def test_shell_carries_all_destinations_and_board_columns(client):
    login(client)
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.data.decode()

    # One main header with the destination nav
    assert 'app-header' in html
    for destination in ('tasks', 'notes', 'mail', 'calendar', 'spaces'):
        assert f'data-destination="{destination}"' in html

    # Global quick capture reachable from every view
    assert 'quickCapture' in html

    # Kanban board columns (the Tasks home)
    for status in ('todo', 'doing', 'blocked', 'done'):
        assert f'id="col-{status}"' in html

    # Calendar and overview survive inside the shell
    assert 'id="calendar"' in html
    assert 'spaceCardsContainer' in html

    # Shortcuts help modal
    assert 'helpModal' in html


def test_unauthenticated_shell_redirects_to_login(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
