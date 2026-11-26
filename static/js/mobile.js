// State variables
let socket = null;
let currentMode = 'general';
let currentLanguage = 'python';
let isListening = false;
let recognition = null;
let speechDebounceTimer = null;
let currentFontSize = 16;
let isHostDisconnected = false;

// Elements
const connectionBadge = document.getElementById('connection-badge');
const answersFeed = document.getElementById('answers-feed');
const thinkingBox = document.getElementById('thinking-box');
const thinkingLabel = document.getElementById('thinking-label');
const transcriptCard = document.getElementById('transcript-card');
const transcriptText = document.getElementById('transcript-text');
const btnListen = document.getElementById('btn-listen');
const listenLabel = document.getElementById('listen-label');
const btnSnip = document.getElementById('btn-snip');
const inputPrompt = document.getElementById('input-prompt');
const btnSend = document.getElementById('btn-send');
const blackoutScreen = document.getElementById('blackout-screen');
const settingsModal = document.getElementById('settings-modal');
const photoInput = document.getElementById('photo-input');

// Security: Pairing Token extraction
const urlParams = new URLSearchParams(window.location.search);
let pairingToken = urlParams.get('token') || (document.cookie.match(/(?:^|;\s*)pairing_token=([^;]+)/) || [])[1] || localStorage.getItem('pairing_token') || '';
if (urlParams.get('token')) {
    localStorage.setItem('pairing_token', urlParams.get('token'));
}

// Authenticated fetch helper
function authFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (options.body instanceof FormData) {
        if (pairingToken) {
            options.headers['X-Pairing-Token'] = pairingToken;
        }
    } else {
        if (!options.headers['Content-Type']) {
            options.headers['Content-Type'] = 'application/json';
        }
        if (pairingToken) {
            options.headers['X-Pairing-Token'] = pairingToken;
        }
    }
    return fetch(url, options);
}

// Initialize WebSockets
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const tokenParam = pairingToken ? `?token=${encodeURIComponent(pairingToken)}&client=mobile` : '?client=mobile';
    const wsUrl = `${protocol}//${window.location.host}/ws${tokenParam}`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Connected to Interview Copilot Hub');
        if (connectionBadge) {
            connectionBadge.style.background = '#10b981';
            connectionBadge.title = 'Connected';
        }
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleIncomingMessage(msg);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };

    socket.onclose = (event) => {
        if ((event && (event.code === 4001 || event.code === 1008)) || isHostDisconnected) {
            console.warn('Disconnected by host PC or invalid pairing token. Reconnect aborted.');
            if (connectionBadge) {
                connectionBadge.style.background = '#ef4444';
                connectionBadge.title = 'Disconnected by Host PC';
            }
            showMobileDisconnectedOverlay();
            return;
        }
        console.warn('WebSocket disconnected. Reconnecting in 2s...');
        if (connectionBadge) {
            connectionBadge.style.background = '#ef4444';
            connectionBadge.title = 'Disconnected (Reconnecting...)';
        }
        setTimeout(initWebSocket, 2000);
    };

    socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
    };
}

