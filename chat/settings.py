"""Environment-driven settings for the assistant.

The assistant reuses the exact same `.env` as the Flask app (AI_API_KEY /
AI_API_BASE_URL / AI_MODEL / SECRET_KEY / API_TOKEN) so there is a single
provider configuration for the whole project. Assistant-specific knobs are
additive and all optional:

  CHAT_MODELS            comma-separated model ids offered in the model picker
                         (first = default). Unset -> just AI_MODEL.
  CHAT_MAX_TOKENS        max tokens per reply (Anthropic requires a value).
  SIMPLER_BASE_URL       base URL of the Simpler REST API as seen from the
                         assistant (in-process mount -> loopback default).
  CHAINLIT_AUTH_SECRET   JWT secret for Chainlit's own auth tokens; derived
                         from SECRET_KEY when unset so no extra config is
                         needed.
"""

import hashlib
import hmac
import os

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_DIR = os.path.join(REPO_ROOT, 'chat')
INSTANCE_DIR = os.path.join(REPO_ROOT, 'instance')


def secret_key() -> str:
    return os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')


def ai_api_key():
    return os.getenv('AI_API_KEY')


def ai_base_url() -> str:
    return os.getenv('AI_API_BASE_URL', 'https://api.openai.com/v1/')


def chat_models() -> list[str]:
    """Models offered in the picker; first entry is the default."""
    raw = os.getenv('CHAT_MODELS', '')
    models = [m.strip() for m in raw.split(',') if m.strip()]
    if not models:
        models = [os.getenv('AI_MODEL', 'gpt-3.5-turbo')]
    return models


def max_tokens() -> int:
    return int(os.getenv('CHAT_MAX_TOKENS', '4096'))


def simpler_base_url() -> str:
    # In the integrated deployment the Flask API lives in the same server
    # process (asgi.py), reachable over loopback.
    return os.getenv('SIMPLER_BASE_URL', 'http://127.0.0.1:53000').rstrip('/')


def simpler_api_token():
    """Bearer credential for the Simpler REST API (same one the MCP sidecar
    uses). Unset -> workspace integration features degrade gracefully."""
    return os.getenv('API_TOKEN') or None


def chainlit_db_path() -> str:
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    return os.path.join(INSTANCE_DIR, 'chainlit.db')


def simpler_mcp_url():
    """URL of Simpler's own MCP sidecar (pre-integrated tool server).
    Compose wires http://mcp:8765/mcp; unset -> workspace tools come only
    from what the user plugs in via the UI."""
    return os.getenv('SIMPLER_MCP_URL') or None


def extra_mcp_servers() -> dict[str, str]:
    """Additional pre-integrated MCP servers: CHAT_MCP_SERVERS is a
    comma-separated list of name=url pairs (streamable HTTP)."""
    servers = {}
    for entry in os.getenv('CHAT_MCP_SERVERS', '').split(','):
        name, _, url = entry.strip().partition('=')
        if name and url:
            servers[name.strip()] = url.strip()
    return servers


def files_dir() -> str:
    """Where uploaded/produced files live. Step 5 points this at the volume
    shared with the sandbox container."""
    path = os.getenv('CHAT_FILES_DIR') or os.path.join(INSTANCE_DIR, 'assistant_files')
    os.makedirs(path, exist_ok=True)
    return path


def agent_max_rounds() -> int:
    return int(os.getenv('CHAT_MAX_TOOL_ROUNDS', '8'))


def ensure_chainlit_env():
    """Set the env vars Chainlit needs, before `chainlit` is imported.

    - CHAINLIT_APP_ROOT: keep Chainlit's config/translations/files under
      chat/ instead of the repo root.
    - CHAINLIT_AUTH_SECRET: required once an auth callback exists. Derived
      deterministically from SECRET_KEY so one secret in .env is enough
      (override by setting CHAINLIT_AUTH_SECRET explicitly).
    """
    os.environ.setdefault('CHAINLIT_APP_ROOT', CHAT_DIR)
    if not os.environ.get('CHAINLIT_AUTH_SECRET'):
        derived = hmac.new(
            secret_key().encode(), b'simpler-chainlit-auth-secret', hashlib.sha256
        ).hexdigest()
        os.environ['CHAINLIT_AUTH_SECRET'] = derived
