"""Issue 004 — RED tests for `POST /api/notes/<id>/cleanify` route.

Three behaviours:
  1. Returns `{content: 'cleaned'}` with the stub provider and does NOT
     persist the cleaned content (the note's `content_markdown` is
     unchanged in DB after the call).
  2. Injects the note's Space's name + description into the system_prompt
     passed to the AI provider (verified via a local spy stub).
  3. Degrades gracefully on AI failure: returns `{content: <original>}`
     with HTTP 200.

The `stub_ai_provider_spy` fixture is local to this file (per issue
instructions: do NOT edit the shared `conftest.py`).
"""

from conftest import login, StubAIProvider


class SpyAIProvider(StubAIProvider):
    """StubAIProvider variant that records the system_prompt arg passed to
    `cleanify`, so the space-description injection test can assert on it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured_system_prompt = None

    def cleanify(self, note_text, system_prompt):
        self.captured_system_prompt = system_prompt
        return "cleaned"


import pytest


@pytest.fixture
def stub_ai_provider_spy(monkeypatch):
    """Patch `ai_parser.get_ai_provider` to return a SpyAIProvider instance
    that captures the `system_prompt` passed to `cleanify`."""
    import ai_parser
    spy = SpyAIProvider()
    monkeypatch.setattr(ai_parser, "get_ai_provider", lambda: spy)
    return spy


def test_cleanify_returns_cleaned_content_without_persisting(client, stub_ai_provider, sample_note):
    login(client)
    resp = client.post(f'/api/notes/{sample_note.id}/cleanify')
    assert resp.status_code == 200
    assert resp.get_json() == {'content': 'cleaned'}

    # The note's content_markdown is unchanged in DB after the call (no persistence).
    from models import Note
    note = Note.query.get(sample_note.id)
    assert note.content_markdown == sample_note.content_markdown  # not persisted


def test_cleanify_injects_space_description_into_system_prompt(client, stub_ai_provider_spy, sample_note):
    login(client)
    client.post(f'/api/notes/{sample_note.id}/cleanify')
    captured_system_prompt = stub_ai_provider_spy.captured_system_prompt
    assert sample_note.space_rel.description in captured_system_prompt
    assert sample_note.space_rel.name in captured_system_prompt


def test_cleanify_injects_note_date_into_system_prompt(client, stub_ai_provider_spy, sample_note):
    login(client)
    client.post(f'/api/notes/{sample_note.id}/cleanify')
    captured_system_prompt = stub_ai_provider_spy.captured_system_prompt
    expected_date = sample_note.created_at.strftime('%Y-%m-%d')
    assert f'Note date (put below the title): {expected_date}' in captured_system_prompt


def test_cleanify_returns_original_on_ai_failure(client, stub_ai_provider_raising, sample_note):
    login(client)
    resp = client.post(f'/api/notes/{sample_note.id}/cleanify')
    assert resp.status_code == 200
    assert resp.get_json() == {'content': sample_note.content_markdown}


def test_cleanify_404_when_note_missing(client, stub_ai_provider):
    login(client)
    resp = client.post('/api/notes/999999/cleanify')
    assert resp.status_code == 404