// Handle Incoming Server Events
function handleIncomingMessage(msg) {
    switch (msg.type) {
        case 'init':
        case 'settings_updated':
            if (msg.mode) currentMode = msg.mode;
            if (msg.language) currentLanguage = msg.language;
            if (typeof msg.credits_balance !== 'undefined') {
                updateMobileCreditsDisplay(msg.credits_balance);
            }
            if (msg.notes) {
                cachedMobileNotes = msg.notes;
                renderMobileNotes(cachedMobileNotes);
            }
            if (msg.type === 'init') {
                if (msg.copilot_active && msg.copilot_start_time) {
                    startCopilotTimerAt(msg.copilot_start_time);
                } else {
                    resetCopilotTimer();
                }
            }
            if (typeof msg.has_resume !== 'undefined') {
                updateMobileResumeUI(msg.has_resume, msg.resume_filename);
            }
            break;

        case 'copilot_started':
            startCopilotTimerAt(msg.start_time || Date.now());
            break;

        case 'copilot_ended':
            stopListening();
            resetCopilotTimer();
            if (msg.reason === 'insufficient_credits') {
                showErrorToast(msg.message || '⚠️ Call ended: Insufficient credits.');
            }
            break;

        case 'error':
            if (thinkingBox) thinkingBox.classList.remove('active');
            showErrorToast(msg.message || 'Error occurred.');
            break;

        case 'companion_disconnected':
            isHostDisconnected = true;
            stopListening();
            resetCopilotTimer();
            showMobileDisconnectedOverlay();
            break;

        case 'credits_updated':
            if (typeof msg.balance !== 'undefined') {
                updateMobileCreditsDisplay(msg.balance);
            }
            const creditsModal = document.getElementById('credits-modal');
            if (creditsModal && creditsModal.classList.contains('active')) {
                loadMobileCreditsData();
            }
            break;

        case 'notes_updated':
            cachedMobileNotes = msg.notes || [];
            renderMobileNotes(cachedMobileNotes);
            break;

        case 'speech_interim':
            showTranscript(msg.text);
            break;

        case 'status':
            if (msg.status === 'thinking') {
                thinkingBox.classList.add('active');
                thinkingLabel.textContent = msg.message || (msg.is_snip ? 'Analyzing Code Screen...' : 'Generating natural spoken answer...');
            } else if (msg.status === 'capturing_screen') {
                thinkingBox.classList.add('active');
                thinkingLabel.textContent = 'Capturing PC Screen...';
            } else if (msg.status === 'error') {
                thinkingBox.classList.remove('active');
                showErrorToast(msg.message || 'An error occurred.');
            }
            break;

        case 'new_answer':
            thinkingBox.classList.remove('active');
            transcriptCard.classList.remove('visible');
            if (isListening) {
                stopListening();
            }
            renderAnswerCard(msg.data);
            break;

        case 'panic_clear':
            answersFeed.innerHTML = `
                <div id="empty-state" class="empty-state">
                    <div class="empty-title">Ready for Interview</div>
                    <div class="empty-subtitle">Solutions stream here live as questions are asked.</div>
                </div>
            `;
            transcriptCard.classList.remove('visible');
            thinkingBox.classList.remove('active');
            break;

        case 'resume_updated':
            updateMobileResumeUI(true, msg.filename, msg.length);
            showErrorToast(`Resume loaded: ${msg.filename} (${msg.length} characters)`);
            break;

        case 'resume_deleted':
            updateMobileResumeUI(false);
            const resArea = document.getElementById('textarea-resume');
            if (resArea) resArea.value = '';
            showErrorToast('Resume was removed.');
            break;

        case 'history_cleared':
            showErrorToast('Conversation memory cleared.');
            break;
    }
}

// Simple & clean Markdown Formatter
function formatMarkdown(text) {
    if (!text) return '';
    let html = text
        // Escape HTML
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        // Code blocks ```code```
        .replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre><code>${code.trim()}</code><button class="copy-btn" onclick="copyCode(this)">Copy</button></pre>`;
        })
        // Inline code `code`
        .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.1);padding:2px 5px;border-radius:4px;color:#38bdf8;">$1</code>')
        // Bold **text**
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        // Headings ### Heading
        .replace(/^### (.*$)/gim, '<h4 style="color:#38bdf8;margin:12px 0 6px 0;font-size:1.05rem;">$1</h4>')
        .replace(/^## (.*$)/gim, '<h3 style="color:#10b981;margin:14px 0 8px 0;font-size:1.15rem;">$1</h3>')
        // Lists
        .replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>');

    // Wrap li in ul
    html = html.replace(/(<li>.*<\/li>)/gims, '<ul style="margin:8px 0 10px 18px;">$1</ul>');
    // Paragraphs
    html = html.split('\n\n').map(p => {
        p = p.trim();
        if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul')) return p;
        return `<p style="margin-bottom:8px;">${p}</p>`;
    }).join('');

    return html;
}

// Render Answer Card
function renderAnswerCard(data) {
    if (!data.success) {
        showErrorToast(data.error || 'Failed to generate solution.');
        return;
    }

    // Clear empty state illustration on first answer
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();

    const card = document.createElement('div');
    card.className = 'answer-card';

    const isSnip = Boolean(data.is_screenshot);
    const speaker = data.speaker || (isSnip ? 'Screen Vision' : 'Candidate');
    let speakerBadge = '';
    if (speaker === 'Interviewer') {
        speakerBadge = `<span class="answer-badge badge-interviewer">Interviewer</span>`;
    } else if (speaker === 'Screen Vision') {
        speakerBadge = `<span class="answer-badge badge-snip">Screen Snip</span>`;
    } else {
        speakerBadge = `<span class="answer-badge badge-candidate">Candidate</span>`;
    }

    const questionHtml = data.question 
        ? `<div class="question-text">Q: "${data.question}"</div>` 
        : (isSnip ? `<div class="question-text">Captured Code Screen</div>` : '');

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    card.innerHTML = `
        <div class="answer-header">
            <div style="display: flex; gap: 6px; align-items: center;">
                ${speakerBadge}
            </div>
            <span class="answer-time">${timeStr}</span>
        </div>
        ${questionHtml}
        <div class="answer-body" style="font-size: ${currentFontSize}px;">
            ${formatMarkdown(data.answer)}
        </div>
    `;

    // Prepend to top
    answersFeed.insertBefore(card, answersFeed.firstChild);

    // Vibrate gently on mobile to notify answer arrived
    if (navigator.vibrate) {
        try { navigator.vibrate(60); } catch (e) { }
    }
}

// Copy Code helper
window.copyCode = function(button) {
    const code = button.previousElementSibling.innerText;
    navigator.clipboard.writeText(code).then(() => {
        button.innerText = 'Copied!';
        setTimeout(() => button.innerText = 'Copy', 1500);
    });
};

function openSpeechHelpModal() {
    const modal = document.getElementById('speech-help-modal');
    if (modal) {
        modal.classList.add('active');
        const hint = document.getElementById('help-modal-ip-hint');
        if (hint) hint.textContent = `${location.protocol}//${location.host}`;
    }
}

