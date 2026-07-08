"""Issue 003.07 — the settings panel's shell wiring (template contract).

The interactive behavior lives in src/static/js/assistant_settings.js
(vanilla JS, no JS test harness in this repo — manual checklist in the
issue); these tests pin the template seams the script depends on.
"""

from conftest import login


def test_panel_markup_present_with_assistant(client, app):
    app.config['ASSISTANT_URL'] = '/assistant/'
    login(client)
    page = client.get('/').get_data(as_text=True)
    assert 'id="assistantSettingsBtn"' in page
    assert 'id="assistantSettingsModal"' in page
    # The five tabs.
    for target in ('astab-models', 'astab-modes', 'astab-skills',
                   'astab-prompt', 'astab-composition'):
        assert f'data-bs-target="#{target}"' in page
    assert '/static/js/assistant_settings.js' in page
    # The shortcut is documented in the help modal (single source of truth).
    assert 'Open the Assistant settings' in page


def test_panel_markup_absent_without_assistant(client, app):
    app.config['ASSISTANT_URL'] = None
    login(client)
    page = client.get('/').get_data(as_text=True)
    assert 'assistantSettingsModal' not in page
    assert 'assistant_settings.js' not in page
