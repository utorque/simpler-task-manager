/* Clipboard polyfill for Chainlit's message "copy" button.
 *
 * Chainlit builds a `new ClipboardItem(...)` and calls
 * `navigator.clipboard.write(...)`. Over plain HTTP (isSecureContext ===
 * false) — how the assistant is often served internally — `ClipboardItem`
 * and the async clipboard API are undefined, so the button throws
 * "Failed to copy: ReferenceError: ClipboardItem is not defined". Shim the
 * missing pieces and fall back to a hidden-textarea execCommand copy (the
 * same fallback the shell uses in src/static/js/app.js). No-op wherever the
 * native APIs already exist (secure contexts), so modern browsers are
 * untouched. */
(function installClipboardPolyfill() {
    function legacyCopyText(text) {
        var ta = document.createElement('textarea');
        ta.value = text == null ? '' : String(text);
        ta.style.position = 'fixed';
        ta.style.top = '-9999px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        document.body.removeChild(ta);
        return ok;
    }

    // Pull a text/plain string out of a ClipboardItem-like object (native or
    // our shim). Returns a Promise<string>.
    function itemText(item) {
        try {
            if (item && typeof item.getType === 'function') {
                return item.getType('text/plain').then(function (blob) {
                    return blob && typeof blob.text === 'function' ? blob.text() : '';
                }, function () { return ''; });
            }
        } catch (e) { /* fall through */ }
        return Promise.resolve('');
    }

    if (typeof window.ClipboardItem === 'undefined') {
        window.ClipboardItem = function ClipboardItem(items) {
            this._items = items || {};
        };
        window.ClipboardItem.prototype.getType = function (type) {
            var val = this._items[type];
            if (val instanceof Blob) return Promise.resolve(val);
            if (val && typeof val.then === 'function') return Promise.resolve(val);
            return Promise.resolve(new Blob([val == null ? '' : String(val)], { type: type }));
        };
    }

    if (!navigator.clipboard) {
        try {
            Object.defineProperty(navigator, 'clipboard', { value: {}, configurable: true });
        } catch (e) {
            try { navigator.clipboard = {}; } catch (e2) { return; }
        }
    }

    if (typeof navigator.clipboard.writeText !== 'function') {
        try {
            navigator.clipboard.writeText = function (text) {
                return legacyCopyText(text)
                    ? Promise.resolve()
                    : Promise.reject(new Error('copy command was unsuccessful'));
            };
        } catch (e) { /* read-only clipboard: nothing more we can do */ }
    }

    if (typeof navigator.clipboard.write !== 'function') {
        try {
            navigator.clipboard.write = function (items) {
                return itemText((items || [])[0]).then(function (text) {
                    return navigator.clipboard.writeText(text);
                });
            };
        } catch (e) { /* read-only clipboard: nothing more we can do */ }
    }
})();

/* Bridge the Simpler shell's space filter into the Chainlit backend.
 *
 * The assistant iframe is same-origin with the shell, so both share
 * localStorage. The shell's space chips (src/static/js/app.js) write
 * `assistantSpaceFilter`; this script (loaded via UI.custom_js) forwards it
 * as a window message — Chainlit's frontend relays any window `message`
 * event to the backend, where @cl.on_window_message stores it in the user
 * session.
 *
 * Sync is poll-based (light: localStorage read every 2s, re-post at most
 * every 10s) so it survives things postMessage timing can't: socket
 * reconnects, "New Chat" resets, thread resumes.
 */