function closeSpeechHelpModal() {
    const modal = document.getElementById('speech-help-modal');
    if (modal) modal.classList.remove('active');
}

function showMobileDisconnectedOverlay() {
    isHostDisconnected = true;
    stopListening();
    resetCopilotTimer();
    const overlay = document.getElementById('mobile-disconnected-overlay');
    if (overlay) {
        overlay.style.display = 'flex';
    }
    const sessionBtn = document.getElementById('btn-session');
    if (sessionBtn) {
        sessionBtn.disabled = true;
        sessionBtn.style.opacity = '0.5';
        sessionBtn.style.pointerEvents = 'none';
    }
    if (btnListen) {
        btnListen.disabled = true;
        btnListen.style.opacity = '0.5';
        btnListen.style.pointerEvents = 'none';
    }
    if (btnSnip) {
        btnSnip.disabled = true;
        btnSnip.style.opacity = '0.5';
        btnSnip.style.pointerEvents = 'none';
    }
    if (connectionBadge) {
        connectionBadge.style.background = '#ef4444';
        connectionBadge.title = 'Disconnected by Host PC';
    }
}
window.showMobileDisconnectedOverlay = showMobileDisconnectedOverlay;

// Primary Session Controller (Start Copilot / End Session)
function updateSessionButtonUI(isActive) {
    isCopilotActive = Boolean(isActive);
    const btn = document.getElementById('btn-session');
    const icon = document.getElementById('session-icon');
    const label = document.getElementById('session-label');
    if (!btn) return;
    if (isActive) {
        btn.className = 'action-btn btn-session btn-session-end';
        if (icon) icon.textContent = '⏹';
        if (label) label.textContent = 'End Session';
        btn.title = 'End Copilot Interview Session';
    } else {
        btn.className = 'action-btn btn-session btn-session-start';
        if (icon) icon.textContent = '▶';
        if (label) label.textContent = 'Start Copilot';
        btn.title = 'Start Copilot Interview Session';
    }
}

async function toggleCopilotSession() {
    if (isHostDisconnected) {
        showMobileDisconnectedOverlay();
        showErrorToast('Disconnected from host PC. Please scan QR code again.');
        return;
    }
    if (isCopilotActive) {
        if (!confirm("End current interview session? This will stop timer and record elapsed session time.")) {
            return;
        }
        try {
            await authFetch('/api/history/session/end', { method: 'POST' });
        } catch (e) {
            console.error('Failed to end session:', e);
        }
        stopListening();
        resetCopilotTimer();
        updateSessionButtonUI(false);
        showErrorToast('Interview session ended.');
    } else {
        try {
            const res = await authFetch('/api/history/session/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Device': 'mobile' },
                body: JSON.stringify({ source: 'mobile' })
            });
            const data = await res.json();
            if (!res.ok) {
                if (res.status === 403) {
                    showMobileDisconnectedOverlay();
                }
                showErrorToast(data.detail || 'Cannot start session.');
                return;
            }
            const startTime = (data && data.start_time) ? data.start_time : Date.now();
            startCopilotTimerAt(startTime);
            updateSessionButtonUI(true);
            showErrorToast('Interview session started!');
        } catch (e) {
            console.error('Failed to start session:', e);
            showErrorToast('Failed to start session: ' + e.message);
        }
    }
}
window.toggleCopilotSession = toggleCopilotSession;

