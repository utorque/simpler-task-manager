# Responsive / phone layer

> Phone UX for the shell, added 2026-07 as **progressive enhancement over the existing vanilla-JS shell** — not a second frontend. CSS in `src/static/css/mobile.css` (everything inside `@media (max-width: 640px)`), JS in `isMobile()`-gated branches in `src/static/js/app.js` (+ small hooks in `notes.js`). The desktop UI is the project's crown jewel and stays **byte-identical**.

## Why this shape (read before proposing a rewrite)

The obvious framing — "the app is unusable on phone, so we need a proper frontend, maybe React/Vite, and a cleaner front/back split" — was explored and **rejected on evidence**:

- **The front/back split already exists.** All domain logic sits behind the Flask `/api/*` blueprints, and `mcp_server/` already consumes that exact contract as an independent HTTP client over the `API_TOKEN` bearer. A new frontend would "unlock" a boundary we already have, so that argument for rewriting is void.
- **Chainlit was never the problem.** It only backs the Assistant tab, and its own React UI is already responsive. Keeping it costs nothing; only the shell chrome *around* the iframe needed to fit. "Escape Chainlit" is not a reason to rewrite.
- **The desktop-first part is the shell** (`index.html` + `app.js` + `style.css`): fixed-pixel sidebars, a 4-column board, hover-only affordances, modifier-click conventions, ~30 keyboard shortcuts.

So the actual problem was narrow, and a second frontend would have cost a duplicated client (feature drift), a JS build pipeline against the project's deliberate **no-build-step** ethos, and re-implementations of the FullCalendar / EasyMDE / board / mail clients. Progressive enhancement was the cheaper and lower-risk answer.

**A separate mobile app stays a documented escape hatch** if progressive enhancement ever hits a real UX ceiling — but re-argue it from evidence, not from the framing above.

## The invariant (do not break this)

*"Without tampering AT ALL with PC usability"* was the hard requirement, so it is enforced **structurally rather than by care**:

- Every mobile rule lives inside the one phone breakpoint. The only top-level rules in `mobile.css` are `display:none` defaults for elements that **do not exist in the desktop design** (the card action button, the master-detail back buttons, the space dropdown) plus `.mobile-sheet-*` styling, which matches nothing on a desktop page.
- Every mobile JS path is behind `isMobile()`, added as a *new* branch. Desktop code paths were never restructured — on PC the drag init, calendar config and click delegation run the same code as before.
- `body.is-mobile` is toggled reactively (`matchMedia` change listener) for anything that needs the state in JS rather than CSS.

Two failure modes to watch when extending: **a rule escaping the breakpoint**, and **structural selectors shifting** — `display:none` elements still count for `:first-child`/`:nth-child`, so injecting hidden nodes into desktop DOM can silently reflow it. Both were audited; keep auditing.

## Decisions worth knowing

- **The board swipes, it doesn't stack.** Full-width scroll-snap columns preserve the kanban mental model (four named columns you move between); a single stacked list would have dissolved it.
- **Drag is desktop-only on purpose.** Touch-dragging fights both the scroll-snap track and page scroll, so SortableJS is simply *not initialized* on phones. Status changes go through a per-card action sheet instead. This is why the mobile board needs no drag polish — the gesture is deliberately absent, not broken.
- **The action sheet is plain DOM, not a Bootstrap modal.** The shell's global Ctrl+Enter handler and several flows key off `.modal.show`; making the sheet a real modal would have entangled it with that plumbing for no benefit.
- **Modifier-click conventions have no touch equivalent**, so everything they express (done / freeze / advance / edit) is reachable from that sheet as visible buttons. Hover-revealed affordances are pinned visible on coarse pointers for the same reason.
- **Space filter is a dropdown on phone, single-select only.** With ~10 spaces the chip row ate most of the screen. Ctrl+click multi-space and Alt+click exclude stay desktop-only (KISS was the explicit ask), and picking from the dropdown clears exclusions. A filter built on desktop that the dropdown cannot express renders a disabled *"Multiple spaces"* entry — **the UI must not claim "All spaces" while the board is actually filtered**. One shared helper (`syncMobileSpaceSelect`) is called from each of the three chip renderers with an `onPick` mirroring that view's existing plain-click branch, so filter semantics are never duplicated.
- **Master-detail for Notes / Mail / Spaces**, because their fixed 260–380px sidebars have no phone equivalent. The detail overlay is reset on destination switch so you never land back in a stale editor.

## Caveats

- **`mobile.css` cascades on top of the older tablet breakpoints in `style.css` (768/900/992px), which still apply at phone widths.** This bit once: the 992px rule sets `.board { flex-wrap: wrap }`, which stacked the full-width columns vertically until the phone rule set `nowrap` explicitly. When a mobile layout misbehaves, look for an earlier breakpoint before debugging the new rule.
- The Assistant tab's *inside* is Chainlit's own responsive UI — we only fit the surrounding toolbar and hide the workspace drawer. Do not try to restyle the iframe's contents from here; `chat/public/simpler.css` is the seam.
- **PWA / installable / offline capture was deliberately deferred** (manifest + service worker + an offline capture queue). It is a strong fit for on-the-go ADHD capture and the natural next step, but it was scoped out, not forgotten.
- Keyboard shortcuts and the `#helpModal` table are desktop concerns and were left alone; if a mobile interaction ever changes a shortcut, the help table is still the single source of truth (see `CONTEXT.md`).

## Verifying a change here

The regression net for "PC is untouched" is a **pixel diff**: screenshot the desktop at several widths across every destination, before vs after, and require **0 differing pixels** (it has held for every change so far, including with 10 spaces seeded). Pair it with an interactive check of the desktop conventions the change is near — a static render can look identical while a handler is dead. On the mobile side, assert no horizontal overflow (`scrollWidth <= innerWidth`) per destination.

Two environment traps when driving the app headless: the shell's CDN assets (Bootstrap / FullCalendar / SortableJS / EasyMDE / Font Awesome) may be blocked by an egress policy — install the same packages from npm and route the CDN URLs to those local copies, or the board renders empty and the failure looks like a code bug. And a `goto` that only changes the URL hash does **not** reload, so the destination never switches; reload after navigating.
