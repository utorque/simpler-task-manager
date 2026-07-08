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
})();