// Web Speech Recognition for Live Audio Listening
function toggleListening() {
    if (isListening) {
        stopListening();
    } else {
        startListening();
    }
}

async function startListening() {
    if (isHostDisconnected) {
        showMobileDisconnectedOverlay();
        showErrorToast('Disconnected from host PC. Please scan QR code again.');
        return;
    }
    // If interview session is not started yet, auto-start the session as well
    if (!isCopilotActive) {
        try {
            const res = await authFetch('/api/history/session/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Device': 'mobile' },
                body: JSON.stringify({ source: 'mobile' })
            });
            const data = await res.json();
            if (!res.ok) {
                if (res.status === 403) {
                    showMobileDisconnectedOverlay();
                }
                showErrorToast(data.detail || 'Cannot start session due to insufficient credits.');
                return;
            }
            const startTime = (data && data.start_time) ? data.start_time : Date.now();
            startCopilotTimerAt(startTime);
            updateSessionButtonUI(true);
        } catch (e) {
            showErrorToast('Failed to start session: ' + e.message);
            return;
        }
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        openSpeechHelpModal();
        return;
    }

    try {
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
            isListening = true;
            if (btnListen) btnListen.classList.add('listening');
            if (listenLabel) listenLabel.textContent = 'Listening...';
            transcriptCard.classList.add('visible');
        };

        recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }

            const currentText = (finalTranscript || interimTranscript).trim();
            showTranscript(currentText);

            // Sync with backend & other devices
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    action: 'speech_interim',
                    text: currentText
                }));
            }

            // Debounced trigger when speaker finishes a sentence
            clearTimeout(speechDebounceTimer);
            if (finalTranscript.trim().length > 10) {
                speechDebounceTimer = setTimeout(() => {
                    sendFinalQuestion(finalTranscript.trim());
                }, 1200);
            }
        };

        recognition.onerror = (event) => {
            console.warn('Speech Recognition error:', event.error);
            if (event.error === 'not-allowed') {
                showErrorToast('Microphone access denied in browser.');
                stopListening();
            }
        };

        recognition.onend = () => {
            if (isListening) {
                try { recognition.start(); } catch (e) {}
            }
        };

        recognition.start();

    } catch (e) {
        console.error('Error starting SpeechRecognition:', e);
        stopListening();
    }
}

function stopListening() {
    isListening = false;
    if (btnListen) btnListen.classList.remove('listening');
    if (listenLabel) listenLabel.textContent = 'Live Listen';
    if (recognition) {
        try { recognition.stop(); } catch(e) {}
        recognition = null;
    }
}

function showTranscript(text) {
    if (!text) return;
    transcriptCard.classList.add('visible');
    transcriptText.textContent = text;
}

function sendFinalQuestion(question) {
    if (!question || !socket) return;
    socket.send(JSON.stringify({
        action: 'speech_final',
        text: question,
        mode: currentMode
    }));
}

// Screen Snip Trigger
function triggerScreenSnip() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            action: 'trigger_snip',
            mode: currentMode
        }));
    } else {
        authFetch('/api/snip', {
            method: 'POST',
            body: JSON.stringify({ mode: currentMode })
        });
    }
}

// Photo / Screenshot Upload from Phone
function handlePhotoUpload(input) {
    if (!input.files || input.files.length === 0) return;
    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);
    formData.append('mode', currentMode);

    thinkingBox.classList.add('active');
    thinkingLabel.textContent = 'Analyzing Photo...';

    authFetch('/api/upload-image', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        thinkingBox.classList.remove('active');
        renderAnswerCard(data);
    })
    .catch(err => {
        thinkingBox.classList.remove('active');
        showErrorToast('Upload failed: ' + err);
    });
}

