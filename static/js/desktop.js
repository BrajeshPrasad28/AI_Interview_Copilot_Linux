        let socket = null;
        let currentMode = 'qa_testing';
        let isMicListening = false;
        let recognition = null;
        let speechDebounceTimer = null;
        let audioContext = null;
        let analyser = null;

        const viewHub = document.getElementById('view-hub');
        const viewCopilot = document.getElementById('view-copilot');
        const content = document.getElementById('content');
        const answersFeed = document.getElementById('answers-feed');
        const statusBanner = document.getElementById('status-banner');
        const statusBannerText = document.getElementById('status-banner-text');
        const dot = document.getElementById('dot');
        const btnMic = document.getElementById('btn-mic');
        const micLabel = document.getElementById('mic-label');
        const liveTranscript = document.getElementById('live-transcript');
        const statusInfo = document.getElementById('status-info');
        const modeSelect = document.getElementById('mode-select');
        const manualInput = document.getElementById('manual-input');
        const footerMode = document.getElementById('footer-mode');

        // Pairing Token extraction
        const urlParams = new URLSearchParams(window.location.search);
        let pairingToken = urlParams.get('token') || (document.cookie.match(/(?:^|;\s*)pairing_token=([^;]+)/) || [])[1] || window.INITIAL_PAIRING_TOKEN || '';
        let currentVadMode = 'smart';
        let pendingPreferences = {};
        let preferencesSaveTimer = null;

        function formatTo12HourTime(ts) {
            if (!ts) return '';
            try {
                const parts = String(ts).trim().split(/\s+/);
                if (parts.length === 2) {
                    const datePart = parts[0];
                    const timeParts = parts[1].split(':');
                    if (timeParts.length >= 2) {
                        let hours = parseInt(timeParts[0], 10);
                        const minutes = timeParts[1];
                        const ampm = hours >= 12 ? 'PM' : 'AM';
                        hours = hours % 12;
                        hours = hours ? hours : 12;
                        const hoursStr = String(hours).padStart(2, '0');
                        return `${datePart} ${hoursStr}:${minutes} ${ampm}`;
                    }
                }
                const d = new Date(ts);
                if (!isNaN(d.getTime())) {
                    const yyyy = d.getFullYear();
                    const mm = String(d.getMonth() + 1).padStart(2, '0');
                    const dd = String(d.getDate()).padStart(2, '0');
                    let h = d.getHours();
                    const m = String(d.getMinutes()).padStart(2, '0');
                    const ampm = h >= 12 ? 'PM' : 'AM';
                    h = h % 12 || 12;
                    const hStr = String(h).padStart(2, '0');
                    return `${yyyy}-${mm}-${dd} ${hStr}:${m} ${ampm}`;
                }
            } catch (_) {}
            return ts;
        }

        function validateUserName(name) {
            const trimmed = (name || '').trim();
            if (!trimmed) {
                return { valid: false, error: 'User Name is mandatory (cannot be empty).' };
            }
            if (trimmed.length < 3) {
                return { valid: false, error: 'User Name must be at least 3 characters.' };
            }
            if (trimmed.length > 50) {
                return { valid: false, error: 'User Name cannot exceed 50 characters.' };
            }
            return { valid: true, error: '' };
        }

        function validateEmailAddress(email) {
            const trimmed = (email || '').trim();
            if (!trimmed) {
                return { valid: false, error: 'Email Address is mandatory (cannot be empty).' };
            }
            const emailRegex = /^[^\s@]+@[^\s@]+\.[a-zA-Z]{2,}$/;
            if (!emailRegex.test(trimmed)) {
                return { valid: false, error: 'Please enter a valid email address (e.g. name@example.com).' };
            }
            return { valid: true, error: '' };
        }

        function formatAndValidatePhone(rawPhone) {
            let val = String(rawPhone || '');
            let digitsOnly = val.replace(/^\+91\s*/, '').replace(/\D/g, '');
            if (digitsOnly.length > 10) {
                digitsOnly = digitsOnly.slice(0, 10);
            }
            const formatted = '+91 ' + digitsOnly;
            if (!digitsOnly) {
                return { valid: false, formatted: formatted, digits: '', error: 'Phone Number is mandatory (+91 and 10 digits).' };
            }
            if (digitsOnly.length < 10) {
                return { valid: false, formatted: formatted, digits: digitsOnly, error: `Phone number must have 10 digits (${digitsOnly.length}/10 entered).` };
            }
            return { valid: true, formatted: formatted, digits: digitsOnly, error: '' };
        }

        function setValidationUI(field, isValid, errorMsg) {
            const tick = document.getElementById(`profile-${field}-valid`);
            const errEl = document.getElementById(`profile-${field}-error`);
            const inputEl = document.getElementById(`profile-${field}`);
            if (tick) {
                tick.style.display = isValid ? 'inline-flex' : 'none';
            }
            if (errEl) {
                if (isValid || !errorMsg) {
                    errEl.style.display = 'none';
                    errEl.textContent = '';
                } else {
                    errEl.style.display = 'flex';
                    errEl.textContent = errorMsg;
                }
            }
            if (inputEl) {
                if (isValid) {
                    inputEl.style.borderColor = 'rgba(16, 185, 129, 0.45)';
                } else if (errorMsg) {
                    inputEl.style.borderColor = 'rgba(239, 68, 68, 0.6)';
                } else {
                    inputEl.style.borderColor = '';
                }
            }
        }

        function setResumeValidationUI(hasResume) {
            const tick = document.getElementById('profile-resume-valid');
            const errEl = document.getElementById('profile-resume-error');
            if (tick) {
                tick.style.display = hasResume ? 'inline-flex' : 'none';
            }
            if (errEl) {
                if (hasResume) {
                    errEl.style.display = 'none';
                    errEl.textContent = '';
                } else {
                    errEl.style.display = 'flex';
                    errEl.textContent = 'Resume upload is mandatory. Please upload your PDF resume.';
                }
            }
        }

        function applyPreference(key, value) {
            const root = document.documentElement;
            if (key === 'profile_name') {
                const el = document.getElementById('profile-name');
                if (el) el.value = value || '';
                const creditName = document.getElementById('credit-user-name');
                if (creditName) creditName.textContent = value || 'User';
                const v = validateUserName(value);
                setValidationUI('name', v.valid, v.error);
            } else if (key === 'profile_email') {
                const emailEl = document.getElementById('profile-email');
                if (emailEl) emailEl.value = value || '';
                const creditEmail = document.getElementById('credit-user-email');
                if (creditEmail) creditEmail.textContent = value || 'user@example.com';
                const v = validateEmailAddress(value);
                setValidationUI('email', v.valid, v.error);
            } else if (key === 'profile_phone') {
                const phoneEl = document.getElementById('profile-phone');
                if (phoneEl) {
                    const v = formatAndValidatePhone(value || '+91 ');
                    phoneEl.value = v.formatted;
                    setValidationUI('phone', v.valid, v.error);
                }
            } else if (key === 'background_opacity') {
                const opacity = Number(value);
                const bgAlpha = opacity / 100;
                root.style.setProperty('--window-bg-opacity', bgAlpha);
                root.style.setProperty('--header-background', `rgba(0, 0, 0, ${bgAlpha})`);
                root.style.setProperty('--surface-header', `rgba(0, 0, 0, ${bgAlpha})`);
                root.style.setProperty('--surface-control', `rgba(0, 0, 0, ${bgAlpha})`);
                root.style.setProperty('--main-content-background', `rgba(0, 0, 0, ${bgAlpha})`);
                root.style.setProperty('--card-background', `rgba(255, 255, 255, ${bgAlpha * 0.05})`);
                root.style.setProperty('--input-background', `rgba(0, 0, 0, ${bgAlpha * 0.38})`);
                root.style.setProperty('--input-focus-background', `rgba(0, 0, 0, ${bgAlpha * 0.63})`);
                root.style.setProperty('--button-background', `rgba(0, 0, 0, ${bgAlpha * 0.63})`);
                root.style.setProperty('--scrollbar-background', `rgba(0, 0, 0, ${bgAlpha * 0.5})`);
                const slider = document.getElementById('background-opacity');
                if (slider) {
                    slider.value = value;
                    const valOut = document.getElementById('background-opacity-value');
                    if (valOut) valOut.textContent = `${value}%`;
                    slider.setAttribute('aria-valuetext', `${value}% opaque`);
                }
                document.querySelectorAll('.quick-opacity-range').forEach(s => {
                    s.value = value;
                });
                if (window.pywebview && window.pywebview.api && window.pywebview.api.set_opacity) {
                    const nativeAlpha = Math.max(40, Math.min(255, Math.round((opacity / 100) * 255)));
                    window.pywebview.api.set_opacity(nativeAlpha);
                }
            } else if (key === 'font_opacity') {
                const fontAlpha = Number(value) / 100;
                root.style.setProperty('--answer-text-opacity', fontAlpha);
                root.style.setProperty('--text-color', `rgba(229, 229, 231, ${fontAlpha})`);
                const slider = document.getElementById('font-opacity');
                if (slider) {
                    slider.value = value;
                    const valOut = document.getElementById('font-opacity-value');
                    if (valOut) valOut.textContent = `${value}%`;
                }
            } else if (key === 'response_font_size') {
                root.style.setProperty('--response-font-size', `${value}px`);
                document.getElementById('response-font-size').value = value;
                document.getElementById('response-font-size-value').textContent = `${value} px`;
            } else if (key === 'show_screen_capture_button') {
                document.getElementById('show-screen-capture-button').checked = Boolean(value);
                const snipButton = document.getElementById('btn-snip');
                if (snipButton) snipButton.style.display = value ? '' : 'none';
            } else if (key === 'screen_quality') {
                document.getElementById('screen-quality').value = String(value);
            } else if (key === 'neural_vad_enabled') {
                document.getElementById('neural-vad-enabled').checked = Boolean(value);
            } else if (key === 'vad_mode') {
                currentVadMode = value;
                document.getElementById('vad-mode').value = value;
            } else if (key === 'google_search_enabled') {
                document.getElementById('google-search-enabled').checked = Boolean(value);
            } else if (key === 'custom_instructions') {
                const ciEl = document.getElementById('custom-instructions');
                if (ciEl) {
                    const truncated = (value || '').slice(0, 100);
                    ciEl.value = truncated;
                    const counter = document.getElementById('custom-instructions-counter');
                    if (counter) counter.textContent = `${truncated.length} / 100`;
                }
            }
        }

        async function loadProfileSettings() {
            try {
                const response = await fetch('/api/settings', { headers: { 'X-Pairing-Token': pairingToken } });
                if (!response.ok) throw new Error('Could not load settings.');
                const settings = await response.json();
                Object.keys(settings).forEach(key => applyPreference(key, settings[key]));

                // Run validation on all fields
                const nameVal = validateUserName(settings.profile_name);
                setValidationUI('name', nameVal.valid, nameVal.error);

                const emailVal = validateEmailAddress(settings.profile_email);
                setValidationUI('email', emailVal.valid, emailVal.error);

                const phoneVal = formatAndValidatePhone(settings.profile_phone || '+91 ');
                setValidationUI('phone', phoneVal.valid, phoneVal.error);

                if (settings.has_resume) {
                    updateDesktopResumeUI(true, settings.resume_filename, settings.resume ? settings.resume.length : 0);
                    setResumeBadge(`Active (${settings.resume_filename || 'Resume'})`, settings.resume_filename);
                    const badge = document.getElementById('resume-status-badge');
                    if (badge) badge.style.color = '#10b981';
                    setResumeValidationUI(true);
                } else {
                    updateDesktopResumeUI(false);
                    setResumeBadge('No Resume Uploaded', '');
                    const badge = document.getElementById('resume-status-badge');
                    if (badge) badge.style.color = 'var(--text-secondary)';
                    setResumeValidationUI(false);
                }
                updateLoopbackUI(settings.loopback_active);
            } catch (error) {
                console.warn('Settings could not be loaded:', error);
            }
        }

        function queuePreferenceSave(key, value) {
            pendingPreferences[key] = value;
            applyPreference(key, value);
            const status = document.getElementById('profile-settings-status');
            if (status) status.textContent = 'Saving settings…';
            clearTimeout(preferencesSaveTimer);
            preferencesSaveTimer = setTimeout(async () => {
                const changes = pendingPreferences;
                pendingPreferences = {};
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Pairing-Token': pairingToken },
                        body: JSON.stringify(changes)
                    });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.detail || 'Settings could not be saved.');
                    if (Object.prototype.hasOwnProperty.call(changes, 'vad_mode')) {
                        currentVadMode = changes.vad_mode;
                        updateLoopbackUI(result.loopback_active);
                    }
                    if (status) status.textContent = 'Settings saved automatically.';
                } catch (error) {
                    if (Object.prototype.hasOwnProperty.call(changes, 'google_search_enabled')) {
                        applyPreference('google_search_enabled', false);
                    }
                    if (status) status.textContent = error.message;
                }
            }, 400);
        }

        function setHubPanel(panel) {
            const hubBody = document.querySelector('.hub-body');
            hubBody.classList.remove('profile-settings-open', 'customize-settings-open', 'history-open', 'notes-open', 'credits-open', 'help-open');
            if (panel) hubBody.classList.add(`${panel}-open`);
            const selectedNavId = {
                'profile-settings': 'profile-nav-button',
                'customize-settings': 'customize-nav-button',
                notes: 'notes-nav-button',
                history: 'history-nav-button',
                credits: 'credits-nav-button',
                help: 'help-nav-button',
                '': 'home-nav-button'
            }[panel];
            document.querySelectorAll('.sidebar-action[id]').forEach(button => {
                const selected = button.id === selectedNavId;
                button.classList.toggle('sidebar-action-active', selected);
                if (selected) button.setAttribute('aria-current', 'page');
                else button.removeAttribute('aria-current');
            });
        }

        function openProfileSettings() {
            setHubPanel('profile-settings');
            loadProfileSettings();
        }

        function openCustomizeSettings() {
            setHubPanel('customize-settings');
            const bgSlider = document.getElementById('background-opacity');
            const quickSlider = document.querySelector('.quick-opacity-range');
            const bgVal = document.getElementById('background-opacity-value');
            if (bgSlider && quickSlider && quickSlider.value) {
                bgSlider.value = quickSlider.value;
                if (bgVal) bgVal.textContent = `${quickSlider.value}%`;
                bgSlider.setAttribute('aria-valuetext', `${quickSlider.value}% opaque`);
            }
            loadProfileSettings();
        }

        function openHelpView() {
            setHubPanel('help');
        }

        function showDashboard() {
            setHubPanel('');
        }

        function formatHistoryTimestamp(value) {
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
        }

        async function loadSessionHistory() {
            const list = document.getElementById('history-session-list');
            list.replaceChildren(Object.assign(document.createElement('p'), { className: 'history-empty', textContent: 'Loading session history...' }));
            try {
                const response = await fetch('/api/history', { headers: { 'X-Pairing-Token': pairingToken } });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Could not load session history.');
                list.replaceChildren();
                if (!data.sessions || data.sessions.length === 0) {
                    list.append(Object.assign(document.createElement('p'), { className: 'history-empty', textContent: 'No saved Q&A sessions yet.' }));
                    return;
                }
                data.sessions.forEach((session, index) => list.append(createHistorySessionCard(session, index)));
            } catch (error) {
                list.replaceChildren(Object.assign(document.createElement('p'), { className: 'history-empty', textContent: error.message }));
            }
        }

        function createHistorySessionCard(session, index) {
            const article = document.createElement('article');
            article.className = 'history-session';
            const header = document.createElement('div');
            header.className = 'history-session-header';
            const expand = document.createElement('button');
            expand.type = 'button';
            expand.className = 'history-expand';
            expand.setAttribute('aria-expanded', 'false');
            const arrow = Object.assign(document.createElement('span'), { className: 'history-arrow', textContent: '›' });
            const summary = document.createElement('div');
            summary.className = 'history-summary';
            const meta = document.createElement('div');
            meta.className = 'history-session-meta';
            meta.append(
                Object.assign(document.createElement('span'), { className: 'history-session-name', textContent: session.user_name || 'User' }),
                Object.assign(document.createElement('span'), { textContent: formatHistoryTimestamp(session.started_at) }),
                Object.assign(document.createElement('span'), { textContent: `${(session.items || []).length} Q&A` })
            );
            const items = session.items || [];
            const latestQuestion = Object.assign(document.createElement('div'), {
                className: 'history-latest-question',
                textContent: items.length ? `Latest: ${items[items.length - 1].question}` : 'No Q&A recorded'
            });
            summary.append(meta, latestQuestion);
            expand.append(arrow, summary);
            const details = document.createElement('div');
            details.className = 'history-session-items';
            expand.addEventListener('click', () => {
                const open = expand.getAttribute('aria-expanded') !== 'true';
                expand.setAttribute('aria-expanded', String(open));
                details.classList.toggle('expanded', open);
            });
            items.slice().reverse().forEach(item => {
                const qa = document.createElement('section');
                qa.className = 'history-qa';
                qa.append(
                    Object.assign(document.createElement('div'), { className: 'history-qa-time', textContent: formatHistoryTimestamp(item.timestamp) }),
                    Object.assign(document.createElement('div'), { className: 'history-qa-question', textContent: `Q: ${item.question}` }),
                    Object.assign(document.createElement('div'), { className: 'history-qa-answer', textContent: `A: ${item.answer}` })
                );
                details.append(qa);
            });
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'history-delete';
            remove.textContent = 'Delete';
            remove.setAttribute('aria-label', `Delete session ${index + 1}`);
            remove.addEventListener('click', () => deleteSessionHistory(session.id));
            header.append(expand, remove);
            article.append(header, details);
            return article;
        }

        async function deleteSessionHistory(sessionId) {
            if (!confirm('Delete this saved Q&A session?')) return;
            try {
                const response = await fetch(`/api/history/${encodeURIComponent(sessionId)}`, {
                    method: 'DELETE', headers: { 'X-Pairing-Token': pairingToken }
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Could not delete session history.');
                await loadSessionHistory();
            } catch (error) {
                alert(error.message);
            }
        }

        function openSessionHistory() {
            setHubPanel('history');
            loadSessionHistory();
        }

        /* -------------------------------------------------------------------------
           NOTES / NOTEBOOK MANAGEMENT (DASHBOARD & IN-APP COPILOT)
           ------------------------------------------------------------------------- */
        let cachedNotes = [];

        function escapeHtml(text) {
            return String(text || '').replace(/[&<>"']/g, char => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            })[char]);
        }

        function openNotesManager() {
            setHubPanel('notes');
            loadDashboardNotes();
        }

        async function loadDashboardNotes() {
            const container = document.getElementById('notes-items-container');
            try {
                const res = await fetch('/api/notes', { headers: { 'X-Pairing-Token': pairingToken } });
                const data = await res.json();
                if (res.ok && data.notes) {
                    cachedNotes = data.notes;
                    renderDashboardNotesList(cachedNotes);
                    renderCopilotNotes(cachedNotes);
                } else if (container) {
                    container.innerHTML = `<p class="history-empty">${data.detail || 'Could not load notes.'}</p>`;
                }
            } catch (err) {
                if (container) container.innerHTML = `<p class="history-empty">Failed to load notes: ${err.message}</p>`;
            }
        }

        function renderDashboardNotesList(notesToRender) {
            const container = document.getElementById('notes-items-container');
            const countBadge = document.getElementById('notes-count');
            if (countBadge) countBadge.textContent = notesToRender.length;
            if (!container) return;

            if (!notesToRender || notesToRender.length === 0) {
                container.innerHTML = `<p class="history-empty">No notes found. Click <strong>+ New Note</strong> above to add your first note!</p>`;
                return;
            }

            container.innerHTML = '';
            notesToRender.forEach(note => {
                const card = document.createElement('article');
                card.className = 'note-card-item';
                card.id = `note-card-${note.id}`;

                const header = document.createElement('div');
                header.className = 'note-card-header';

                const expandBtn = document.createElement('button');
                expandBtn.type = 'button';
                expandBtn.className = 'note-card-expand';
                expandBtn.innerHTML = `
                    <div style="min-width:0;">
                        <span class="note-card-title">${escapeHtml(note.title)}</span>
                        <span class="note-card-date">${note.updated_at || ''}</span>
                        <div class="note-card-preview">${escapeHtml(note.content ? note.content.replace(/\n/g, ' ') : '')}</div>
                    </div>
                `;

                const actions = document.createElement('div');
                actions.className = 'note-card-actions';

                const copyBtn = document.createElement('button');
                copyBtn.type = 'button';
                copyBtn.className = 'btn-note-action';
                copyBtn.textContent = 'Copy';
                copyBtn.title = 'Copy note text';
                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(note.content || note.title);
                    copyBtn.textContent = 'Copied!';
                    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
                };

                const editBtn = document.createElement('button');
                editBtn.type = 'button';
                editBtn.className = 'btn-note-action';
                editBtn.textContent = 'Edit';
                editBtn.title = 'Edit this note';
                editBtn.onclick = (e) => {
                    e.stopPropagation();
                    editNote(note.id);
                };

                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'btn-note-action btn-note-delete';
                delBtn.textContent = 'Delete';
                delBtn.title = 'Delete this note';
                delBtn.onclick = (e) => {
                    e.stopPropagation();
                    deleteNote(note.id);
                };

                actions.append(copyBtn, editBtn, delBtn);
                header.append(expandBtn, actions);

                const body = document.createElement('div');
                body.className = 'note-card-body';
                body.id = `note-body-${note.id}`;
                body.innerHTML = `<div class="note-content-display">${escapeHtml(note.content || '')}</div>`;

                expandBtn.onclick = () => {
                    body.classList.toggle('expanded');
                };

                card.append(header, body);
                container.append(card);
            });
        }

        function filterDashboardNotes() {
            const query = (document.getElementById('notes-search-input')?.value || '').toLowerCase().trim();
            if (!query) {
                renderDashboardNotesList(cachedNotes);
                return;
            }
            const filtered = cachedNotes.filter(n =>
                (n.title && n.title.toLowerCase().includes(query)) ||
                (n.content && n.content.toLowerCase().includes(query))
            );
            renderDashboardNotesList(filtered);
        }

        function resetNoteEditor() {
            document.getElementById('note-editor-id').value = '';
            document.getElementById('note-editor-title').value = '';
            document.getElementById('note-editor-content').value = '';
            document.getElementById('btn-save-note').textContent = 'Save Note';
            document.getElementById('btn-cancel-note').style.display = 'none';
            document.getElementById('note-editor-status').textContent = '';
            document.getElementById('note-editor-title').focus();
        }

        function editNote(id) {
            const note = cachedNotes.find(n => n.id === id);
            if (!note) return;
            document.getElementById('note-editor-id').value = note.id;
            document.getElementById('note-editor-title').value = note.title;
            document.getElementById('note-editor-content').value = note.content;
            document.getElementById('btn-save-note').textContent = 'Update Note';
            document.getElementById('btn-cancel-note').style.display = 'inline-block';
            document.getElementById('note-editor-status').textContent = `Editing: ${note.title}`;
            document.getElementById('note-editor-card').scrollIntoView({ behavior: 'smooth' });
        }

        function cancelNoteEdit() {
            resetNoteEditor();
        }

        async function saveCurrentNote() {
            const id = document.getElementById('note-editor-id').value;
            const title = document.getElementById('note-editor-title').value.trim();
            const content = document.getElementById('note-editor-content').value.trim();
            const status = document.getElementById('note-editor-status');

            if (!title && !content) {
                status.textContent = 'Please enter a title or note content.';
                status.style.color = '#ef4444';
                return;
            }

            status.textContent = 'Saving note...';
            status.style.color = '#94a3b8';

            try {
                const res = await fetch('/api/notes', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Pairing-Token': pairingToken },
                    body: JSON.stringify({ id: id || undefined, title, content })
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    status.textContent = 'Note saved successfully!';
                    status.style.color = '#10b981';
                    cachedNotes = data.notes;
                    renderDashboardNotesList(cachedNotes);
                    renderCopilotNotes(cachedNotes);
                    resetNoteEditor();
                    setTimeout(() => { status.textContent = ''; }, 2500);
                } else {
                    status.textContent = `Error: ${data.detail || 'Could not save note'}`;
                    status.style.color = '#ef4444';
                }
            } catch (err) {
                status.textContent = `Error: ${err.message}`;
                status.style.color = '#ef4444';
            }
        }

        async function deleteNote(id) {
            if (!confirm('Are you sure you want to delete this note?')) return;
            try {
                const res = await fetch(`/api/notes/${encodeURIComponent(id)}`, {
                    method: 'DELETE',
                    headers: { 'X-Pairing-Token': pairingToken }
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    cachedNotes = data.notes;
                    renderDashboardNotesList(cachedNotes);
                    renderCopilotNotes(cachedNotes);
                } else {
                    alert(data.detail || 'Could not delete note.');
                }
            } catch (err) {
                alert(`Error deleting note: ${err.message}`);
            }
        }

        function toggleNotesDrawer() {
            const drawer = document.getElementById('notes-drawer');
            const btn = document.getElementById('btn-notes');
            if (!drawer) return;
            const isOpen = drawer.style.display === 'flex';
            drawer.style.display = isOpen ? 'none' : 'flex';
            if (btn) btn.classList.toggle('active', !isOpen);
            if (!isOpen) {
                if (cachedNotes.length === 0) loadDashboardNotes();
                else renderCopilotNotes(cachedNotes);
                const search = document.getElementById('overlay-notes-search');
                if (search) search.focus();
            }
        }

        function renderCopilotNotes(notesToRender) {
            const list = document.getElementById('notes-drawer-list');
            if (!list) return;
            if (!notesToRender || notesToRender.length === 0) {
                list.innerHTML = `<p style="color:#94a3b8; font-size:0.75rem;">No saved notes. Create notes in Dashboard under <strong>Notes</strong>.</p>`;
                return;
            }
            list.innerHTML = '';
            notesToRender.forEach(note => {
                const item = document.createElement('div');
                item.className = 'overlay-note-item';

                const header = document.createElement('div');
                header.className = 'overlay-note-header';

                const titleSpan = document.createElement('div');
                titleSpan.className = 'overlay-note-title';
                titleSpan.innerHTML = `<span>${escapeHtml(note.title)}</span>`;

                const copyBtn = document.createElement('button');
                copyBtn.type = 'button';
                copyBtn.className = 'overlay-note-copy';
                copyBtn.textContent = 'Copy';
                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(note.content || note.title);
                    copyBtn.textContent = 'Copied!';
                    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1400);
                };

                header.append(titleSpan, copyBtn);

                const textDiv = document.createElement('div');
                textDiv.className = 'overlay-note-text';
                textDiv.textContent = note.content || '(Empty note)';

                header.onclick = () => {
                    textDiv.classList.toggle('open');
                };

                item.append(header, textDiv);
                list.append(item);
            });
        }

        function filterOverlayNotes(query) {
            query = (query || '').toLowerCase().trim();
            if (!query) {
                renderCopilotNotes(cachedNotes);
                return;
            }
            const filtered = cachedNotes.filter(n =>
                (n.title && n.title.toLowerCase().includes(query)) ||
                (n.content && n.content.toLowerCase().includes(query))
            );
            renderCopilotNotes(filtered);
        }

        /* -------------------------------------------------------------------------
           CREDIT & HISTORY MANAGEMENT (VOUCHERS, TRANSACTIONS & LIVE BALANCES)
           ------------------------------------------------------------------------- */
        let cachedCredits = { balance: 100, transactions: [] };
        let currentCreditFilter = 'all';

        function openCreditsView() {
            setHubPanel('credits');
            loadCreditsData();
        }

        function formatCreditCodeInput(input) {
            if (!input) return;
            let raw = input.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
            if (raw.length > 16) raw = raw.slice(0, 16);
            const parts = raw.match(/.{1,4}/g);
            input.value = parts ? parts.join('-') : raw;
        }

        function fillVoucherCode(code) {
            const input = document.getElementById('credit-code-input');
            if (input) {
                input.value = code;
                formatCreditCodeInput(input);
                input.focus();
            }
        }

        async function loadCreditsData() {
            const list = document.getElementById('credit-history-list');
            try {
                const response = await fetch('/api/credits', {
                    headers: { 'X-Pairing-Token': pairingToken }
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Could not load credit details.');

                cachedCredits = data;

                // Update live balance in header pill & stat card
                const headerBadge = document.getElementById('header-credit-points');
                if (headerBadge) headerBadge.textContent = data.balance ?? 0;

                const balanceVal = document.getElementById('credit-balance-value');
                if (balanceVal) balanceVal.textContent = data.balance ?? 0;

                const userNameEl = document.getElementById('credit-user-name');
                if (userNameEl) userNameEl.textContent = data.user_name || 'User';

                const userEmailEl = document.getElementById('credit-user-email');
                if (userEmailEl) userEmailEl.textContent = data.user_email || 'user@example.com';

                const txs = data.transactions || [];
                renderCreditTransactions(txs, currentCreditFilter);
            } catch (err) {
                if (list) {
                    list.innerHTML = `<p class="history-empty" style="color:#f87171;">Failed to load credits: ${escapeHtml(err.message)}</p>`;
                }
            }
        }

        function filterCreditHistory(type, btn) {
            currentCreditFilter = type;
            document.querySelectorAll('.credit-filter-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            renderCreditTransactions(cachedCredits.transactions || [], type);
        }

        function renderCreditTransactions(transactions, filter) {
            const list = document.getElementById('credit-history-list');
            if (!list) return;

            filter = filter || currentCreditFilter || 'all';
            let filtered = transactions || [];
            if (filter === 'credit') {
                filtered = filtered.filter(tx => tx.type === 'credit');
            } else if (filter === 'debit') {
                filtered = filtered.filter(tx => tx.type === 'debit');
            }

            if (!filtered || filtered.length === 0) {
                list.innerHTML = `<p class="history-empty">No transaction history found for "${escapeHtml(filter)}".</p>`;
                return;
            }

            list.innerHTML = '';
            filtered.forEach(tx => {
                const isCredit = tx.type === 'credit';
                const card = document.createElement('div');
                card.className = 'credit-tx-card';

                const amountSign = isCredit ? `+${tx.amount}` : `${tx.amount}`;
                const displayTitle = isCredit ? 'Credit Points Added' : 'Credit Points Used';

                let metaHtml = '';
                if (isCredit) {
                    if (tx.code) {
                        metaHtml += `<span class="credit-tx-meta-item">Code: <strong>${escapeHtml(tx.code)}</strong></span>`;
                    }
                    if (tx.expiry_date) {
                        metaHtml += `<span class="credit-tx-meta-item">Expiry: <strong>${escapeHtml(tx.expiry_date)}</strong></span>`;
                    }
                    metaHtml += `<span class="credit-tx-meta-item">Added by: <strong>${escapeHtml(tx.user_name || 'User')}</strong> (${escapeHtml(tx.user_email || 'N/A')} &bull; ${escapeHtml(tx.user_phone || 'N/A')})</span>`;
                } else {
                    const durationStr = tx.duration || 'N/A';
                    const snapsVal = tx.total_snaps ?? 0;

                    metaHtml += `<span class="credit-tx-meta-item">Total Duration: <strong>${escapeHtml(durationStr)}</strong></span>`;
                    metaHtml += `<span class="credit-tx-meta-item">Total Snap: <strong>${escapeHtml(String(snapsVal))}</strong></span>`;
                    metaHtml += `<span class="credit-tx-meta-item">Used by: <strong>${escapeHtml(tx.user_name || 'User')}</strong> (${escapeHtml(tx.user_email || 'N/A')} &bull; ${escapeHtml(tx.user_phone || 'N/A')})</span>`;
                }

                const displayTime = formatTo12HourTime(tx.timestamp || '');

                card.innerHTML = `
                    <div class="credit-tx-left">
                        <div class="credit-tx-body">
                            <div class="credit-tx-top">
                                <span class="credit-tx-id">${escapeHtml(tx.id || 'TXN')}</span>
                                <span class="credit-tx-time">${escapeHtml(displayTime)}</span>
                            </div>
                            <div class="credit-tx-desc">${escapeHtml(displayTitle)}</div>
                            <div class="credit-tx-meta">
                                ${metaHtml}
                            </div>
                        </div>
                    </div>
                    <div class="credit-tx-right">
                        <span class="credit-tx-amount-val ${isCredit ? 'amount-credit' : 'amount-used'}">${amountSign}</span>
                    </div>
                `;
                list.appendChild(card);
            });
        }

        async function redeemCreditCode() {
            const input = document.getElementById('credit-code-input');
            const btn = document.getElementById('btn-redeem');
            const status = document.getElementById('credit-redeem-status');
            if (!input || !btn) return;

            const raw = input.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
            if (raw.length !== 16) {
                if (status) {
                    status.style.display = 'block';
                    status.className = 'credit-redeem-status error';
                    status.textContent = 'Please enter a valid 16-character alphanumeric voucher code (e.g. ABCD-1234-EFGH-5678).';
                }
                input.focus();
                return;
            }

            btn.disabled = true;
            const oldText = btn.textContent;
            btn.textContent = 'Verifying...';
            if (status) {
                status.style.display = 'none';
                status.textContent = '';
            }

            try {
                const response = await fetch('/api/credits/redeem', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Pairing-Token': pairingToken
                    },
                    body: JSON.stringify({ code: raw })
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to redeem voucher code.');
                }

                if (status) {
                    status.style.display = 'block';
                    status.className = 'credit-redeem-status success';
                    status.textContent = `${data.message || 'Voucher redeemed successfully!'} (Added +${data.amount} Credits)`;
                }

                input.value = '';

                // Reload fresh credits and transactions
                await loadCreditsData();
            } catch (err) {
                if (status) {
                    status.style.display = 'block';
                    status.className = 'credit-redeem-status error';
                    status.textContent = err.message;
                }
            } finally {
                btn.disabled = false;
                btn.textContent = oldText;
            }
        }

        function bindProfileSettings() {
            // Profile Name validator (3-50 chars)
            const nameEl = document.getElementById('profile-name');
            if (nameEl) {
                nameEl.addEventListener('input', () => {
                    let val = nameEl.value;
                    if (val.length > 50) {
                        val = val.slice(0, 50);
                        nameEl.value = val;
                    }
                    const v = validateUserName(val);
                    setValidationUI('name', v.valid, v.error);
                    if (v.valid) {
                        queuePreferenceSave('profile_name', val.trim());
                    }
                });
                nameEl.addEventListener('blur', () => {
                    const v = validateUserName(nameEl.value);
                    setValidationUI('name', v.valid, v.error);
                });
            }

            // Email Address validator
            const emailEl = document.getElementById('profile-email');
            if (emailEl) {
                emailEl.addEventListener('input', () => {
                    const v = validateEmailAddress(emailEl.value);
                    setValidationUI('email', v.valid, v.error);
                    if (v.valid) {
                        queuePreferenceSave('profile_email', emailEl.value.trim());
                    }
                });
                emailEl.addEventListener('blur', () => {
                    const v = validateEmailAddress(emailEl.value);
                    setValidationUI('email', v.valid, v.error);
                });
            }

            // Phone Number validator (+91 and exactly 10 digits)
            const phoneEl = document.getElementById('profile-phone');
            if (phoneEl) {
                phoneEl.addEventListener('focus', () => {
                    if (!phoneEl.value || phoneEl.value.trim() === '') {
                        phoneEl.value = '+91 ';
                    }
                });
                phoneEl.addEventListener('input', () => {
                    const v = formatAndValidatePhone(phoneEl.value);
                    phoneEl.value = v.formatted;
                    setValidationUI('phone', v.valid, v.error);
                    if (v.valid) {
                        queuePreferenceSave('profile_phone', v.formatted);
                    }
                });
                phoneEl.addEventListener('blur', () => {
                    const v = formatAndValidatePhone(phoneEl.value);
                    setValidationUI('phone', v.valid, v.error);
                });
            }

            // Custom AI Instructions (max 100 chars with live counter)
            const ciEl = document.getElementById('custom-instructions');
            if (ciEl) {
                const counter = document.getElementById('custom-instructions-counter');
                ciEl.addEventListener('input', () => {
                    let val = ciEl.value;
                    if (val.length > 100) {
                        val = val.slice(0, 100);
                        ciEl.value = val;
                    }
                    if (counter) counter.textContent = `${val.length} / 100`;
                    queuePreferenceSave('custom_instructions', val);
                });
            }

            // Remaining UI controls
            const controls = [
                ['background-opacity', 'background_opacity', Number],
                ['font-opacity', 'font_opacity', Number],
                ['response-font-size', 'response_font_size', Number],
                ['screen-quality', 'screen_quality', Number],
                ['vad-mode', 'vad_mode', value => value]
            ];
            controls.forEach(([id, key, convert]) => {
                const element = document.getElementById(id);
                if (element) {
                    element.addEventListener(element.tagName === 'SELECT' ? 'change' : 'input', () => queuePreferenceSave(key, convert(element.value)));
                }
            });
            document.querySelectorAll('.quick-opacity-range').forEach(quickSlider => {
                quickSlider.addEventListener('input', () => queuePreferenceSave('background_opacity', Number(quickSlider.value)));
            });
            for (const [id, key] of [['show-screen-capture-button', 'show_screen_capture_button'], ['neural-vad-enabled', 'neural_vad_enabled'], ['google-search-enabled', 'google_search_enabled']]) {
                const el = document.getElementById(id);
                if (el) el.addEventListener('change', event => queuePreferenceSave(key, event.target.checked));
            }
            document.addEventListener('keydown', event => {
                const hubBody = document.querySelector('.hub-body');
                if (event.key === 'Escape' && (hubBody.classList.contains('profile-settings-open') || hubBody.classList.contains('customize-settings-open') || hubBody.classList.contains('history-open') || hubBody.classList.contains('notes-open') || hubBody.classList.contains('credits-open') || hubBody.classList.contains('help-open'))) {
                    showDashboard();
                }
            });

            const loopbackButton = document.getElementById('btn-loopback');
            loopbackButton.addEventListener('pointerdown', event => {
                if (currentVadMode !== 'manual') return;
                event.preventDefault();
                if (loopbackButton.setPointerCapture) loopbackButton.setPointerCapture(event.pointerId);
                setLoopbackListening(true);
            });
            for (const eventName of ['pointerup', 'pointercancel']) {
                loopbackButton.addEventListener(eventName, () => { if (currentVadMode === 'manual') setLoopbackListening(false); });
            }
        }

        /* -------------------------------------------------------------------------
           INTERVIEW SESSION RUNNING TIMER (FOR CLIENT BILLING & TRACKING)
           ------------------------------------------------------------------------- */
        let copilotTimerInterval = null;
        let copilotInterviewStartTime = null;

        function formatInterviewDuration(ms) {
            const totalSecs = Math.max(0, Math.floor(ms / 1000));
            const hours = Math.floor(totalSecs / 3600);
            const minutes = Math.floor((totalSecs % 3600) / 60);
            const seconds = totalSecs % 60;
            const pad = (n) => String(n).padStart(2, '0');
            return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
        }

        function updateCopilotTimerUI() {
            const display = document.getElementById('copilot-timer-display');
            if (!display || !copilotInterviewStartTime) return;
            const elapsed = Date.now() - copilotInterviewStartTime;
            display.textContent = formatInterviewDuration(elapsed);
        }

        function startCopilotTimer(forceReset = false, explicitStartTime = null) {
            if (explicitStartTime) {
                copilotInterviewStartTime = parseInt(explicitStartTime, 10);
                try {
                    sessionStorage.setItem('copilot_interview_start', String(copilotInterviewStartTime));
                } catch (e) { }
            } else if (forceReset || !copilotInterviewStartTime) {
                const saved = sessionStorage.getItem('copilot_interview_start');
                if (saved && !forceReset) {
                    copilotInterviewStartTime = parseInt(saved, 10);
                } else {
                    copilotInterviewStartTime = Date.now();
                    try {
                        sessionStorage.setItem('copilot_interview_start', String(copilotInterviewStartTime));
                    } catch (e) { }
                }
            }
            updateCopilotTimerUI();
            if (!copilotTimerInterval) {
                copilotTimerInterval = setInterval(updateCopilotTimerUI, 1000);
            }
        }

        function stopCopilotTimer() {
            if (copilotTimerInterval) {
                clearInterval(copilotTimerInterval);
                copilotTimerInterval = null;
            }
        }

        function resetCopilotTimer() {
            stopCopilotTimer();
            copilotInterviewStartTime = null;
            try {
                sessionStorage.removeItem('copilot_interview_start');
            } catch (e) { }
            const display = document.getElementById('copilot-timer-display');
            if (display) display.textContent = '00:00:00';
        }

        /* -------------------------------------------------------------------------
           PHONE COMPANION SYNCHRONIZATION & PC LOCK
           ------------------------------------------------------------------------- */
        let isCompanionConnected = false;
        let isSessionTakenOverOnPC = false;
        let currentCopilotStartTime = null;

        function updateCompanionUI(isConnected) {
            isCompanionConnected = Boolean(isConnected);
            const overlay = document.getElementById('qr-connected-overlay');
            const unpaired = document.getElementById('companion-unpaired-info');
            const paired = document.getElementById('companion-paired-info');
            const startBtn = document.getElementById('home-start-copilot-btn');
            const startBtnLabel = document.getElementById('home-start-btn-label');
            const mobileCard = document.getElementById('mobile-session-active-card');

            if (overlay) overlay.style.display = isConnected ? 'flex' : 'none';
            if (unpaired) unpaired.style.display = isConnected ? 'none' : 'block';
            if (paired) paired.style.display = isConnected ? 'block' : 'none';

            if (isConnected && !isSessionTakenOverOnPC) {
                if (startBtn) {
                    startBtn.disabled = true;
                    startBtn.classList.add('btn-locked-mobile');
                    startBtn.setAttribute('title', 'Session is managed from your paired mobile phone. Click Take Over on PC to control from here.');
                }
                if (startBtnLabel) {
                    startBtnLabel.textContent = 'Controlled via Mobile';
                }
                if (mobileCard) {
                    mobileCard.style.display = 'block';
                }
            } else {
                if (startBtn) {
                    startBtn.disabled = false;
                    startBtn.classList.remove('btn-locked-mobile');
                    startBtn.removeAttribute('title');
                }
                if (startBtnLabel) {
                    startBtnLabel.textContent = 'Start Copilot';
                }
                if (mobileCard) {
                    mobileCard.style.display = 'none';
                }
            }
        }

        function refreshQrImage() {
            const qrImg = document.getElementById('qr-image');
            if (qrImg) {
                qrImg.src = '/qr?t=' + Date.now();
            }
        }

        function updateQrLinkUI(url) {
            const qrLink = document.querySelector('.qr-link');
            if (qrLink) {
                qrLink.dataset.mobileUrl = url;
                qrLink.textContent = url;
            }
        }

        async function takeOverOnPC() {
            try {
                const res = await fetch('/api/companion/takeover', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Pairing-Token': pairingToken
                    }
                });
                const data = await res.json();
                if (data && data.token) {
                    pairingToken = data.token;
                    if (data.mobile_url) {
                        updateQrLinkUI(data.mobile_url);
                    }
                }
            } catch (e) {
                console.error('Error taking over on PC:', e);
            }

            isSessionTakenOverOnPC = false;
            updateCompanionUI(false);
            refreshQrImage();
            showStealthToast('💻 Copilot controls shifted to PC. Mobile disconnected & QR reset.');
        }
        window.takeOverOnPC = takeOverOnPC;

        async function disconnectCompanion() {
            try {
                const res = await fetch('/api/companion/disconnect', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Pairing-Token': pairingToken
                    }
                });
                const data = await res.json();
                if (data && data.token) {
                    pairingToken = data.token;
                    if (data.mobile_url) {
                        updateQrLinkUI(data.mobile_url);
                    }
                }
                isSessionTakenOverOnPC = false;
                updateCompanionUI(false);
                refreshQrImage();
                showStealthToast('Mobile phone disconnected. QR unlocked & reset.');
            } catch (e) {
                console.error('Failed to disconnect companion:', e);
            }
        }
        window.disconnectCompanion = disconnectCompanion;

        /* -------------------------------------------------------------------------
           VIEW SWITCHING LOGIC (NO SEPARATE WINDOWS)
           ------------------------------------------------------------------------- */
        async function switchToCopilotView(startNewSession = true, explicitStartTime = null) {
            if (startNewSession && isCompanionConnected && !isSessionTakenOverOnPC) {
                showStealthToast('🔒 Session is locked to Mobile. Click Take Over on PC first.');
                return;
            }
            if (startNewSession) {
                try {
                    await fetch('/api/history/session/start', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Pairing-Token': pairingToken,
                            'X-Device': 'desktop'
                        },
                        body: JSON.stringify({ source: 'desktop' })
                    });
                } catch (e) { }
                startCopilotTimer(true, explicitStartTime);
            } else {
                startCopilotTimer(false, explicitStartTime);
            }
            viewHub.style.display = 'none';
            viewCopilot.style.display = 'flex';
            document.body.classList.add('copilot-mode');
            window.location.hash = 'copilot';
            if (!socket || socket.readyState !== WebSocket.OPEN) {
                initWebSocket();
            }
            initPttMedia();
            const bgSlider = document.getElementById('background-opacity');
            if (bgSlider) {
                document.querySelectorAll('.quick-opacity-range').forEach(s => {
                    s.value = bgSlider.value;
                });
            }
        }

        function switchToHubView() {
            viewCopilot.style.display = 'none';
            viewHub.style.display = 'flex';
            document.body.classList.remove('copilot-mode');
            window.location.hash = '';
            const bgSlider = document.getElementById('background-opacity');
            if (bgSlider) {
                document.querySelectorAll('.quick-opacity-range').forEach(s => {
                    s.value = bgSlider.value;
                });
            }
        }

        async function backToHub() {
            if (confirm("End current interview session? This will flush the 5-turn memory and return to the Hub.")) {
                try {
                    await fetch('/api/history/session/end', {
                        method: 'POST', headers: { 'X-Pairing-Token': pairingToken }
                    });
                    await fetch('/api/clear-history', {
                        method: 'POST',
                        headers: { 'X-Pairing-Token': pairingToken }
                    });
                    if (socket && socket.readyState === WebSocket.OPEN) {
                        socket.send(JSON.stringify({ action: 'clear_history' }));
                    }
                } catch (e) { }
                resetCopilotTimer();
                clearOverlay();
                switchToHubView();
            }
        }

        function minimizeWindow() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.minimize) {
                window.pywebview.api.minimize();
            } else {
                alert("Tip: You can now safely minimize this window (or press Win+Down). Your phone companion is connected and will receive solutions directly!");
            }
        }

        function closeApp() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.close) {
                window.pywebview.api.close();
            } else {
                window.close();
            }
        }

        /* -------------------------------------------------------------------------
           WEBSOCKET ENGINE
           ------------------------------------------------------------------------- */
        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const tokenParam = pairingToken ? `?token=${encodeURIComponent(pairingToken)}` : '';
            socket = new WebSocket(`${protocol}//${window.location.host}/ws${tokenParam}`);

            socket.onopen = () => {
                if (dot) dot.style.background = '#10b981';
                if (statusInfo) statusInfo.textContent = 'Connected & Ready';
            };

            socket.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    handleMessage(msg);
                } catch (e) { }
            };

            socket.onclose = () => {
                if (dot) dot.style.background = '#ef4444';
                if (statusInfo) statusInfo.textContent = 'Reconnecting...';
                setTimeout(initWebSocket, 2000);
            };
        }

        function setResumeBadge(message, filename = '') {
            const badge = document.getElementById('resume-status-badge');
            badge.textContent = message;
            badge.title = filename;
            badge.setAttribute('aria-label', filename ? `Resume: ${filename}` : message);
        }

        let thinkingTimer = null;

        function handleMessage(msg) {
            if (msg.type === 'init') {
                if (typeof msg.loopback_active !== 'undefined') {
                    updateLoopbackUI(msg.loopback_active);
                }
                if (msg.mode) {
                    currentMode = msg.mode;
                    if (modeSelect) modeSelect.value = msg.mode;
                    if (footerMode) footerMode.textContent = formatModeName(msg.mode);
                }
                if (msg.notes) {
                    cachedNotes = msg.notes;
                    renderDashboardNotesList(cachedNotes);
                    renderCopilotNotes(cachedNotes);
                }
                if (typeof msg.credits_balance !== 'undefined') {
                    const headerBadge = document.getElementById('header-credit-points');
                    if (headerBadge) headerBadge.textContent = msg.credits_balance;
                    const balanceVal = document.getElementById('credit-balance-value');
                    if (balanceVal) balanceVal.textContent = msg.credits_balance;
                }
                if (msg.has_resume) {
                    updateDesktopResumeUI(true, msg.resume_filename);
                    setResumeBadge(`Active (${msg.resume_filename || 'Resume'})`, msg.resume_filename);
                    const badge = document.getElementById('resume-status-badge');
                    if (badge) badge.style.color = '#10b981';
                    document.getElementById('profile-resume-status').textContent = `Resume ready: ${msg.resume_filename || 'uploaded'}.`;
                } else {
                    updateDesktopResumeUI(false);
                    setResumeBadge('No Resume Uploaded', '');
                    const badge = document.getElementById('resume-status-badge');
                    if (badge) badge.style.color = 'var(--text-secondary)';
                    document.getElementById('profile-resume-status').textContent = 'No resume uploaded.';
                }
                ['background_opacity', 'font_opacity', 'response_font_size', 'show_screen_capture_button', 'screen_quality', 'neural_vad_enabled', 'vad_mode', 'google_search_enabled', 'custom_instructions', 'profile_name', 'profile_email', 'profile_phone'].forEach(key => {
                    if (typeof msg[key] !== 'undefined') {
                        applyPreference(key, msg[key]);
                    }
                });
                if (typeof msg.companion_connected !== 'undefined') {
                    updateCompanionUI(Boolean(msg.companion_connected));
                }
                if (msg.copilot_active && msg.copilot_start_time) {
                    startCopilotTimer(false, msg.copilot_start_time);
                }
            } else if (msg.type === 'notes_updated') {
                cachedNotes = msg.notes || [];
                renderDashboardNotesList(cachedNotes);
            } else if (msg.type === 'credits_updated') {
                if (typeof msg.balance !== 'undefined') {
                    const headerBadge = document.getElementById('header-credit-points');
                    if (headerBadge) headerBadge.textContent = msg.balance;
                    const balanceVal = document.getElementById('credit-balance-value');
                    if (balanceVal) balanceVal.textContent = msg.balance;
                }
                const hubBody = document.querySelector('.hub-body');
                if (hubBody && hubBody.classList.contains('credits-open')) {
                    loadCreditsData();
                }
            } else if (msg.type === 'settings_updated') {
                ['background_opacity', 'font_opacity', 'response_font_size', 'show_screen_capture_button', 'screen_quality', 'neural_vad_enabled', 'vad_mode', 'google_search_enabled', 'custom_instructions', 'profile_name', 'profile_email', 'profile_phone'].forEach(key => {
                    if (typeof msg[key] !== 'undefined') {
                        applyPreference(key, msg[key]);
                    }
                });
                if (typeof msg.has_resume !== 'undefined') {
                    updateDesktopResumeUI(msg.has_resume, msg.resume_filename);
                }
                if (typeof msg.loopback_active !== 'undefined') {
                    updateLoopbackUI(msg.loopback_active);
                }
            } else if (msg.type === 'ptt_state') {
                if (typeof msg.loopback_active !== 'undefined') {
                    updateLoopbackUI(msg.loopback_active);
                }
            } else if (msg.type === 'loopback_status') {
                updateLoopbackUI(msg.is_active);
            } else if (msg.type === 'status' && msg.status === 'thinking') {
                clearTimeout(thinkingTimer);
                statusBannerText.textContent = msg.message || (msg.is_snip ? '📸 Analyzing Code Screen with Gemini...' : '⚡ Generating spoken developer answer...');
                statusBanner.style.display = 'flex';
                statusBanner.style.background = 'rgba(16, 185, 129, 0.15)';
                statusBanner.style.color = '#10b981';
                statusBanner.style.borderColor = 'rgba(16, 185, 129, 0.35)';

                thinkingTimer = setTimeout(() => {
                    statusBanner.style.display = 'none';
                }, 15000);

            } else if (msg.type === 'status' && msg.status === 'idle') {
                clearTimeout(thinkingTimer);
                statusBannerText.textContent = 'Audio did not contain a complete question.';
                statusBanner.style.background = 'rgba(148, 163, 184, 0.15)';
                statusBanner.style.color = '#cbd5e1';
                statusBanner.style.borderColor = 'rgba(148, 163, 184, 0.25)';
                statusBanner.style.display = 'flex';
                setTimeout(() => {
                    statusBanner.style.display = 'none';
                }, 3000);

            } else if (msg.type === 'speech_interim') {
                if (liveTranscript) liveTranscript.textContent = msg.text;
            } else if (msg.type === 'new_answer') {
                clearTimeout(thinkingTimer);
                statusBanner.style.display = 'none';
                if (msg.data.success) {
                    renderAnswer(msg.data);
                } else {
                    renderError(msg.data.error || 'Failed to generate answer.');
                }
            } else if (msg.type === 'mode_changed') {
                currentMode = msg.mode;
                if (modeSelect) modeSelect.value = msg.mode;
                if (footerMode) footerMode.textContent = formatModeName(msg.mode);
            } else if (msg.type === 'history_cleared') {
                statusBannerText.textContent = 'Rolling conversation history cleared.';
                statusBanner.style.display = 'flex';
                statusBanner.style.background = 'rgba(0, 122, 255, 0.15)';
                statusBanner.style.color = '#007aff';
                statusBanner.style.borderColor = 'rgba(0, 122, 255, 0.35)';
                setTimeout(() => { statusBanner.style.display = 'none'; }, 3000);
            } else if (msg.type === 'resume_updated') {
                statusBannerText.textContent = `Resume updated: ${msg.filename || 'Profile loaded'}`;
                statusBanner.style.display = 'flex';
                statusBanner.style.background = 'rgba(16, 185, 129, 0.15)';
                statusBanner.style.color = '#10b981';
                statusBanner.style.borderColor = 'rgba(16, 185, 129, 0.35)';
                document.getElementById('profile-resume-status').textContent = `Resume ready: ${msg.filename || 'uploaded'}.`;
                updateDesktopResumeUI(true, msg.filename, msg.length);
                const badge = document.getElementById('resume-status-badge');
                if (badge) {
                    const filename = msg.filename || 'Resume';
                    setResumeBadge(`Active (${filename} • ${msg.length} chars)`, filename);
                    badge.style.color = '#10b981';
                }
                setTimeout(() => { statusBanner.style.display = 'none'; }, 3500);
            } else if (msg.type === 'resume_deleted') {
                updateDesktopResumeUI(false);
                setResumeBadge('No Resume Uploaded', '');
                const badge = document.getElementById('resume-status-badge');
                if (badge) badge.style.color = 'var(--text-secondary)';
                document.getElementById('profile-resume-status').textContent = 'No resume uploaded.';
                statusBannerText.textContent = 'Resume was removed.';
                statusBanner.style.display = 'flex';
                statusBanner.style.background = 'rgba(239, 68, 68, 0.15)';
                statusBanner.style.color = '#f87171';
                statusBanner.style.borderColor = 'rgba(239, 68, 68, 0.35)';
                setTimeout(() => { statusBanner.style.display = 'none'; }, 3000);
            } else if (msg.type === 'copilot_started') {
                currentCopilotStartTime = msg.start_time;
                const isFromMobile = (msg.source === 'mobile') || (isCompanionConnected && !isSessionTakenOverOnPC);

                if (isFromMobile) {
                    // Mobile is primary: KEEP LAPTOP IN STEALTH MODE (do not hijack PC screen)!
                    updateCompanionUI(true);
                    startCopilotTimer(false, msg.start_time);
                    const mobileCard = document.getElementById('mobile-session-active-card');
                    const mobileStatusText = document.getElementById('mobile-active-status-text');
                    const mobileHelpText = document.getElementById('mobile-active-help-text');
                    if (mobileCard) mobileCard.style.display = 'block';
                    if (mobileStatusText) mobileStatusText.textContent = '🔴 Active Session on Mobile';
                    if (mobileHelpText) mobileHelpText.textContent = 'Live interview solutions & speech detection active on your phone. PC screen is in stealth mode.';
                    showStealthToast('📱 Stealth session active on Phone');
                } else {
                    // Direct PC session or Taken Over: switch desktop view
                    switchToCopilotView(false, msg.start_time);
                }
            } else if (msg.type === 'copilot_ended') {
                // Auto reset Desktop when session ends
                resetCopilotTimer();
                clearOverlay();
                switchToHubView();
                loadSessionHistory();
                loadCreditsData();
                currentCopilotStartTime = null;

                // User requirement: Even when session ends on mobile, if mobile is still connected,
                // KEEP THE START COPILOT BUTTON LOCKED on laptop!
                // Only unlock when user clicks "Take Over on PC" or manually disconnects mobile.
                if (isCompanionConnected && !isSessionTakenOverOnPC) {
                    updateCompanionUI(true);
                    const mobileStatusText = document.getElementById('mobile-active-status-text');
                    const mobileHelpText = document.getElementById('mobile-active-help-text');
                    if (mobileStatusText) mobileStatusText.textContent = 'Controlled via Mobile Phone';
                    if (mobileHelpText) mobileHelpText.textContent = 'Mobile companion is paired. Start new session from phone, or click Take Over on PC.';
                }
            } else if (msg.type === 'pairing_token_updated') {
                if (msg.token) {
                    pairingToken = msg.token;
                }
                if (msg.mobile_url) {
                    updateQrLinkUI(msg.mobile_url);
                }
                refreshQrImage();
            } else if (msg.type === 'companion_status') {
                if (!msg.connected) {
                    isSessionTakenOverOnPC = false;
                    refreshQrImage();
                }
                updateCompanionUI(Boolean(msg.connected));
            } else if (msg.type === 'panic_clear') {
                clearTimeout(thinkingTimer);
                clearOverlay();
            }
        }

        function formatModeName(mode) {
            const map = {
                'qa_testing': 'QA & Testing',
                'general': 'General Tech',
                'coding': 'DSA & Coding',
                'system_design': 'System Design',
                'behavioral': 'HR / Behavioral'
            };
            return map[mode] || mode;
        }

        function handleLoopbackControl(event) {
            if (currentVadMode === 'manual') {
                if (event) event.preventDefault();
                return;
            }
            toggleLoopbackAudio();
        }

        function setLoopbackListening(newState) {
            const btn = document.getElementById('btn-loopback');
            if (btn.classList.contains('active') === newState) return;
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'toggle_loopback', enable: newState }));
            } else {
                fetch('/api/loopback/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Pairing-Token': pairingToken },
                    body: JSON.stringify({ enable: newState })
                });
            }
            updateLoopbackUI(newState);
        }

        function toggleLoopbackAudio() {
            const btn = document.getElementById('btn-loopback');
            const isCurrentlyActive = btn.classList.contains('active');
            setLoopbackListening(!isCurrentlyActive);
        }

        function updateLoopbackUI(isActive) {
            const btn = document.getElementById('btn-loopback');
            const label = document.getElementById('loopback-label');
            if (!btn || !label) return;
            if (isActive) {
                btn.classList.add('active');
                label.textContent = 'Interviewer Voice';
                if (liveTranscript) liveTranscript.textContent = 'Listening....';
            } else {
                btn.classList.remove('active');
                label.textContent = 'Voice Paused';
                if (liveTranscript) liveTranscript.textContent = 'Interviewer audio capture paused.';
            }
        }

        /* -------------------------------------------------------------------------
           ANSWER RENDERING (DESCENDING ORDER - RECENT AT TOP)
           ------------------------------------------------------------------------- */
        function renderAnswer(data) {
            if (isMicListening) {
                stopMicListening();
            }

            const welcomeCard = document.getElementById('welcome-card');
            if (welcomeCard) welcomeCard.remove();
            const clearedPlaceholder = document.getElementById('cleared-placeholder');
            if (clearedPlaceholder) clearedPlaceholder.remove();

            let text = data.answer || '';
            let html = text
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
                .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                .replace(/^### (.*$)/gim, '<h4 style="color:#007aff;margin:12px 0 6px 0;font-size:1.05rem;">$1</h4>')
                .replace(/^## (.*$)/gim, '<h3 style="color:#10b981;margin:14px 0 8px 0;font-size:1.15rem;">$1</h3>')
                .replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>');
            html = html.replace(/(<li>.*<\/li>)/gims, '<ul style="margin:6px 0 10px 18px;">$1</ul>');

            const now = new Date();
            const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

            const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
            const providerBadge = data.model_used ? `<span style="font-size:0.70rem;color:#94a3b8;background:rgba(255,255,255,0.06);padding:2px 8px;border-radius:4px;">${escapeHtml(data.model_used)}</span>` : '';

            const spk = data.speaker || (data.is_screenshot ? 'screen' : (data.is_audio ? 'interviewer' : 'candidate'));
            let speakerBadge = '';
            if (spk === 'interviewer') {
                speakerBadge = '<span style="display:inline-flex;align-items:center;background:rgba(0,122,255,0.18);color:#007aff;padding:3px 9px;border-radius:6px;font-size:0.75rem;font-weight:700;"> INTERVIEWER</span>';
            } else if (spk === 'screen') {
                speakerBadge = '<span style="display:inline-flex;align-items:center;background:rgba(245,158,11,0.18);color:#f59e0b;padding:3px 9px;border-radius:6px;font-size:0.75rem;font-weight:700;"> SCREEN SOLUTION</span>';
            } else {
                speakerBadge = '<span style="display:inline-flex;align-items:center;background:rgba(16,185,129,0.18);color:#10b981;padding:3px 9px;border-radius:6px;font-size:0.75rem;font-weight:700;"> CANDIDATE</span>';
            }

            const qText = data.question
                ? `<div style="color:#94a3b8;font-size:0.95rem;font-weight:600;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.06);">Q: "${escapeHtml(data.question)}"</div>`
                : '';

            const card = document.createElement('div');
            card.className = 'answer-card-item';
            card.innerHTML = `
                <div class="answer-card-header">
                    <div style="display:flex;align-items:center;gap:8px;">
                        ${speakerBadge}
                        ${providerBadge}
                    </div>
                    <span class="answer-time">${timeStr}</span>
                </div>
                ${qText}
                <div class="answer-card-body">
                    ${html}
                </div>
            `;

            answersFeed.insertBefore(card, answersFeed.firstChild);
            content.scrollTop = 0;
        }

        function renderError(errMessage) {
            const card = document.createElement('div');
            card.className = 'answer-card-item';
            card.style.borderColor = 'rgba(239, 68, 68, 0.4)';
            card.style.background = 'rgba(239, 68, 68, 0.1)';
            card.innerHTML = `
                <div style="color:#ef4444;font-weight:700;font-size:0.88rem;margin-bottom:6px;">&#9888;&#65039; Notice</div>
                <div style="color:#cbd5e1;font-size:0.88rem;">${String(errMessage).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char])}</div>
            `;
            answersFeed.insertBefore(card, answersFeed.firstChild);
            content.scrollTop = 0;
        }

        // =========================================================================
        // PUSH-TO-TALK (HOLD & RELEASE) AUDIO ENGINE
        // =========================================================================
        let pttMediaRecorder = null;
        let pttAudioChunks = [];
        let isPttPressed = false;
        let isPttRecording = false;
        let pttStartTime = 0;
        let pttStream = null;

        // Backward-compatibility stub
        function stopMicListening() {
            if (isPttPressed || isPttRecording) stopPtt(true);
        }

        async function initPttMedia() {
            if (!pttStream || !pttStream.active) {
                try {
                    pttStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                } catch (err) {
                    console.error("Microphone access denied or unavailable:", err);
                    return false;
                }
            }
            return true;
        }

        function pauseLoopback() {
            updateLoopbackUI(false);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'ptt_start' }));
            } else {
                fetch('/api/ptt/start', {
                    method: 'POST',
                    headers: { 'X-Pairing-Token': pairingToken }
                }).catch(() => { });
            }
        }

        function resumeLoopback() {
            updateLoopbackUI(true);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'ptt_end' }));
            } else {
                fetch('/api/ptt/end', {
                    method: 'POST',
                    headers: { 'X-Pairing-Token': pairingToken }
                }).then(r => r.json()).then(data => {
                    if (typeof data.loopback_active !== 'undefined') {
                        updateLoopbackUI(data.loopback_active);
                    }
                }).catch(() => { });
            }
        }

        async function startPtt() {
            if (isPttPressed && isPttRecording) return;
            isPttPressed = true;

            // 1. Instantly pause interviewer loopback
            pauseLoopback();

            // 2. Immediate visual feedback
            if (btnMic) btnMic.classList.add('recording');
            if (micLabel) micLabel.textContent = 'Recording (Release to Send)';
            if (liveTranscript) liveTranscript.textContent = 'Recording candidate voice...';

            // 3. Ensure audio stream is ready
            const hasMedia = await initPttMedia();

            // User released while initializing mic! Cancel immediately so it never gets stuck!
            if (!isPttPressed) {
                stopPtt(true);
                return;
            }

            if (!hasMedia || !pttStream) {
                isPttPressed = false;
                if (btnMic) btnMic.classList.remove('recording');
                if (micLabel) micLabel.textContent = 'Hold to Speak';
                resumeLoopback();
                alert("Microphone access is not available. Please ensure microphone permissions are granted in Windows.");
                return;
            }

            // 4. Start MediaRecorder
            try {
                let options = {};
                if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                    options = { mimeType: 'audio/webm;codecs=opus' };
                } else if (MediaRecorder.isTypeSupported('audio/webm')) {
                    options = { mimeType: 'audio/webm' };
                } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
                    options = { mimeType: 'audio/mp4' };
                }
                pttAudioChunks = [];
                pttMediaRecorder = new MediaRecorder(pttStream, options);
                pttMediaRecorder.ondataavailable = (e) => {
                    if (e.data && e.data.size > 0) {
                        pttAudioChunks.push(e.data);
                    }
                };
                pttMediaRecorder.start(100);
                isPttRecording = true;
                pttStartTime = Date.now();
            } catch (err) {
                console.error("MediaRecorder start failed:", err);
                stopPtt(true);
            }
        }

        async function stopPtt(cancel = false) {
            if (!isPttPressed && !isPttRecording) return;
            isPttPressed = false;

            // 1. Immediately remove visual recording indicator
            if (btnMic) btnMic.classList.remove('recording');

            // 2. CRITICAL: Immediately resume loopback audio with ZERO latency!
            resumeLoopback();

            if (!isPttRecording) {
                // Released before media initialized (e.g. quick click)
                if (micLabel) micLabel.textContent = 'Hold to Speak';
                return;
            }

            isPttRecording = false;
            const duration = Date.now() - pttStartTime;

            if (pttMediaRecorder && pttMediaRecorder.state !== 'inactive') {
                try { pttMediaRecorder.stop(); } catch (e) { }
            }

            // Discard accidental quick clicks (< 300ms)
            if (cancel || duration < 300) {
                if (micLabel) micLabel.textContent = 'Hold to Speak';
                if (liveTranscript) liveTranscript.textContent = 'Listening to interviewer...';
                return;
            }

            if (micLabel) micLabel.textContent = 'Transcribing...';
            if (liveTranscript) liveTranscript.textContent = 'Processing candidate voice...';

            // Wait 120ms for recorder buffer to flush final data chunk
            setTimeout(async () => {
                try {
                    const mimeType = pttMediaRecorder ? (pttMediaRecorder.mimeType || 'audio/webm') : 'audio/webm';
                    const audioBlob = new Blob(pttAudioChunks, { type: mimeType });

                    if (audioBlob.size > 800) {
                        const formData = new FormData();
                        formData.append('file', audioBlob, 'candidate_voice.webm');
                        formData.append('mode', currentMode);
                        formData.append('speaker', 'Candidate');

                        await fetch('/api/process-audio', {
                            method: 'POST',
                            headers: { 'X-Pairing-Token': pairingToken },
                            body: formData
                        });
                    }
                } catch (err) {
                    console.error("Error submitting PTT audio:", err);
                } finally {
                    if (!isPttPressed && !isPttRecording) {
                        if (micLabel) micLabel.textContent = 'Hold to Speak';
                    }
                }
            }, 120);
        }

        // Attach Pointer Listeners for Hold & Release with Pointer Capture
        if (btnMic) {
            btnMic.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
            btnMic.addEventListener('pointerdown', (e) => {
                e.preventDefault();
                try { btnMic.setPointerCapture(e.pointerId); } catch (_) { }
                startPtt();
            });
            btnMic.addEventListener('pointerup', (e) => {
                e.preventDefault();
                try { btnMic.releasePointerCapture(e.pointerId); } catch (_) { }
                stopPtt();
            });
            btnMic.addEventListener('pointercancel', (e) => {
                try { btnMic.releasePointerCapture(e.pointerId); } catch (_) { }
                stopPtt(true);
            });
            btnMic.addEventListener('contextmenu', (e) => e.preventDefault());
        }

        // Global safety listeners: Window blur or uncaptured release outside button
        window.addEventListener('mouseup', () => {
            if (isPttPressed || isPttRecording) stopPtt();
        });
        window.addEventListener('touchend', () => {
            if (isPttPressed || isPttRecording) stopPtt();
        });
        window.addEventListener('blur', () => {
            if (isPttPressed || isPttRecording) stopPtt(true);
        });

        // Keyboard Push-to-Talk (Hold Spacebar when not typing in text input)
        window.addEventListener('keydown', (e) => {
            const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
            if (activeTag === 'input' || activeTag === 'textarea') return;

            if (e.code === 'Space' && !e.repeat && !isPttPressed) {
                e.preventDefault();
                startPtt();
            }
        });
        window.addEventListener('keyup', (e) => {
            if (e.code === 'Space' && (isPttPressed || isPttRecording)) {
                e.preventDefault();
                stopPtt();
            }
        });

        function sendQuestion(q) {
            if (!q || !socket) return;
            socket.send(JSON.stringify({
                action: 'speech_final',
                text: q,
                mode: currentMode
            }));
        }

        /* -------------------------------------------------------------------------
           SOUND METER EQUALIZER
           ------------------------------------------------------------------------- */
        function setupMicAudioVisualizer() {
            navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
                setupStreamVisualizer(stream);
            }).catch(() => { });
        }

        function setupStreamVisualizer(stream) {
            try {
                if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const source = audioContext.createMediaStreamSource(stream);
                analyser = audioContext.createAnalyser();
                analyser.fftSize = 32;
                source.connect(analyser);

                const bars = [document.getElementById('bar1'), document.getElementById('bar2'), document.getElementById('bar3'), document.getElementById('bar4'), document.getElementById('bar5')];
                const data = new Uint8Array(analyser.frequencyBinCount);

                function loop() {
                    if (!analyser) return;
                    analyser.getByteFrequencyData(data);
                    let sum = 0;
                    for (let i = 0; i < 5; i++) {
                        let val = Math.max(3, (data[i * 2] / 255) * 16);
                        sum += data[i * 2];
                        if (bars[i]) bars[i].style.height = `${val}px`;
                    }
                    let avg = sum / 5;
                    bars.forEach(b => {
                        if (b) b.style.background = avg > 15 ? '#10b981' : '#64748b';
                    });
                    requestAnimationFrame(loop);
                }
                loop();
            } catch (e) { }
        }

        /* -------------------------------------------------------------------------
           MANUAL QUESTION SUBMIT & SNIP
           ------------------------------------------------------------------------- */
        function submitManualQuestion() {
            const q = manualInput.value.trim();
            if (!q) return;

            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    action: 'ask',
                    question: q,
                    mode: currentMode
                }));
            }
            manualInput.value = '';
        }

        manualInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitManualQuestion();
        });

        function triggerSnip() {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'trigger_snip', mode: currentMode }));
            }
        }

        function changeMode(m) {
            currentMode = m;
            if (footerMode) footerMode.textContent = formatModeName(m);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'change_mode', mode: m }));
            }
        }

        function clearOverlay() {
            answersFeed.innerHTML = `
                <div id="cleared-placeholder" class="empty-state">
                    <p style="font-size: 0.92rem; color: #94a3b8; margin-bottom: 6px;">✨ All answers cleared.</p>
                    <p style="font-size: 0.80rem; color: #64748b;">Listening for next question from interviewer or snip...</p>
                </div>
            `;
            statusBanner.style.display = 'none';
            if (liveTranscript) liveTranscript.textContent = 'Listening...';

            // Reset rolling 5-turn AI conversation memory
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'clear_history' }));
            } else {
                fetch('/api/clear-history', {
                    method: 'POST',
                    headers: { 'X-Pairing-Token': pairingToken }
                });
            }
        }

        function clearConversationMemory() {
            clearOverlay();
        }

        /* -------------------------------------------------------------------------
           HUB ACTIONS: COPY PHONE LINK, RESUME UPLOAD, DETACHED OVERLAY
           ------------------------------------------------------------------------- */
        async function copyMobileUrl() {
            const status = document.getElementById('action-status');
            const qrStatus = document.getElementById('qr-copy-status');
            try {
                await navigator.clipboard.writeText(document.querySelector('.qr-link').dataset.mobileUrl);
                status.textContent = 'Phone link copied! Open it on your phone, or scan the QR code.';
                qrStatus.textContent = 'Copied to clipboard!';
            } catch (error) {
                status.textContent = 'Could not copy automatically. Scan the QR code with your phone camera.';
                qrStatus.textContent = 'Could not copy. Scan the QR code instead.';
            }
        }

        async function launchDesktopOverlay() {
            const button = document.getElementById('overlay-button');
            const status = document.getElementById('action-status');
            if (button) button.disabled = true;
            if (status) status.textContent = 'Starting detached native overlay...';
            try {
                const response = await fetch('/api/desktop-overlay', {
                    method: 'POST',
                    headers: { 'X-Pairing-Token': pairingToken }
                });
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.detail || 'The overlay could not be started.');
                }
                if (status) status.textContent = result.already_running
                    ? 'The desktop overlay is already open.'
                    : 'The detached native desktop overlay has been launched.';
            } catch (error) {
                if (status) status.textContent = error.message || 'The desktop overlay could not be started.';
            } finally {
                if (button) button.disabled = false;
            }
        }

        async function uploadResumeFile(input) {
            if (!input.files || input.files.length === 0) return;
            const file = input.files[0];
            const status = document.getElementById('action-status');
            const badge = document.getElementById('resume-status-badge');

            if (!file.name.toLowerCase().endsWith('.pdf')) {
                status.textContent = 'Upload a PDF resume only.';
                document.getElementById('profile-resume-status').textContent = 'Upload a PDF resume only.';
                input.value = '';
                return;
            }
            if (file.size > 1024 * 1024) {
                status.textContent = 'Resume file must be 1 MB or smaller.';
                document.getElementById('profile-resume-status').textContent = 'Resume file must be 1 MB or smaller.';
                input.value = '';
                return;
            }

            status.textContent = `Parsing ${file.name}...`;
            document.getElementById('profile-resume-status').textContent = `Parsing ${file.name}...`;
            setResumeBadge(`Parsing ${file.name}...`, file.name);
            badge.style.color = '#007aff';

            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/api/upload-resume', {
                    method: 'POST',
                    headers: { 'X-Pairing-Token': pairingToken },
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    setResumeBadge(`Active (${file.name} • ${data.length} chars)`, file.name);
                    badge.style.color = '#10b981';
                    status.textContent = `Resume loaded: ${file.name} (${data.length} characters injected into AI context).`;
                    document.getElementById('profile-resume-status').textContent = `Resume ready: ${file.name}.`;
                    updateDesktopResumeUI(true, file.name, data.length);
                } else {
                    throw new Error(data.detail || data.error || 'Failed to parse resume');
                }
            } catch (err) {
                setResumeBadge('Error parsing resume', file.name);
                badge.style.color = '#ef4444';
                status.textContent = `Upload failed: ${err.message}`;
                document.getElementById('profile-resume-status').textContent = `Upload failed: ${err.message}`;
            }
        }

        async function deleteResumeFile() {
            if (!confirm("Are you sure you want to remove the saved resume?")) return;
            try {
                const res = await fetch('/api/resume', {
                    method: 'DELETE',
                    headers: { 'X-Pairing-Token': pairingToken }
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    updateDesktopResumeUI(false);
                    setResumeBadge('No Resume Uploaded', '');
                    const badge = document.getElementById('resume-status-badge');
                    if (badge) badge.style.color = 'var(--text-secondary)';
                    document.getElementById('profile-resume-status').textContent = 'Resume removed. You can upload a fresh resume.';
                    const status = document.getElementById('action-status');
                    if (status) status.textContent = 'Resume removed.';
                } else {
                    alert(data.detail || data.error || 'Failed to delete resume.');
                }
            } catch (err) {
                alert('Error deleting resume: ' + err.message);
            }
        }

        function updateDesktopResumeUI(hasResume, filename = '', charCount = 0) {
            const card = document.getElementById('desktop-saved-resume-card');
            const fnEl = document.getElementById('desktop-resume-filename');
            const metaEl = document.getElementById('desktop-resume-meta');
            const uploadBtn = document.getElementById('btn-upload-resume-desktop');

            if (hasResume) {
                if (card) card.style.display = 'flex';
                if (fnEl) fnEl.textContent = filename || 'resume.pdf';
                if (metaEl) metaEl.textContent = charCount ? `Ready for AI context (${charCount} characters)` : 'Saved on this device & ready for AI';
                if (uploadBtn) uploadBtn.textContent = 'Replace PDF Resume';
                setResumeValidationUI(true);
            } else {
                if (card) card.style.display = 'none';
                if (uploadBtn) uploadBtn.textContent = 'Upload PDF Resume';
                setResumeValidationUI(false);
            }
        }

        /* -------------------------------------------------------------------------
           DESKTOP WINDOW CONTROLS: CLOSE, MINIMIZE, OPACITY CYCLING & HOTKEYS
           ------------------------------------------------------------------------- */
        function closeApp() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.close) {
                window.pywebview.api.close();
            } else {
                window.close();
            }
        }

        function minimizeWindow() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.minimize) {
                window.pywebview.api.minimize();
            }
        }

        function toggleSidebar() {
            const hubBody = document.querySelector('.hub-body');
            const toggle = document.getElementById('sidebar-toggle');
            const isCollapsed = hubBody.classList.toggle('sidebar-collapsed');
            toggle.setAttribute('aria-expanded', String(!isCollapsed));
            toggle.setAttribute('aria-label', isCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
            toggle.title = isCollapsed ? 'Expand sidebar' : 'Collapse sidebar';
        }

        /* -------------------------------------------------------------------------
           WINDOW RESIZING: 1-CLICK PRESETS & CORNER DRAG
           ------------------------------------------------------------------------- */
        const sizePresets = [
            { name: 'Normal', w: 800, h: 460 },
            { name: 'Large', w: 960, h: 560 },
            { name: 'Compact', w: 700, h: 390 }
        ];
        let sizePresetIdx = 0;

        function cycleWindowSize() {
            sizePresetIdx = (sizePresetIdx + 1) % sizePresets.length;
            const preset = sizePresets[sizePresetIdx];
            if (window.pywebview && window.pywebview.api && window.pywebview.api.resize_window) {
                window.pywebview.api.resize_window(preset.w, preset.h);
            }
            const btns = document.querySelectorAll('.btn-size-cycle');
            btns.forEach(b => {
                b.textContent = `📐 ${preset.name}`;
            });
        }

        // Frameless pywebview windows do not get Windows' native sizing border.
        // Add invisible corner hit areas and resize through pywebview instead,
        // keeping the transparent edge free of a drawn native frame.
        (function enableCornerResize() {
            const api = window.pywebview && window.pywebview.api;
            if (!api || !api.resize_window_from_corner) {
                window.addEventListener('pywebviewready', enableCornerResize, { once: true });
                return;
            }
            if (!document.body) return;

            const style = document.createElement('style');
            style.textContent = `
                .window-resize-handle {
                    position: fixed; z-index: 2147483647; width: 16px; height: 16px;
                    background: transparent; pointer-events: auto; user-select: none;
                    -webkit-user-select: none; touch-action: none;
                }
                .window-resize-n { top: 0; left: 16px; right: 16px; width: auto; height: 8px; cursor: ns-resize; }
                .window-resize-s { bottom: 0; left: 16px; right: 16px; width: auto; height: 8px; cursor: ns-resize; }
                .window-resize-w { left: 0; top: 16px; bottom: 16px; width: 8px; height: auto; cursor: ew-resize; }
                .window-resize-e { right: 0; top: 16px; bottom: 16px; width: 8px; height: auto; cursor: ew-resize; }
                .window-resize-nw { top: 0; left: 0; cursor: nwse-resize; }
                .window-resize-ne { top: 0; right: 0; cursor: nesw-resize; }
                .window-resize-sw { bottom: 0; left: 0; cursor: nesw-resize; }
                .window-resize-se { bottom: 0; right: 0; cursor: nwse-resize; }
            `;
            document.head.appendChild(style);

            let drag = null;
            let lastResizeAt = 0;
            ['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se'].forEach(edge => {
                const handle = document.createElement('div');
                handle.className = `window-resize-handle window-resize-${edge}`;
                handle.dataset.resizeEdge = edge;
                handle.setAttribute('aria-hidden', 'true');
                document.body.appendChild(handle);
            });

            // pywebview easy_drag listens for bubbling mousedown events;
            // consume corner presses first so they resize rather than move.
            window.addEventListener('mousedown', event => {
                const handle = event.target.closest('.window-resize-handle');
                if (!handle || event.button !== 0) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                const corner = handle.dataset.resizeEdge;
                drag = {
                    corner,
                    x: event.screenX,
                    y: event.screenY,
                    width: window.outerWidth,
                    height: window.outerHeight,
                };
                document.body.style.cursor = getComputedStyle(handle).cursor;
            }, true);

            function resizeFromPointer(event, force) {
                if (!drag) return;
                const now = performance.now();
                if (!force && now - lastResizeAt < 32) return;
                lastResizeAt = now;

                const dx = event.screenX - drag.x;
                const dy = event.screenY - drag.y;
                const west = drag.corner.includes('w');
                const north = drag.corner.includes('n');
                const width = drag.width + (west ? -dx : dx);
                const height = drag.height + (north ? -dy : dy);
                api.resize_window_from_corner(width, height, drag.corner);
            }

            window.addEventListener('mousemove', event => resizeFromPointer(event, false));
            window.addEventListener('mouseup', event => {
                if (!drag) return;
                resizeFromPointer(event, true);
                drag = null;
                document.body.style.cursor = '';
            });
        })();

        function showStealthToast(message) {
            let container = document.querySelector('.toast-container');
            if (!container) {
                container = document.createElement('div');
                container.className = 'toast-container';
                document.body.appendChild(container);
            }
            container.innerHTML = '';
            const pill = document.createElement('div');
            pill.className = 'toast-pill';
            pill.innerHTML = `<span>${message}</span>`;
            container.appendChild(pill);
            setTimeout(() => {
                if (pill.parentNode === container) {
                    container.removeChild(pill);
                }
            }, 2200);
        }

        function toggleClickThrough() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_click_through) {
                window.pywebview.api.toggle_click_through().then(isActive => {
                    showStealthToast(isActive ? 'Click-Through: ON — Press Ctrl+M to disable (auto-off in 30s)' : 'Click-Through: Off (Normal clicks)');
                    const btns = document.querySelectorAll('.btn-click-through');
                    btns.forEach(b => b.classList.toggle('active', Boolean(isActive)));
                });
            } else {
                showStealthToast('Click-Through: Desktop overlay mode');
            }
        }

        window.addEventListener('keydown', (e) => {
            // Hotkey Ctrl + [ : increase transparency (decrease opacity)
            if (e.ctrlKey && e.key === '[') {
                e.preventDefault();
                const slider = document.getElementById('background-opacity') || document.getElementById('quick-opacity-slider');
                const cur = slider ? parseInt(slider.value, 10) || 61 : 61;
                const nextVal = Math.max(0, cur - 10);
                queuePreferenceSave('background_opacity', nextVal);
                showStealthToast(`Glass Transparency: ${nextVal}%`);
            }
            // Hotkey Ctrl + ] : decrease transparency (increase opacity)
            if (e.ctrlKey && e.key === ']') {
                e.preventDefault();
                const slider = document.getElementById('background-opacity') || document.querySelector('.quick-opacity-range');
                const cur = slider ? parseInt(slider.value, 10) || 61 : 61;
                const nextVal = Math.min(100, cur + 10);
                queuePreferenceSave('background_opacity', nextVal);
                showStealthToast(`Glass Transparency: ${nextVal}%`);
            }
            // Hotkey Ctrl + M : Toggle click-through mode (from reference app!)
            if (e.ctrlKey && (e.key === 'm' || e.key === 'M')) {
                e.preventDefault();
                toggleClickThrough();
            }
        });

        window.addEventListener('pywebviewready', () => {
            const slider = document.getElementById('background-opacity') || document.querySelector('.quick-opacity-range');
            const opacity = slider ? Number(slider.value) : 61;
            if (window.pywebview && window.pywebview.api && window.pywebview.api.set_opacity) {
                const nativeAlpha = Math.max(40, Math.min(255, Math.round((opacity / 100) * 255)));
                window.pywebview.api.set_opacity(nativeAlpha);
            }
        });

        /* -------------------------------------------------------------------------
           INITIALIZE ON LOAD
           ------------------------------------------------------------------------- */
        window.addEventListener('DOMContentLoaded', () => {
            bindProfileSettings();
            loadProfileSettings();
            loadDashboardNotes();
            loadCreditsData();
            initWebSocket();
            const hash = window.location.hash;
            const viewParam = urlParams.get('view');
            if (hash === '#copilot' || viewParam === 'copilot') {
                switchToCopilotView(false);
            }
        });
