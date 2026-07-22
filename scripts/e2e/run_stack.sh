#!/bin/bash
# Local E2E stack: the docker-compose topology as plain processes.
#
#   web (uvicorn asgi:app)  :53999   Flask + Chainlit assistant
#   simpler-mcp sidecar     :8765    workspace tools
#   sandbox sidecar         :8766    execution sandbox (NO container isolation here!)
#   mock LLM                :8089    scripted OpenAI-compatible model
#
# Usage:  bash scripts/e2e/run_stack.sh   (needs `pip install -r requirements.txt`)
# Then:   python scripts/e2e/drive.py
#
# WARNING: wipes instance/tasks.db + instance/chainlit.db (test databases).
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
WORKSPACE="${E2E_WORKSPACE:-/tmp/simpler-e2e-workspace}"
LOGDIR="${E2E_LOGDIR:-/tmp/simpler-e2e-logs}"
PY="${PYTHON:-python3}"
cd "$REPO"

pkill -f 'uvicorn asgi:app' 2>/dev/null || true
pkill -f 'mcp_server/server.py' 2>/dev/null || true
pkill -f 'sandbox/server.py' 2>/dev/null || true
pkill -f 'e2e/mock_llm.py' 2>/dev/null || true
sleep 1

rm -rf "$WORKSPACE" "$REPO/instance/chainlit.db" "$REPO/instance/tasks.db"
mkdir -p "$WORKSPACE" "$LOGDIR"

env -i PATH="$PATH" HOME="$HOME" \
  SECRET_KEY=e2e-test-secret-key APP_PASSWORD=e2epass API_TOKEN=e2e-api-token FLASK_ENV=production \
  AI_API_KEY=sk-mock AI_API_BASE_URL=http://127.0.0.1:8089/v1 AI_MODEL=mock-model CHAT_MODELS=mock-model \
  SIMPLER_MCP_URL=http://127.0.0.1:8765/mcp SANDBOX_MCP_URL=http://127.0.0.1:8766/mcp \
  CHAT_FILES_DIR="$WORKSPACE" \
  "$PY" -m uvicorn asgi:app --host 127.0.0.1 --port 53999 > "$LOGDIR/web.log" 2>&1 &

env -i PATH="$PATH" HOME="$HOME" \
  SIMPLER_BASE_URL=http://127.0.0.1:53999 SIMPLER_API_TOKEN=e2e-api-token MCP_BIND=127.0.0.1:8765 \
  "$PY" mcp_server/server.py > "$LOGDIR/mcp.log" 2>&1 &

env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$REPO" \
  SANDBOX_WORKSPACE="$WORKSPACE" MCP_BIND=127.0.0.1:8766 \
  "$PY" sandbox/server.py > "$LOGDIR/sandbox.log" 2>&1 &

env -i PATH="$PATH" HOME="$HOME" \
  "$PY" scripts/e2e/mock_llm.py > "$LOGDIR/mockllm.log" 2>&1 &

sleep 8
for p in 53999 8765 8766 8089; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$p/" || echo 000)
  echo "port $p: HTTP $code"
done
echo "logs in $LOGDIR — now run: python scripts/e2e/drive.py"