// Text Input Submit
function submitTextQuestion() {
    const q = inputPrompt.value.trim();
    if (!q) return;

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            action: 'ask',
            question: q,
            mode: currentMode
        }));
    } else {
        authFetch('/api/ask', {
            method: 'POST',
            body: JSON.stringify({ question: q, mode: currentMode })
        });
    }

    inputPrompt.value = '';
}

// Stealth Blackout
function toggleBlackout() {
    blackoutScreen.classList.toggle('active');
}

// Panic Clear (Clears answers & memory without resetting billing timer)
function triggerPanic() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: 'panic' }));
    }
    answersFeed.innerHTML = `
        <div id="empty-state" class="empty-state">
            <div class="empty-title">Ready for Interview</div>
            <div class="empty-subtitle">Solutions stream here live as questions are asked.</div>
        </div>
    `;
    transcriptCard.classList.remove('visible');
    thinkingBox.classList.remove('active');
    showErrorToast('All answers cleared.');
}

// Handle Resume File Upload from Phone
function handleResumeUpload(input) {
    if (!input.files || input.files.length === 0) return;
    const file = input.files[0];
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showErrorToast('Upload a PDF resume only.');
        input.value = '';
        return;
    }
    if (file.size > 1024 * 1024) {
        showErrorToast('Resume file must be 1 MB or smaller.');
        input.value = '';
        return;
    }
    const formData = new FormData();
    formData.append('file', file);

    thinkingBox.classList.add('active');
    thinkingLabel.textContent = `Parsing ${file.name}...`;

    authFetch('/api/upload-resume', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        thinkingBox.classList.remove('active');
        if (data.success) {
            const fullText = data.text || data.preview || '';
            const textarea = document.getElementById('textarea-resume');
            if (textarea) textarea.value = fullText;
            updateMobileResumeUI(true, file.name, data.length);
            showErrorToast(`Resume saved: ${file.name}`);
        } else {
            showErrorToast(data.detail || 'Resume upload failed.');
        }
    })
    .catch(err => {
        thinkingBox.classList.remove('active');
        showErrorToast('Resume upload error: ' + err);
    });
}

// Delete Candidate Resume
async function deleteMobileResume() {
    if (!confirm('Are you sure you want to remove this resume?')) return;
    try {
        const res = await authFetch('/api/resume', { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            const textarea = document.getElementById('textarea-resume');
            if (textarea) textarea.value = '';
            updateMobileResumeUI(false);
            showErrorToast('Resume removed. You can upload a fresh resume.');
        } else {
            showErrorToast('Failed to delete resume.');
        }
    } catch (e) {
        showErrorToast('Error deleting resume.');
    }
}

// Update Mobile Resume Card UI
function updateMobileResumeUI(hasResume, filename = '', charCount = 0) {
    const card = document.getElementById('mobile-saved-resume-card');
    const fnEl = document.getElementById('mobile-resume-filename');
    const metaEl = document.getElementById('mobile-resume-meta');
    const uploadBtn = document.getElementById('btn-mobile-upload-resume');

    if (hasResume) {
        if (card) card.style.display = 'flex';
        if (fnEl) fnEl.textContent = filename || 'resume.pdf';
        if (metaEl) metaEl.textContent = charCount ? `Ready for AI (${charCount} chars)` : 'Saved on this device';
        if (uploadBtn) uploadBtn.textContent = 'Replace PDF';
    } else {
        if (card) card.style.display = 'none';
        if (uploadBtn) uploadBtn.textContent = 'Upload PDF';
    }
}

// Font Size Scaling
function adjustFontSize(delta) {
    currentFontSize = Math.max(12, Math.min(26, currentFontSize + delta));
    document.querySelectorAll('.answer-body').forEach(body => {
        body.style.fontSize = `${currentFontSize}px`;
    });
}

/* -------------------------------------------------------------------------
   INTERVIEW SESSION RUNNING TIMER (FOR CLIENT BILLING & TRACKING)
   ------------------------------------------------------------------------- */
let copilotTimerInterval = null;
let copilotInterviewStartTime = null;
let isCopilotActive = false;

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
    if (!display) return;
    if (!copilotInterviewStartTime) {
        display.textContent = '00:00:00';
        return;
    }
    const elapsed = Date.now() - copilotInterviewStartTime;
    display.textContent = formatInterviewDuration(elapsed);
}

