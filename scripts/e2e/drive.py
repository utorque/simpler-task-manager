"""E2E driver: a browser-equivalent chat session against the running stack
(scripts/e2e/run_stack.sh). Needs: pip install python-socketio[client] websocket-client

Verifies, over the actual wire protocols:
1. Flask login -> Chainlit header-auth bridge -> authenticated socket.io
2. plain streamed reply
3. E2E-TASK: agent turn -> simpler MCP tool call -> task really created via
   the audited REST path (actor='agent' in the changelog)
4. E2E-SANDBOX: agent turn -> sandbox MCP run_python -> produced file
   detected and sent back as a File element
5. chat history persisted in instance/chainlit.db
"""

import os
import sqlite3
import sys
import time
import uuid

import requests
import socketio

BASE = os.getenv('E2E_BASE', 'http://127.0.0.1:53999')
WORKSPACE = os.getenv('E2E_WORKSPACE', '/tmp/simpler-e2e-workspace')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASSED = []


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))
    PASSED.append(bool(condition))


# ---- 1. auth chain ----------------------------------------------------------
http = requests.Session()
r = http.post(f'{BASE}/login', json={'password': 'e2epass'})
check('flask login', r.ok)

r = http.post(f'{BASE}/assistant/auth/header')
check('chainlit header-auth via flask cookie', r.ok, f'status {r.status_code}')
check('access_token cookie set', 'access_token' in http.cookies.get_dict())

r_bad = requests.post(f'{BASE}/assistant/auth/header')
check('header-auth refused without cookie', r_bad.status_code == 401)

cookie_header = '; '.join(f'{k}={v}' for k, v in http.cookies.get_dict().items())


class Turn:
    def __init__(self):
        self.tokens = []
        self.messages = []
        self.elements = []
        self.done = False


sio = socketio.Client(logger=False)
turn = Turn()


@sio.on('stream_start')
def on_stream_start(data):
    turn.tokens.append(data.get('output', '') or '')


@sio.on('stream_token')
def on_stream_token(data):
    turn.tokens.append(data.get('token', ''))


@sio.on('new_message')
def on_new_message(data):
    turn.messages.append(data)


@sio.on('element')
def on_element(data):
    turn.elements.append(data)


@sio.on('task_end')
def on_task_end(data=None):
    turn.done = True


sio.connect(
    BASE,
    socketio_path='/assistant/ws/socket.io',
    headers={'Cookie': cookie_header},
    auth={'sessionId': str(uuid.uuid4()), 'clientType': 'webapp',
          'chatProfile': os.getenv('E2E_MODEL', 'mock-model'), 'userEnv': '{}'},
    transports=['websocket', 'polling'],
    wait_timeout=15,
)
check('socket.io connected (authenticated)', sio.connected)
sio.emit('connection_successful')
time.sleep(1)


def send_turn(text, timeout=60):
    global turn
    turn = Turn()
    sio.emit('client_message', {'message': {
        'id': str(uuid.uuid4()),
        'threadId': '',
        'name': 'owner',
        'type': 'user_message',
        'output': text,
        'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
    }})
    deadline = time.time() + timeout
    while not turn.done and time.time() < deadline:
        time.sleep(0.25)
    time.sleep(0.5)
    return turn


# ---- 2. plain streamed reply -------------------------------------------------
t = send_turn('hello there')
streamed = ''.join(t.tokens)
check('plain reply streamed', 'MOCK_REPLY' in streamed, repr(streamed[:60]))

# ---- 3. workspace tool call through simpler MCP ------------------------------
t = send_turn('Please E2E-TASK now')
streamed = ''.join(t.tokens)
check('tool-round reply streamed', 'TOOL_OK' in streamed, repr(streamed[:80]))

api = requests.Session()
api.headers['Authorization'] = 'Bearer e2e-api-token'
tasks = api.get(f'{BASE}/api/tasks').json()
created = [x for x in tasks if x['title'] == 'E2E task from assistant']
check('task created in workspace via MCP', len(created) == 1,
      f"space={created[0]['space'] if created else '-'} prio={created[0]['priority'] if created else '-'}")

logs = api.get(f'{BASE}/api/logs?limit=5').json()
agent_log = [entry for entry in logs if entry['actor'] == 'agent'
             and entry['action'] == 'create']
check("mutation audited as actor='agent'", len(agent_log) >= 1)

# ---- 4. sandbox file round-trip ----------------------------------------------
t = send_turn('Please E2E-SANDBOX now', timeout=90)
streamed = ''.join(t.tokens)
check('sandbox reply streamed', 'TOOL_OK' in streamed, repr(streamed[:80]))

file_elements = [e for e in t.elements if e.get('name') == 'e2e_output.txt']
file_msgs = [m for m in t.messages if 'Files from this turn' in (m.get('output') or '')]
check('produced file returned to user', bool(file_elements) and bool(file_msgs),
      f'{len(file_elements)} element(s)')

with open(os.path.join(WORKSPACE, 'e2e_output.txt')) as f:
    check('file content correct in shared workspace', f.read() == 'sandbox says hi')

sio.disconnect()

# ---- 5. history persisted ------------------------------------------------------
time.sleep(1)
db = sqlite3.connect(os.path.join(REPO, 'instance', 'chainlit.db'))
threads = db.execute('SELECT COUNT(*) FROM threads').fetchone()[0]
steps = db.execute("SELECT COUNT(*) FROM steps WHERE type='user_message'").fetchone()[0]
users = db.execute('SELECT identifier FROM users').fetchall()
check('chat history persisted', threads >= 1 and steps >= 3,
      f'{threads} thread(s), {steps} user message(s), users={users}')

print()
print(f'{sum(PASSED)}/{len(PASSED)} checks passed')
sys.exit(0 if all(PASSED) else 1)
