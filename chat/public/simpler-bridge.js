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

    setInterval(sync, 2000);
    if (document.readyState === 'complete') {
        setTimeout(sync, 500);
    } else {
        window.addEventListener('load', function () { setTimeout(sync, 500); });
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

    function setComposerText(text) {
        var input = document.getElementById('chat-input');
        if (!input) return;
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(input, text);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        input.setSelectionRange(text.length, text.length);
    }

    function onPrefillMessage(event) {
        var data = event.data;
        if (typeof data === 'string') {
            try { data = JSON.parse(data); } catch (e) { return; }
        }
        if (!data || data.type !== 'simpler-starter-prefill') return;
        setComposerText(data.prefill || '');
    }

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