function startCopilotTimerAt(startTime) {
    copilotInterviewStartTime = startTime ? parseInt(startTime, 10) : Date.now();
    isCopilotActive = true;
    updateSessionButtonUI(true);
    try {
        sessionStorage.setItem('copilot_interview_start', String(copilotInterviewStartTime));
    } catch (e) { }

    const badge = document.getElementById('copilot-timer-badge');
    if (badge) badge.classList.add('active');

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
    isCopilotActive = false;
    copilotInterviewStartTime = null;
    updateSessionButtonUI(false);
    try {
        sessionStorage.removeItem('copilot_interview_start');
    } catch (e) { }
    const badge = document.getElementById('copilot-timer-badge');
    if (badge) badge.classList.remove('active');
    const display = document.getElementById('copilot-timer-display');
    if (display) display.textContent = '00:00:00';
}

/* -------------------------------------------------------------------------
   MOBILE CREDITS & HISTORY MODULE
   ------------------------------------------------------------------------- */
let cachedMobileTransactions = [];
let currentMobileTxFilter = 'all';

function updateMobileCreditsDisplay(balance) {
    const formatted = Number(balance ?? 0).toFixed(2);
    const badge = document.getElementById('mobile-credit-points');
    if (badge) badge.textContent = formatted;
    const modalBal = document.getElementById('modal-credit-balance-val');
    if (modalBal) modalBal.textContent = formatted;
}

function openCreditsModal() {
    const modal = document.getElementById('credits-modal');
    if (modal) modal.classList.add('active');
    loadMobileCreditsData();
}

function closeCreditsModal() {
    const modal = document.getElementById('credits-modal');
    if (modal) modal.classList.remove('active');
}

async function loadMobileCreditsData() {
    try {
        const res = await authFetch('/api/credits');
        if (!res.ok) return;
        const data = await res.json();
        updateMobileCreditsDisplay(data.balance ?? 0);
        
        const emailEl = document.getElementById('modal-credit-user-email');
        if (emailEl) {
            emailEl.textContent = data.user_email ? data.user_email : (data.user_name ? `${data.user_name}` : 'Saved on this device');
        }

        cachedMobileTransactions = data.transactions || [];
        renderMobileTransactions(cachedMobileTransactions);
    } catch (err) {
        console.error('Error loading mobile credits:', err);
    }
}

function filterMobileTransactions(filter) {
    currentMobileTxFilter = filter;
    document.querySelectorAll('.credit-filter-pill-mobile').forEach(pill => {
        pill.classList.toggle('active', pill.dataset.filter === filter);
    });
    renderMobileTransactions(cachedMobileTransactions);
}

function renderMobileTransactions(txList) {
    const container = document.getElementById('mobile-credits-tx-list');
    if (!container) return;

    let filtered = txList || [];
    if (currentMobileTxFilter === 'credit') {
        filtered = filtered.filter(t => t.type === 'credit');
    } else if (currentMobileTxFilter === 'debit') {
        filtered = filtered.filter(t => t.type === 'debit');
    }

    if (filtered.length === 0) {
        container.innerHTML = '<p class="history-empty" style="text-align:center;padding:16px;color:#64748b;font-size:0.75rem;">No transactions recorded.</p>';
        return;
    }

    container.innerHTML = filtered.map(tx => {
        const isCredit = tx.type === 'credit';
        const sign = isCredit ? '+' : '-';
        const amountClass = isCredit ? 'amount-credit' : 'amount-used';
        const displayDesc = isCredit ? 'Credit Point Added' : 'Credit Point Used';
        
        let detailsHtml = '';
        if (isCredit) {
            detailsHtml = tx.code ? `Code: ${tx.code}` : (tx.description || '');
        } else {
            const parts = [];
            if (tx.duration_sec) parts.push(`${tx.duration_sec}s`);
            if (tx.snaps_taken) parts.push(`${tx.snaps_taken} snip${tx.snaps_taken > 1 ? 's' : ''}`);
            if (tx.qa_count) parts.push(`${tx.qa_count} QA`);
            detailsHtml = parts.join(' • ') || (tx.description || '');
        }

        const rawDate = tx.timestamp || (tx.created_at ? tx.created_at.replace('T', ' ').slice(0, 16) : '');
        let dateStr = rawDate;
        try {
            const parts = String(rawDate).trim().split(/\s+/);
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
                    dateStr = `${datePart} ${hoursStr}:${minutes} ${ampm}`;
                }
            }
        } catch (_) {}

        return `
            <div class="credit-tx-item-mobile">
                <div>
                    <div class="credit-tx-desc-mobile">${displayDesc}</div>
                    <div class="credit-tx-meta-mobile">${detailsHtml ? detailsHtml + ' • ' : ''}${dateStr}</div>
                </div>
                <div class="credit-tx-amount-mobile ${amountClass}">${sign}${Number(Math.abs(tx.amount || 0)).toFixed(2)}</div>
            </div>
        `;
    }).join('');
}

