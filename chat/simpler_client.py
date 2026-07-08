"""Async client for Simpler's own REST API (the assistant's window into the
workspace).

Same seam as the MCP sidecar: every call rides the API_TOKEN bearer path
(src/auth.py), so assistant-driven reads/writes are attributable and the
Flask routes stay the single source of truth. With API_TOKEN unset the
assistant still chats — workspace features just report themselves
unavailable instead of failing.

The module-level client is swappable (tests inject an httpx transport wired
to the Flask test app, mirroring tests/test_mcp_tools.py).
"""

import httpx

from chat import settings


class SimplerAPIError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def configured() -> bool:
    return settings.simpler_api_token() is not None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.simpler_base_url(),
            headers={'Authorization': f'Bearer {settings.simpler_api_token() or ""}'},
            timeout=30.0,
        )
    return _client


async def _get(path: str, params: dict | None = None):
    if not configured():
        raise SimplerAPIError(
            'Workspace access is not configured (set API_TOKEN in .env).')
    try:
        resp = await get_client().get(path, params=params)
    except httpx.HTTPError as e:
        raise SimplerAPIError(f'Simpler API unreachable: {e}')
    if resp.status_code >= 400:
        try:
            detail = resp.json().get('error', resp.text)
        except Exception:
            detail = resp.text
        raise SimplerAPIError(f'Simpler API error {resp.status_code}: {detail}')
    return resp.json()


async def list_spaces() -> list:
    return await _get('/api/spaces')


async def list_tasks(include_completed: bool = False, space_ids: list[int] | None = None,
                     status: str | None = None) -> list:
    fetch_completed = include_completed or status == 'done'
    tasks = await _get('/api/tasks',
                       params={'include_completed': str(fetch_completed).lower()})
    if space_ids is not None:
        tasks = [t for t in tasks if t.get('space_id') in space_ids]
    if status is not None:
        tasks = [t for t in tasks if t.get('status') == status]
    return tasks


async def get_task(task_id: int) -> dict:
    tasks = await _get('/api/tasks', params={'include_completed': 'true'})
    for task in tasks:
        if task['id'] == task_id:
            return task
    raise SimplerAPIError(f'Task {task_id} not found')


async def list_notes(space_ids: list[int] | None = None) -> list:
    notes = await _get('/api/notes')
    if space_ids is not None:
        notes = [n for n in notes if n.get('space_id') in space_ids]
    return notes


async def get_note(note_id: int) -> dict:
    return await _get(f'/api/notes/{note_id}')