(function () {
    var lastPayload = null;
    var lastSentAt = 0;

    function sync() {
        var raw;
        try {
            raw = window.localStorage.getItem('assistantSpaceFilter') || 'null';
        } catch (e) {
            return;
        }
        var payload = JSON.stringify({ type: 'simpler-space-filter', space_ids: JSON.parse(raw) });
        var now = Date.now();
        if (payload === lastPayload && now - lastSentAt < 10000) return;
        lastPayload = payload;
        lastSentAt = now;
        // Post to our own window: the Chainlit app listens for window
        // `message` events and forwards them to the backend socket.
        window.postMessage(payload, window.location.origin);
    }

    function tick() {
        sync();
        pumpPinnedTask();
        reloadIfStartersStale();
    }

    setInterval(tick, 2000);
    if (document.readyState === 'complete') {
        setTimeout(tick, 500);
    } else {
        window.addEventListener('load', function () { setTimeout(tick, 500); });
    }

    /* "Work on this with the assistant": the shell's robot buttons (board
     * cards and note rows, src/static/js/app.js) hand tasks/notes over through
     * a localStorage queue (`assistantPinQueue`, a JSON array of
     * {kind:'task'|'note', id}). A plain click also switches to the Assistant
     * tab; Ctrl+click stages an item and stays put, so several can pile up
     * before the user comes over.
     *
     * localStorage rather than postMessage because the shell lazy-loads this
     * iframe — the very first pin happens BEFORE this script exists, so the
     * handoff has to be a value that waits for us, not an event. The queue is
     * drained (read once and removed) only while this iframe is actually on
     * screen, so background staging never delivers early; everything staged is
     * then handed over together the moment the Assistant tab opens. The batch
     * is re-posted every tick until the backend answers with its prefill (the
     * socket may not be up yet on a cold iframe), then dropped.
     *
     * Backend side: @cl.on_window_message → on_pin_refs, same injection the
     * task starters run. */
    var PIN_QUEUE_KEY = 'assistantPinQueue';
    var pendingPins = null;

    // Only deliver while the Assistant view is visible: the parent hides this
    // iframe (display:none) on other tabs, so a hidden frame has no offsetParent.
    function assistantVisible() {
        try {
            var fe = window.frameElement;
            if (!fe) return true;            // not framed (tests) → assume visible
            return fe.offsetParent !== null;
        } catch (e) {
            return true;
        }
    }

    function readPinnedRefs() {
        var raw;
        try {
            raw = window.localStorage.getItem(PIN_QUEUE_KEY);
            if (!raw) return;
            window.localStorage.removeItem(PIN_QUEUE_KEY);
        } catch (e) {
            return;
        }
        var queue;
        try { queue = JSON.parse(raw); } catch (e) { return; }
        if (!Array.isArray(queue)) return;
        var refs = [];
        for (var i = 0; i < queue.length; i++) {
            var p = queue[i];
            if (p && p.id != null && (p.kind === 'task' || p.kind === 'note')) {
                refs.push({ kind: p.kind, id: p.id });
            }
        }
        if (!refs.length) return;
        // A batch that arrives mid-flight (rapid staging) joins the pending one.
        if (pendingPins) {
            pendingPins.refs = pendingPins.refs.concat(refs);
            pendingPins.tries = 0;
        } else {
            pendingPins = { refs: refs, tries: 0 };
        }
    }

    function pumpPinnedTask() {
        // Draining a hidden iframe would deliver staged pins into a conversation
        // the user hasn't opened yet — wait until the Assistant view is on screen.
        if (!assistantVisible()) return;
        readPinnedRefs();
        if (!pendingPins) return;
        // The composer only exists once the chat session is mounted; posting
        // before that goes nowhere (nothing relays it to the backend yet).
        if (!document.getElementById('chat-input')) return;
        if (pendingPins.tries++ > 5) {
            pendingPins = null;
            return;
        }
        window.postMessage(JSON.stringify({
            type: 'simpler-pin',
            refs: pendingPins.refs
        }), window.location.origin);
    }

    // Same-origin parent writes fire `storage` here: pin without waiting for
    // the next poll when the iframe is already loaded and visible.
    window.addEventListener('storage', function (event) {
        if (event.key === PIN_QUEUE_KEY) pumpPinnedTask();
    });

    /* Starters are the tasks in Doing, and Chainlit ships them inside the
     * config it fetches ONCE per page load — so a board change in the shell
     * leaves them stale until F5. The shell publishes a revision string of its
     * Doing set ('assistantStartersRev'); when it moves, reload the iframe —
     * but only while the welcome screen is up (starters on screen, composer
     * empty), the one state where a reload costs nothing. Mid-conversation the
     * starters aren't visible anyway and the next New Chat gets them fresh. */
    var startersRev = readStartersRev();

    function readStartersRev() {
        try { return window.localStorage.getItem('assistantStartersRev'); }
        catch (e) { return null; }
    }

    function reloadIfStartersStale() {
        var rev = readStartersRev();
        if (rev === startersRev) return;
        startersRev = rev;
        if (pendingPins) return;                      // a pin is mid-flight
        if (!document.getElementById('starters')) return;
        var input = document.getElementById('chat-input');
        if (input && input.value.trim()) return;      // don't eat a draft
        window.location.reload();
    }

    /* Starter prefill (issue 003.01): starters must not fire-and-send.
     *
     * Capture-phase click interception runs BEFORE React's delegated
     * handler, so stopping propagation means Chainlit never sends the
     * starter message. The click label goes to the backend (same window
     * `message` relay as the space filter above); the backend runs the
     * starter's /task injection and answers with a
     * `simpler-starter-prefill` window message (Chainlit posts those to
     * window.parent), which we write into the composer — a controlled
     * React textarea, so set via the native value setter + an `input`
     * event to update React state. */
    document.addEventListener('click', function (event) {
        var button = event.target && event.target.closest
            ? event.target.closest('button[id^="starter-"]') : null;
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        window.postMessage(JSON.stringify({
            type: 'simpler-starter-click',
            label: (button.textContent || '').trim()
        }), window.location.origin);
    }, true);

    /* The composer is a controlled React textarea: writing `.value`
     * directly is invisible to React, so go through the native value
     * setter and fire an `input` event to sync its state. */
    function writeComposer(input, value, caret) {
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        input.setSelectionRange(caret, caret);
    }

    function setComposerText(text) {
        var input = document.getElementById('chat-input');
        if (!input) return;
        writeComposer(input, text, text.length);
    }

    function insertComposerText(text) {
        var input = document.getElementById('chat-input');
        if (!input) return;
        var value = input.value || '';
        var start = input.selectionStart == null ? value.length : input.selectionStart;
        var end = input.selectionEnd == null ? start : input.selectionEnd;
        var before = value.slice(0, start);
        var after = value.slice(end);
        // Keep the path a standalone token whichever side it lands on.
        var chunk = (before && !/\s$/.test(before) ? ' ' : '') + text +
            (after && !/^\s/.test(after) ? ' ' : '');
        writeComposer(input, before + chunk + after, before.length + chunk.length);
    }

    function onPrefillMessage(event) {
        var data = event.data;
        if (typeof data === 'string') {
            try { data = JSON.parse(data); } catch (e) { return; }
        }
        if (!data || data.type !== 'simpler-starter-prefill') return;
        pendingPins = null;  // the backend answered: stop re-posting the pins
        setComposerText(data.prefill || '');
    }

    /* Workspace path drop: the shell's WorkspaceView drawer lives OUTSIDE
     * this iframe, but a drag started there still dispatches dragover/drop
     * into a same-origin iframe, and the drag data store is readable on
     * drop. Chainlit's own dropzone would swallow that drop as a file
     * upload, so we intercept in the WINDOW CAPTURE phase (ahead of every
     * React handler) whenever the drag carries the drawer's custom MIME
     * type, and paste the workspace-relative path into the composer
     * instead — the model addresses sandbox/workspace files by that path. */
    var WORKSPACE_MIME = 'application/x-workspace-path';
    var dragoverTimer = null;

    function carriesWorkspacePath(event) {
        var types = event.dataTransfer && event.dataTransfer.types;
        // `types` is a DOMStringList in older engines — no .includes().
        return !!types && Array.prototype.indexOf.call(types, WORKSPACE_MIME) !== -1;
    }

    function markDragging(on) {
        document.body.classList.toggle('simpler-path-dragover', on);
        if (dragoverTimer) clearTimeout(dragoverTimer);
        // dragleave/dragend are unreliable across the iframe boundary
        // (drops that land back in the shell never notify us), so the
        // highlight expires on its own once dragover stops firing.
        dragoverTimer = on ? setTimeout(function () { markDragging(false); }, 200) : null;
    }

    window.addEventListener('dragover', function (event) {
        if (!carriesWorkspacePath(event)) return;
        event.preventDefault();            // required for `drop` to fire at all
        event.stopImmediatePropagation();
        event.dataTransfer.dropEffect = 'copy';
        markDragging(true);
    }, true);

    window.addEventListener('drop', function (event) {
        if (!carriesWorkspacePath(event)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        markDragging(false);
        var path = event.dataTransfer.getData('text/plain')
            || event.dataTransfer.getData(WORKSPACE_MIME);
        if (path) insertComposerText('`' + path + '`');
    }, true);

    // The backend's send_window_message lands on window.parent when the
    // assistant is iframed by the shell (same-origin), on window itself
    // when running standalone — listen on both.
    window.addEventListener('message', onPrefillMessage);
    try {
        if (window.parent && window.parent !== window) {
            window.parent.addEventListener('message', onPrefillMessage);
        }
    } catch (e) { /* cross-origin parent: not the Simpler shell */ }
})();