let mobileCreditRedeemStatusTimer = null;
function setMobileCreditRedeemStatus(message, color, autoDismiss = true) {
    const status = document.getElementById('mobile-credit-redeem-status');
    if (!status) return;
    clearTimeout(mobileCreditRedeemStatusTimer);
    status.textContent = message;
    status.style.color = color;
    mobileCreditRedeemStatusTimer = autoDismiss && message ? setTimeout(() => {
        status.textContent = '';
        mobileCreditRedeemStatusTimer = null;
    }, 5000) : null;
}

async function redeemMobileCreditCode() {
    const input = document.getElementById('mobile-credit-code-input');
    const btn = document.getElementById('btn-mobile-redeem');
    if (!input) return;

    const code = input.value.trim();
    if (!code) {
        setMobileCreditRedeemStatus('Please enter a 16-character credit code.', '#ef4444');
        return;
    }

    if (btn) btn.disabled = true;
    setMobileCreditRedeemStatus('Verifying code...', '#38bdf8', false);

    try {
        const res = await authFetch('/api/credits/redeem', {
            method: 'POST',
            body: JSON.stringify({ code: code })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            input.value = '';
            setMobileCreditRedeemStatus(`Success! Added +${data.credited} credits.`, '#10b981');
            updateMobileCreditsDisplay(data.balance);
            showErrorToast(`Recharged +${data.credited} credit points!`);
            loadMobileCreditsData();
        } else {
            setMobileCreditRedeemStatus(data.detail || data.error || 'Invalid or expired code.', '#ef4444');
        }
    } catch (err) {
        setMobileCreditRedeemStatus('Network error. Try again.', '#ef4444');
    } finally {
        if (btn) btn.disabled = false;
    }
}

/* -------------------------------------------------------------------------
   MOBILE QUICK NOTES & CHEAT SHEET MODULE
   ------------------------------------------------------------------------- */
let cachedMobileNotes = [];

function openNotesModal() {
    const modal = document.getElementById('notes-modal');
    if (modal) modal.classList.add('active');
    loadMobileNotes();
}

function closeNotesModal() {
    const modal = document.getElementById('notes-modal');
    if (modal) modal.classList.remove('active');
}

async function loadMobileNotes() {
    try {
        const res = await authFetch('/api/notes');
        if (!res.ok) return;
        const data = await res.json();
        cachedMobileNotes = data.notes || [];
        renderMobileNotes(cachedMobileNotes);
    } catch (e) { }
}

function filterMobileNotes(query) {
    query = (query || '').toLowerCase().trim();
    if (!query) {
        renderMobileNotes(cachedMobileNotes);
        return;
    }
    const filtered = cachedMobileNotes.filter(n =>
        (n.title && n.title.toLowerCase().includes(query)) ||
        (n.content && n.content.toLowerCase().includes(query))
    );
    renderMobileNotes(filtered);
}

function renderMobileNotes(notes) {
    const container = document.getElementById('mobile-notes-list');
    if (!container) return;

    if (!notes || notes.length === 0) {
        container.innerHTML = '<p style="color:#64748b;font-size:0.75rem;text-align:center;padding:16px;">No saved notes yet. Add them in desktop Hub!</p>';
        return;
    }

    container.innerHTML = notes.map((note, idx) => {
        const title = (note.title || 'Untitled Note').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
        const content = (note.content || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
        return `
            <div class="note-item-mobile">
                <div class="note-header-mobile" onclick="toggleMobileNote('${note.id || idx}')">
                    <span>${title}</span>
                    <span style="font-size:0.7rem;color:#94a3b8;">▼</span>
                </div>
                <div id="mobile-note-body-${note.id || idx}" class="note-content-mobile">${content}</div>
            </div>
        `;
    }).join('');
}

function toggleMobileNote(id) {
    const body = document.getElementById(`mobile-note-body-${id}`);
    if (body) {
        body.classList.toggle('open');
    }
}

// Settings Modal
function openSettings() {
    settingsModal.classList.add('active');
    authFetch('/api/settings')
        .then(res => res.json())
        .then(data => {
            if (data.profile_name !== undefined) {
                const nameEl = document.getElementById('input-profile-name');
                if (nameEl) nameEl.value = data.profile_name || '';
            }
            if (data.profile_email !== undefined) {
                const emailEl = document.getElementById('input-profile-email');
                if (emailEl) emailEl.value = data.profile_email || '';
            }
            if (data.profile_phone !== undefined) {
                const phoneEl = document.getElementById('input-profile-phone');
                if (phoneEl) phoneEl.value = data.profile_phone || '';
            }
            if (data.has_resume) {
                updateMobileResumeUI(true, data.resume_filename, data.resume ? data.resume.length : 0);
            } else {
                updateMobileResumeUI(false);
            }
            if (data.resume !== undefined) {
                const resumeEl = document.getElementById('textarea-resume');
                if (resumeEl) resumeEl.value = data.resume || '';
            }
            if (data.jd !== undefined) {
                const jdEl = document.getElementById('textarea-jd');
                if (jdEl) jdEl.value = data.jd || '';
            }
        })
        .catch(() => {
            showErrorToast('Failed to load settings.');
        });
}

function closeSettings() {
    settingsModal.classList.remove('active');
}

function saveSettings() {
    const profileName = (document.getElementById('input-profile-name')?.value || '').trim();
    const profileEmail = (document.getElementById('input-profile-email')?.value || '').trim();
    const profilePhone = (document.getElementById('input-profile-phone')?.value || '').trim();
    const resume = (document.getElementById('textarea-resume')?.value || '');
    const jd = (document.getElementById('textarea-jd')?.value || '');

    const payload = {
        profile_name: profileName,
        profile_email: profileEmail,
        profile_phone: profilePhone,
        resume: resume,
        jd: jd,
        mode: currentMode
    };

    authFetch('/api/settings', {
        method: 'POST',
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        closeSettings();
        if (resume.trim()) {
            updateMobileResumeUI(true, 'resume.pdf', resume.length);
        } else {
            updateMobileResumeUI(false);
        }
        showErrorToast('Configuration saved!');
    })
    .catch(() => {
        showErrorToast('Error saving configuration.');
    });
}

// Non-blocking in-app Toast Notification
let toastTimer = null;
function showErrorToast(msg) {
    const toast = document.getElementById('toast-notification');
    if (toast) {
        toast.textContent = msg;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            toast.classList.remove('show');
        }, 5000);
    } else {
        console.log('[Toast]:', msg);
    }
}

