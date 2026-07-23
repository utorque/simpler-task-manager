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
        tryFlush();
    }

    setInterval(tick, 2000);
    if (document.readyState === 'complete') {
        setTimeout(tick, 500);
    } else {
        window.addEventListener('load', function () { setTimeout(tick, 500); });
    }

    /* "Work on this with the assistant": the shell's robot buttons (board
     * cards and note rows, src/static/js/app.js) STAGE tasks/notes into a
     * localStorage queue (`assistantPinQueue`, a JSON array of
     * {kind:'task'|'note', id}). Ctrl+click stages and stays put; a plain click
     * stages and jumps to the Assistant tab. The nav tab shows the staged count.
     *
     * Delivery is EXPLICIT, never a background poll (that is what "just doesn't
     * pin" tripped on). The queue is flushed only when:
     *   - the welcome screen's one starter is clicked (intercepted below), or
     *   - the shell asks for it: a plain robot click posts `simpler-pin-flush`
     *     into this iframe (already loaded), or leaves `assistantPinFlush` in
     *     localStorage for a cold iframe to honour on boot.
     * A flush reads+clears the queue and posts one `simpler-pin` batch, which
     * @cl.on_window_message → on_pin_refs injects (task + linked note, or full
     * note) and seeds the composer. It re-posts each tick until the backend's
     * prefill answers (a cold socket may not be up yet), capped at 5 tries. */
    var PIN_QUEUE_KEY = 'assistantPinQueue';
    var PIN_FLUSH_KEY = 'assistantPinFlush';
    var PIN_STARTER_LABEL = '📌 Work on my pinned tasks';
    var flush = null;                                 // {tries, refs} while in flight

    function requestFlush() {
        if (flush) { flush.tries = 0; }               // already gathering — retry now
        else { flush = { tries: 0, refs: null }; }    // fresh: read the queue
        tryFlush();
    }

    function tryFlush() {
        if (!flush) return;
        // The composer/socket must be up to relay the batch to the backend; on a
        // cold iframe it may not be yet — stay pending and retry next tick.
        if (!document.getElementById('chat-input')) return;
        if (flush.tries++ > 5) { flush = null; return; }
        // Read + clear the queue once (the key is removed on first read); hold
        // the refs so a retry re-posts the same batch instead of losing it.
        if (flush.refs === null) {
            var raw;
            try {
                raw = window.localStorage.getItem(PIN_QUEUE_KEY);
                window.localStorage.removeItem(PIN_QUEUE_KEY);
            } catch (e) { raw = null; }
            var queue = [];
            try { queue = raw ? JSON.parse(raw) : []; } catch (e) { queue = []; }
            var refs = [];
            if (Array.isArray(queue)) {
                for (var i = 0; i < queue.length; i++) {
                    var p = queue[i];
                    if (p && p.id != null && (p.kind === 'task' || p.kind === 'note')) {
                        refs.push({ kind: p.kind, id: p.id });
                    }
                }
            }
            flush.refs = refs;
        }
        window.postMessage(JSON.stringify({
            type: 'simpler-pin',
            refs: flush.refs
        }), window.location.origin);
    }

    // Cold-iframe flush request left by a plain robot click before this script
    // existed: honour it once, then let tick retry until the socket is up.
    try {
        if (window.localStorage.getItem(PIN_FLUSH_KEY)) {
            window.localStorage.removeItem(PIN_FLUSH_KEY);
            requestFlush();
        }
    } catch (e) { /* no localStorage → nothing to flush */ }

    // Live-iframe flush: the shell posts this straight into our window when a
    // plain robot click switches over, so delivery is immediate, not polled.
    window.addEventListener('message', function (event) {
        var data = event.data;
        if (typeof data === 'string') {
            try { data = JSON.parse(data); } catch (e) { return; }
        }
        if (data && data.type === 'simpler-pin-flush') requestFlush();
    });

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
        var label = (button.textContent || '').trim();
        // The one pin starter delivers the staged tasks/notes (resolved here
        // from localStorage); every other starter goes through the backend.
        if (label === PIN_STARTER_LABEL) {
            requestFlush();
            return;
        }
        window.postMessage(JSON.stringify({
            type: 'simpler-starter-click',
            label: label
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
        flush = null;        // the backend answered: stop re-posting the pins
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
