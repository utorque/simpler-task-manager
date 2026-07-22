/* Assistant settings panel (issue 003.07).
 *
 * A transient Bootstrap modal opened from the Assistant tab subheader (or
 * the `,` shortcut while in the Assistant destination). Tabs: Model · Modes
 * · Skills · Prompt · Composition — all persisted to instance/assistant/
 * through /api/assistant/*, live without a restart. The modal overlays the
 * (persistent) workspace drawer; they never collide.
 */
(function () {
    'use strict';

    let state = null;          // last GET /api/assistant/settings payload
    let editingSkill = null;   // name of the skill open in the editor, or null
    let promptMDE = null;      // EasyMDE over the system-prompt textarea

    function el(id) { return document.getElementById(id); }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    async function api(method, url, body) {
        const options = { method, headers: {} };
        if (body !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
        const response = await fetch(url, options);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || `${method} ${url} failed (${response.status})`);
        }
        return payload;
    }

    function report(error) { alert(error.message || error); }

    // ===== String-list editors (models + reasoning levels) ==================

    function renderStringList(listId, items) {
        const list = el(listId);
        list.innerHTML = '';
        items.forEach((item, index) => {
            const row = document.createElement('li');
            row.className = 'list-group-item d-flex align-items-center py-1';
            row.innerHTML =
                `<span class="flex-grow-1">${escapeHtml(item)}` +
                (index === 0 ? ' <span class="badge bg-primary">default</span>' : '') +
                '</span>' +
                '<button class="btn btn-sm btn-link p-0 me-2" data-action="up" title="Move up">▲</button>' +
                '<button class="btn btn-sm btn-link p-0 me-2" data-action="down" title="Move down">▼</button>' +
                '<button class="btn btn-sm btn-link text-danger p-0" data-action="remove" title="Remove">✕</button>';
            row.querySelectorAll('button').forEach((button) => {
                button.addEventListener('click', () => {
                    const action = button.dataset.action;
                    if (action === 'remove') items.splice(index, 1);
                    if (action === 'up' && index > 0) {
                        [items[index - 1], items[index]] = [items[index], items[index - 1]];
                    }
                    if (action === 'down' && index < items.length - 1) {
                        [items[index + 1], items[index]] = [items[index], items[index + 1]];
                    }
                    renderStringList(listId, items);
                });
            });
            list.appendChild(row);
        });
    }

    function wireStringListEditor(listId, inputId, addId, saveId, url, key, items) {
        renderStringList(listId, items);
        el(addId).onclick = () => {
            const value = el(inputId).value.trim();
            if (!value || items.includes(value)) return;
            items.push(value);
            el(inputId).value = '';
            renderStringList(listId, items);
        };
        el(inputId).onkeydown = (event) => {
            if (event.key === 'Enter') { event.preventDefault(); el(addId).click(); }
        };
        el(saveId).onclick = async () => {
            try {
                const payload = await api('PUT', url, items);
                items.splice(0, items.length, ...payload[key]);
                renderStringList(listId, items);
            } catch (error) { report(error); }
        };
    }

    // ===== Skills manager ====================================================

    function renderSkills() {
        const container = el('assistantSkillsList');
        container.innerHTML = '';
        (state.skills || []).forEach((skill) => {
            const row = document.createElement('div');
            row.className = 'd-flex align-items-center border-bottom py-1 gap-2';
            const badge = skill.source === 'bundled'
                ? '<span class="badge bg-secondary">bundled</span>'
                : '<span class="badge bg-success">instance</span>';
            row.innerHTML =
                `<div class="flex-grow-1"><strong>${escapeHtml(skill.name)}</strong> ${badge}` +
                `<div class="small text-muted">${escapeHtml(skill.description)}</div></div>` +
                '<button class="btn btn-sm btn-outline-secondary" data-action="edit">Edit</button>' +
                (skill.source === 'instance'
                    ? '<button class="btn btn-sm btn-outline-danger" data-action="delete">Delete</button>'
                    : '');
            row.querySelector('[data-action="edit"]').addEventListener('click', () => openSkillEditor(skill));
            const deleteButton = row.querySelector('[data-action="delete"]');
            if (deleteButton) {
                deleteButton.addEventListener('click', async () => {
                    if (!confirm(`Delete skill “${skill.name}”?`)) return;
                    try {
                        await api('DELETE', `/api/assistant/skills/${encodeURIComponent(skill.name)}`);
                        await refresh();
                    } catch (error) { report(error); }
                });
            }
            container.appendChild(row);
        });
    }

    async function openSkillEditor(skill) {
        editingSkill = skill ? skill.name : null;
        el('assistantSkillEditor').style.display = '';
        el('assistantSkillName').value = skill ? skill.name : '';
        el('assistantSkillName').disabled = !!skill;
        el('assistantSkillDescription').value = skill ? skill.description : '';
        el('assistantSkillBody').value = '';
        if (skill) {
            // The list endpoint has no body; a bundled/instance SKILL.md body
            // is fetched lazily only when editing. Reuse the settings GET is
            // not enough — load via the skills root of the workspace API when
            // instance, else start from an empty body the save will fork.
            try {
                const response = await fetch(
                    `/api/workspace/files/skills/${encodeURIComponent(skill.name)}/SKILL.md`);
                if (response.ok) {
                    const text = await response.text();
                    el('assistantSkillBody').value = text.replace(/^---[\s\S]*?---\n?/, '');
                }
            } catch (error) { /* bundled skill: body starts empty, save forks it */ }
        }
    }

    function closeSkillEditor() {
        editingSkill = null;
        el('assistantSkillEditor').style.display = 'none';
    }

    async function saveSkill() {
        const name = el('assistantSkillName').value.trim();
        const description = el('assistantSkillDescription').value.trim();
        const body = el('assistantSkillBody').value;
        try {
            if (editingSkill) {
                await api('PUT', `/api/assistant/skills/${encodeURIComponent(editingSkill)}`,
                          { body, description });
            } else {
                await api('POST', '/api/assistant/skills', { name, description, body });
            }
            closeSkillEditor();
            await refresh();
        } catch (error) { report(error); }
    }

    // ===== Prompt editor =====================================================
    // Same convention as the notes editor: the prompt opens rendered (EasyMDE
    // preview mode) and a double-click on the preview drops into edit mode.

    function setPromptPreview(on) {
        if (!promptMDE) return;
        if (promptMDE.isPreviewActive() !== on) promptMDE.togglePreview();
    }

    function initPromptEditor() {
        if (promptMDE || typeof EasyMDE === 'undefined') return;
        promptMDE = new EasyMDE({
            element: el('assistantPromptBody'),
            autosave: { enabled: false },
            autoDownloadFontAwesome: false,
            status: false,
            spellChecker: false,
            // Side-by-side must stay inside the modal, not take over the whole
            // screen (EasyMDE defaults to fullscreen side-by-side).
            sideBySideFullscreen: false,
            minHeight: '360px',
            // simpler:/generic: section markers are HTML comments — invisible
            // once rendered. Show them as inline code so preview mode still
            // exposes where the context-conditional blocks start and end.
            previewRender: function (plainText) {
                return this.parent.markdown(plainText.replace(
                    /<!--\s*(?:simpler|generic):(?:start|end)\s*-->/g,
                    (marker) => '`' + marker + '`'));
            },
            toolbar: [
                'bold', 'italic', '|',
                'heading-1', 'heading-2', 'heading-3', '|',
                'quote', 'unordered-list', 'ordered-list', '|',
                'code', 'horizontal-rule', '|',
                'link', '|',
                'preview', 'side-by-side', '|', 'guide',
            ],
        });
        // Preview → edit on double-click; links keep their normal behavior and
        // the side-by-side live preview (.editor-preview-side) is untouched.
        el('astab-prompt').addEventListener('dblclick', (event) => {
            if (!promptMDE.isPreviewActive()) return;
            if (event.target.closest('a')) return;
            if (!event.target.closest('.editor-preview-full')) return;
            setPromptPreview(false);
            promptMDE.codemirror.refresh();
            promptMDE.codemirror.focus();
        });
        // The editor is built while its tab-pane is hidden, so CodeMirror
        // measures a zero height — remeasure when the Prompt tab is shown.
        const tab = document.querySelector('[data-bs-target="#astab-prompt"]');
        if (tab) tab.addEventListener('shown.bs.tab', () => promptMDE.codemirror.refresh());
    }

    function renderPrompt() {
        const prompt = state.system_prompt || {};
        el('assistantPromptSource').innerHTML = prompt.source === 'instance'
            ? `Editing the <strong>instance override</strong> (last saved ${escapeHtml(prompt.last_modified || '?')})`
            : 'Showing the <strong>shipped default</strong> — saving creates an instance override that survives upgrades.';
        const body = prompt.body || '';
        initPromptEditor();
        if (!promptMDE) { el('assistantPromptBody').value = body; return; }
        // The preview pane only re-renders on toggle: write the buffer with
        // preview off, then flip it back on for a non-empty prompt.
        setPromptPreview(false);
        promptMDE.value(body);
        setPromptPreview(!!body.trim());
    }

    function promptBody() {
        return promptMDE ? promptMDE.value() : el('assistantPromptBody').value;
    }

    async function savePrompt() {
        try {
            await api('PUT', '/api/assistant/system-prompt', { body: promptBody() });
            await refresh();
        } catch (error) { report(error); }
    }

    async function resetPrompt() {
        if (!confirm('Reset the system prompt to the shipped default?')) return;
        try {
            await api('DELETE', '/api/assistant/system-prompt');
            await refresh();
        } catch (error) { report(error); }
    }

    // ===== Composition viewer ================================================

    const LAYER_LABELS = {
        base: 'Base prompt',
        datetime: 'Current date & time',
        spaces_guidance: 'Spaces guidance',
        tools: 'Tools',
        skills: 'Skills',
    };

    function renderComposition() {
        const container = el('assistantCompositionLayers');
        container.innerHTML = '';
        ((state.composition || {}).layers || []).forEach((layer) => {
            const card = document.createElement('details');
            card.className = 'border rounded p-2 mb-2';
            let meta = '';
            if (layer.kind === 'base') {
                meta = `${escapeHtml(layer.name)} · last modified ${escapeHtml(layer.last_modified || '?')}`;
            } else if (layer.sources) {
                meta = layer.sources.length ? `sources: ${escapeHtml(layer.sources.join(', '))}` : 'not configured';
            } else if (layer.items) {
                meta = layer.items.length + ' item(s): ' + escapeHtml(layer.items.join(', '));
            }
            card.innerHTML =
                `<summary><strong>${escapeHtml(LAYER_LABELS[layer.kind] || layer.kind)}</strong>` +
                (meta ? ` <span class="text-muted small">— ${meta}</span>` : '') + '</summary>' +
                `<pre class="small mt-2 mb-0" style="white-space:pre-wrap;">${escapeHtml(layer.text)}</pre>`;
            container.appendChild(card);
        });
    }

    // ===== Load + open =======================================================

    async function refresh() {
        state = await api('GET', '/api/assistant/settings');
        wireStringListEditor('assistantModelList', 'assistantModelInput',
                             'assistantModelAdd', 'assistantModelsSave',
                             '/api/assistant/models', 'models', state.models);
        wireStringListEditor('assistantReasoningList', 'assistantReasoningInput',
                             'assistantReasoningAdd', 'assistantReasoningSave',
                             '/api/assistant/reasoning-levels', 'reasoning_levels',
                             state.reasoning_levels);
        renderSkills();
        renderPrompt();
        renderComposition();
    }

    async function open() {
        const modalElement = el('assistantSettingsModal');
        if (!modalElement) return;
        try {
            await refresh();
        } catch (error) { report(error); return; }
        closeSkillEditor();
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }

    document.addEventListener('DOMContentLoaded', () => {
        const button = el('assistantSettingsBtn');
        if (!button) return;
        button.addEventListener('click', open);
        el('assistantSkillNew').addEventListener('click', () => openSkillEditor(null));
        el('assistantSkillCancel').addEventListener('click', closeSkillEditor);
        el('assistantSkillSave').addEventListener('click', saveSkill);
        el('assistantPromptSave').addEventListener('click', savePrompt);
        el('assistantPromptReset').addEventListener('click', resetPrompt);

        // `,` opens the settings while in the Assistant destination (kept out
        // of inputs/modals — same guards as app.js's plain-letter shortcuts).
        document.addEventListener('keydown', (event) => {
            if (event.key !== ',' || event.ctrlKey || event.metaKey || event.altKey) return;
            const target = event.target;
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
                           || target.isContentEditable)) return;
            if (document.querySelector('.modal.show')) return;
            const view = document.getElementById('view-assistant');
            if (!view || view.style.display === 'none') return;
            event.preventDefault();
            open();
        });
    });

    window.AssistantSettings = { open };
})();