// Event Listeners setup
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    // Do NOT start timer on QR scan / load! Timer starts only when Copilot is started.
    authFetch('/api/copilot/status')
        .then(r => {
            if (r.status === 401 || r.status === 403) {
                showMobileDisconnectedOverlay();
                throw new Error('Unauthorized');
            }
            return r.json();
        })
        .then(data => {
            if (data && data.is_active && data.started_at) {
                startCopilotTimerAt(data.started_at);
            } else {
                resetCopilotTimer();
            }
        })
        .catch(() => {
            resetCopilotTimer();
        });

    loadMobileCreditsData();
    loadMobileNotes();

    // Action buttons
    if (btnListen) btnListen.addEventListener('click', toggleListening);
    if (btnSnip) btnSnip.addEventListener('click', triggerScreenSnip);

    // Text Input
    if (btnSend) btnSend.addEventListener('click', submitTextQuestion);
    if (inputPrompt) {
        inputPrompt.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitTextQuestion();
        });
    }

    // Blackout click to restore
    if (blackoutScreen) {
        blackoutScreen.addEventListener('click', () => blackoutScreen.classList.remove('active'));
    }

    // Prevent screen sleep on mobile when active (Wake Lock API)
    if ('wakeLock' in navigator) {
        try {
            navigator.wakeLock.request('screen');
        } catch (err) {}
    }
});
