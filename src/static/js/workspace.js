/* WorkspaceView (issue 003.09): the assistant-only right drawer browsing the
 * assistant-workspace volume through /api/workspace/* (issue 003.08).
 *
 * Vanilla JS following the NotesView/MailView conventions: one class, DOM
 * injected into the drawer container, lazy tree loading per folder expand,
 * HTML5 drag-drop for uploads and moves, EasyMDE for inline .md edits
 * (autosave on blur). Open/closed + last path persist in localStorage.
 * The drawer is persistent; the Assistant settings modal simply overlays it.
 */
(function () {
    'use strict';

    const ROOT = 'workspace';
    const STORAGE_OPEN = 'workspaceDrawerOpen';
    const STORAGE_PATH = 'workspaceDrawerPath';

    class WorkspaceView {
        constructor(drawer) {
            this.drawer = drawer;
            this.currentPath = localStorage.getItem(STORAGE_PATH) || '';
            this.editor = null;        // EasyMDE instance while a file is open
            this.editingPath = null;
            this.initialized = false;
        }

        // ===== Plumbing ======================================================

        async api(method, url, body, isForm) {
            const options = { method };
            if (body !== undefined && !isForm) {
                options.headers = { 'Content-Type': 'application/json' };
                options.body = JSON.stringify(body);
            } else if (isForm) {
                options.body = body;
            }
            const response = await fetch(url, options);
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.error || `${method} ${url} failed`);
            }
            return response;
        }

        async fetchTree(path) {
            const query = new URLSearchParams({ root: ROOT, path: path || '' });
            const response = await this.api('GET', `/api/workspace/tree?${query}`);
            return response.json();
        }

        join(dir, name) { return dir ? `${dir}/${name}` : name; }

        // ===== Drawer toggle =================================================

        isOpen() { return !this.drawer.classList.contains('d-none'); }

        async toggle(force) {
            const open = force !== undefined ? force : !this.isOpen();
            this.drawer.classList.toggle('d-none', !open);
            localStorage.setItem(STORAGE_OPEN, open ? '1' : '0');
            if (open && !this.initialized) await this.init();
            else if (open) await this.refresh();
        }

        async init() {
            this.initialized = true;
            this.drawer.innerHTML =
                '<div class="workspace-drawer-header">' +
                '  <div class="workspace-breadcrumb" id="workspaceBreadcrumb"></div>' +
                '  <div class="workspace-actions">' +
                '    <button class="btn btn-sm btn-link p-0 me-2" id="workspaceNewFolder" title="New folder"><i class="fas fa-folder-plus"></i></button>' +
                '    <label class="btn btn-sm btn-link p-0 me-2 mb-0" title="Upload files"><i class="fas fa-upload"></i>' +
                '      <input type="file" id="workspaceUploadInput" multiple hidden></label>' +
                '    <button class="btn btn-sm btn-link p-0" id="workspaceRefresh" title="Refresh"><i class="fas fa-rotate"></i></button>' +
                '  </div>' +
                '</div>' +
                '<div class="workspace-tree" id="workspaceTree"></div>' +
                '<div class="workspace-editor d-none" id="workspaceEditor">' +
                '  <div class="workspace-editor-header">' +
                '    <button class="btn btn-sm btn-link p-0 me-2" id="workspaceEditorBack" title="Back to files"><i class="fas fa-arrow-left"></i></button>' +
                '    <span class="small text-truncate" id="workspaceEditorName"></span>' +
                '  </div>' +
                '  <textarea id="workspaceEditorArea"></textarea>' +
                '</div>' +
                '<div class="workspace-drophint small text-muted">Drop files here to upload</div>';

            this.drawer.querySelector('#workspaceNewFolder')
                .addEventListener('click', () => this.createFolder());
            this.drawer.querySelector('#workspaceRefresh')
                .addEventListener('click', () => this.refresh());
            this.drawer.querySelector('#workspaceEditorBack')
                .addEventListener('click', () => this.closeEditor());
            this.drawer.querySelector('#workspaceUploadInput')
                .addEventListener('change', (event) => {
                    this.uploadFiles(event.target.files, this.currentPath);
                    event.target.value = '';
                });

            // Whole-drawer drop target for uploads (into the current dir).
            this.drawer.addEventListener('dragover', (event) => {
                if (event.dataTransfer.types.includes('Files')) {
                    event.preventDefault();
                    this.drawer.classList.add('workspace-dragover');
                }
            });
            this.drawer.addEventListener('dragleave', () => {
                this.drawer.classList.remove('workspace-dragover');
            });
            this.drawer.addEventListener('drop', (event) => {
                this.drawer.classList.remove('workspace-dragover');
                if (event.dataTransfer.files.length) {
                    event.preventDefault();
                    this.uploadFiles(event.dataTransfer.files, this.currentPath);
                }
            });

            await this.refresh();
        }

        // ===== Tree ==========================================================

        renderBreadcrumb() {
            const crumb = this.drawer.querySelector('#workspaceBreadcrumb');
            crumb.innerHTML = '';
            const parts = this.currentPath ? this.currentPath.split('/') : [];
            const mk = (label, path) => {
                const anchor = document.createElement('a');
                anchor.href = '#';
                anchor.textContent = label;
                anchor.addEventListener('click', (event) => {
                    event.preventDefault();
                    this.openDir(path);
                });
                return anchor;
            };
            crumb.appendChild(mk('workspace', ''));
            parts.forEach((part, index) => {
                crumb.appendChild(document.createTextNode(' / '));
                crumb.appendChild(mk(part, parts.slice(0, index + 1).join('/')));
            });
        }

        async openDir(path) {
            this.currentPath = path;
            localStorage.setItem(STORAGE_PATH, path);
            await this.refresh();
        }

        async refresh() {
            if (!this.initialized) return;
            this.closeEditor();
            this.renderBreadcrumb();
            const tree = this.drawer.querySelector('#workspaceTree');
            let payload;
            try {
                payload = await this.fetchTree(this.currentPath);
            } catch (error) {
                if (this.currentPath) { this.currentPath = ''; return this.refresh(); }
                tree.innerHTML = `<div class="small text-danger p-2">${error.message}</div>`;
                return;
            }
            tree.innerHTML = '';
            tree.appendChild(this.renderEntries(payload.entries, this.currentPath));
            if (!payload.entries.length) {
                tree.innerHTML = '<div class="small text-muted p-2">(empty)</div>';
            }
        }

        renderEntries(entries, dirPath) {
            const list = document.createElement('div');
            entries.forEach((entry) => list.appendChild(this.renderNode(entry, dirPath)));
            return list;
        }

        renderNode(entry, dirPath) {
            const relPath = this.join(dirPath, entry.name);
            const node = document.createElement('div');
            node.className = 'workspace-node';
            const row = document.createElement('div');
            row.className = 'workspace-row d-flex align-items-center';
            row.draggable = true;

            const icon = entry.type === 'dir' ? 'fa-folder' :
                (entry.name.endsWith('.md') ? 'fa-file-lines' : 'fa-file');
            const label = document.createElement('span');
            label.className = 'workspace-name flex-grow-1 text-truncate';
            label.innerHTML = `<i class="fas ${icon} me-1"></i>`;
            label.appendChild(document.createTextNode(entry.name));
            row.appendChild(label);

            const actions = document.createElement('span');
            actions.className = 'workspace-row-actions';
            if (entry.type === 'file') {
                const download = document.createElement('a');
                download.href = entry.url;
                download.setAttribute('download', entry.name);
                download.title = 'Download';
                download.innerHTML = '<i class="fas fa-download"></i>';
                download.addEventListener('click', (e) => e.stopPropagation());
                actions.appendChild(download);
            }
            const remove = document.createElement('a');
            remove.href = '#';
            remove.title = 'Delete';
            remove.innerHTML = '<i class="fas fa-trash"></i>';
            remove.addEventListener('click', async (event) => {
                event.preventDefault();
                event.stopPropagation();
                await this.deleteNode(relPath, entry.type);
            });
            actions.appendChild(remove);
            row.appendChild(actions);

            // Click: dirs expand/collapse inline; .md/.txt open the editor.
            let childBox = null;
            row.addEventListener('click', async () => {
                if (entry.type === 'dir') {
                    if (childBox) { childBox.remove(); childBox = null; return; }
                    const payload = await this.fetchTree(relPath);
                    childBox = document.createElement('div');
                    childBox.className = 'workspace-children';
                    childBox.appendChild(this.renderEntries(payload.entries, relPath));
                    if (!payload.entries.length) {
                        childBox.innerHTML = '<div class="small text-muted ps-3">(empty)</div>';
                    }
                    node.appendChild(childBox);
                } else if (/\.(md|txt)$/i.test(entry.name)) {
                    this.openEditor(relPath, entry.url);
                }
            });

            // Drag source (move) — files land on folder rows or the breadcrumb.
            // The same drag also crosses into the assistant iframe: the
            // text/plain flavour is the workspace-relative path the model
            // works with, pasted into the composer by simpler-bridge.js
            // (folders keep a trailing slash so the intent reads clearly).
            row.addEventListener('dragstart', (event) => {
                event.dataTransfer.setData('application/x-workspace-path', relPath);
                event.dataTransfer.setData(
                    'text/plain', entry.type === 'dir' ? `${relPath}/` : relPath);
                event.dataTransfer.effectAllowed = 'copyMove';
                event.stopPropagation();
            });
            if (entry.type === 'dir') {
                row.addEventListener('dragover', (event) => {
                    if (event.dataTransfer.types.includes('application/x-workspace-path')
                        || event.dataTransfer.types.includes('Files')) {
                        event.preventDefault();
                        event.stopPropagation();
                        row.classList.add('workspace-droptarget');
                    }
                });
                row.addEventListener('dragleave', () => row.classList.remove('workspace-droptarget'));
                row.addEventListener('drop', async (event) => {
                    row.classList.remove('workspace-droptarget');
                    event.stopPropagation();
                    const from = event.dataTransfer.getData('application/x-workspace-path');
                    if (from) {
                        event.preventDefault();
                        await this.moveNode(from, this.join(relPath, from.split('/').pop()));
                    } else if (event.dataTransfer.files.length) {
                        event.preventDefault();
                        await this.uploadFiles(event.dataTransfer.files, relPath);
                    }
                });
            }

            node.appendChild(row);
            return node;
        }

        // ===== Mutations =====================================================

        async createFolder() {
            const name = prompt('New folder name:');
            if (!name) return;
            try {
                await this.api('POST', '/api/workspace/mkdir',
                               { root: ROOT, path: this.join(this.currentPath, name) });
                await this.refresh();
            } catch (error) { alert(error.message); }
        }

        async uploadFiles(fileList, targetDir) {
            try {
                for (const file of Array.from(fileList)) {
                    const form = new FormData();
                    form.append('root', ROOT);
                    form.append('path', targetDir || '');
                    form.append('file', file, file.name);
                    await this.api('POST', '/api/workspace/upload', form, true);
                }
                await this.refresh();
            } catch (error) { alert(error.message); }
        }

        async deleteNode(relPath, type) {
            const what = type === 'dir' ? 'folder (and everything in it)' : 'file';
            if (!confirm(`Delete this ${what}?\n${relPath}`)) return;
            try {
                const query = new URLSearchParams({ root: ROOT, path: relPath });
                await this.api('DELETE', `/api/workspace/file?${query}`);
                await this.refresh();
            } catch (error) { alert(error.message); }
        }

        async moveNode(fromRel, toRel) {
            if (fromRel === toRel || toRel.startsWith(fromRel + '/')) return;
            try {
                await this.api('POST', '/api/workspace/move',
                               { root: ROOT, from: fromRel, to: toRel });
                await this.refresh();
            } catch (error) { alert(error.message); }
        }

        // ===== Inline markdown editor =======================================

        async openEditor(relPath, url) {
            const box = this.drawer.querySelector('#workspaceEditor');
            const tree = this.drawer.querySelector('#workspaceTree');
            let content = '';
            try {
                content = await (await this.api('GET', url)).text();
            } catch (error) { alert(error.message); return; }
            this.editingPath = relPath;
            this.drawer.querySelector('#workspaceEditorName').textContent = relPath;
            tree.classList.add('d-none');
            box.classList.remove('d-none');
            this.editor = new EasyMDE({
                element: this.drawer.querySelector('#workspaceEditorArea'),
                initialValue: content,
                autoDownloadFontAwesome: false,
                spellChecker: false,
                status: false,
                toolbar: false,
                minHeight: '200px',
            });
            this.editor.codemirror.on('blur', () => this.saveEditor());
        }

        async saveEditor() {
            if (!this.editor || this.editingPath === null) return;
            try {
                await this.api('PUT', '/api/workspace/file', {
                    root: ROOT, path: this.editingPath,
                    content: this.editor.value(),
                });
            } catch (error) { alert(error.message); }
        }

        closeEditor() {
            if (!this.editor) return;
            this.saveEditor();
            this.editor.toTextArea();
            this.editor = null;
            this.editingPath = null;
            this.drawer.querySelector('#workspaceEditor').classList.add('d-none');
            this.drawer.querySelector('#workspaceTree').classList.remove('d-none');
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const drawer = document.getElementById('workspaceDrawer');
        const button = document.getElementById('workspaceDrawerBtn');
        if (!drawer || !button) return;
        const view = new WorkspaceView(drawer);
        window.workspaceView = view;

        button.addEventListener('click', () => view.toggle());

        // Restore last open state when the shell loads (the drawer lives
        // inside #view-assistant, so it only shows when that tab is active).
        if (localStorage.getItem(STORAGE_OPEN) === '1') view.toggle(true);

        // `W` toggles the drawer while in the Assistant destination.
        document.addEventListener('keydown', (event) => {
            if ((event.key !== 'w' && event.key !== 'W') || event.ctrlKey
                || event.metaKey || event.altKey || event.shiftKey) return;
            const target = event.target;
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
                           || target.isContentEditable)) return;
            if (document.querySelector('.modal.show')) return;
            const viewAssistant = document.getElementById('view-assistant');
            if (!viewAssistant || viewAssistant.style.display === 'none') return;
            event.preventDefault();
            view.toggle();
        });
    });

    window.WorkspaceView = WorkspaceView;
})();
