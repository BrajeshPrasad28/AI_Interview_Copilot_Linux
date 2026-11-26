        let socket = null;
        let currentMode = 'qa_testing';  // Default to QA & Testing
        let isMicListening = false;
        let recognition = null;
        let speechDebounceTimer = null;
        let audioContext = null;
        let analyser = null;

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

        // Window Controls (minimize, close, pass-through)
        function minimizeWindow() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.minimize) {
                window.pywebview.api.minimize();
            }
        }

        function closeApp() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.close) {
                window.pywebview.api.close();
            } else {
                window.close();
            }
        }

        function toggleClickThrough() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_click_through) {
                window.pywebview.api.toggle_click_through().then(isActive => {
                    document.querySelectorAll('.btn-click-through').forEach(b => b.classList.toggle('active', isActive));
                });
            }
        }

        // Pairing Token extraction
        const urlParams = new URLSearchParams(window.location.search);
        const pairingToken = urlParams.get('token') || (document.cookie.match(/(?:^|;\s*)pairing_token=([^;]+)/) || [])[1] || window.INITIAL_PAIRING_TOKEN || '';

        let opacitySaveTimer = null;
        function updateBackgroundOpacity(value, save = true) {
            const num = Number(value);
            const val = Math.max(0, Math.min(100, Number.isFinite(num) ? num : 61));
            const card = document.getElementById('overlay-main-card');
            if (card) {
                card.style.setProperty('--bg-opacity', val / 100);
            }
            document.body.style.setProperty('--bg-opacity', val / 100);

            const quickSlider = document.getElementById('quick-opacity-slider');
            if (quickSlider && Number(quickSlider.value) !== val) {
                quickSlider.value = val;
            }
            const quickVal = document.getElementById('quick-opacity-val');
            if (quickVal) {
                quickVal.textContent = `${val}%`;
            }

            if (window.pywebview && window.pywebview.api && window.pywebview.api.set_opacity) {
                const nativeAlpha = Math.max(40, Math.min(255, Math.round((val / 100) * 255)));
                window.pywebview.api.set_opacity(nativeAlpha);
            }

            if (save) {
                clearTimeout(opacitySaveTimer);
                opacitySaveTimer = setTimeout(() => {
                    fetch('/api/settings', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Pairing-Token': pairingToken
                        },
                        body: JSON.stringify({ background_opacity: val })
                    }).catch(() => { });
                }, 300);
            }
        }

        async function loadInterfacePreferences() {
            try {
                const response = await fetch('/api/settings', {
                    headers: { 'X-Pairing-Token': pairingToken }
                });
                if (!response.ok) throw new Error('Could not load interface settings.');
                const settings = await response.json();
                if (Number.isFinite(Number(settings.background_opacity))) {
                    updateBackgroundOpacity(settings.background_opacity, false);
                }
                const card = document.getElementById('overlay-main-card');
                if (card) {
                    if (Number.isFinite(Number(settings.font_opacity))) {
                        card.style.setProperty('--answer-text-opacity', Number(settings.font_opacity) / 100);
                    }
                    if (Number.isFinite(Number(settings.response_font_size))) {
                        card.style.setProperty('--response-font-size', `${Number(settings.response_font_size)}px`);
                    }
                }
            } catch (error) {
                console.warn('Interface settings could not be loaded:', error);
            }
        }

        // Initialize WebSocket
        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const tokenParam = pairingToken ? `?token=${encodeURIComponent(pairingToken)}` : '';
            socket = new WebSocket(`${protocol}//${window.location.host}/ws${tokenParam}`);

            socket.onopen = () => {
                dot.style.background = '#10b981';
                if (statusInfo) statusInfo.textContent = 'Connected & Ready';
            };

            socket.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    handleMessage(msg);
                } catch (e) { }
            };

            socket.onclose = () => {
                dot.style.background = '#ef4444';
                if (statusInfo) statusInfo.textContent = 'Reconnecting...';
                setTimeout(initWebSocket, 2000);
            };
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
                    renderOverlayNotes(cachedNotes);
                }
                if (Number.isFinite(Number(msg.background_opacity))) {
                    updateBackgroundOpacity(msg.background_opacity, false);
                }
                if (msg.copilot_active && msg.copilot_start_time) {
                    copilotInterviewStartTime = msg.copilot_start_time;
                    startCopilotTimer(false);
                } else {
                    resetCopilotTimer();
                }
            } else if (msg.type === 'copilot_started') {
                copilotInterviewStartTime = msg.start_time || Date.now();
                startCopilotTimer(false);
            } else if (msg.type === 'copilot_ended') {
                resetCopilotTimer();
            } else if (msg.type === 'notes_updated') {
                cachedNotes = msg.notes || [];
                renderOverlayNotes(cachedNotes);
            } else if (msg.type === 'settings_updated') {
                if (Number.isFinite(Number(msg.background_opacity))) {
                    updateBackgroundOpacity(msg.background_opacity, false);
                }
                const card = document.getElementById('overlay-main-card');
                if (card) {
                    if (Number.isFinite(Number(msg.font_opacity))) {
                        card.style.setProperty('--answer-text-opacity', Number(msg.font_opacity) / 100);
                    }
                    if (Number.isFinite(Number(msg.response_font_size))) {
                        card.style.setProperty('--response-font-size', `${Number(msg.response_font_size)}px`);
                    }
                }
            } else if (msg.type === 'ptt_state') {
                if (typeof msg.loopback_active !== 'undefined') {
                    updateLoopbackUI(msg.loopback_active);
                }
            } else if (msg.type === 'loopback_status') {
                updateLoopbackUI(msg.is_active);
            } else if (msg.type === 'status' && msg.status === 'thinking') {
                // Show thinking banner at top without erasing previous answers
                clearTimeout(thinkingTimer);
                statusBannerText.textContent = msg.message || (msg.is_snip ? 'Analyzing Code Screen with Gemini...' : 'Generating response...');
                statusBanner.style.display = 'flex';
                statusBanner.style.background = 'rgba(16, 185, 129, 0.15)';
                statusBanner.style.color = '#10b981';
                statusBanner.style.borderColor = 'rgba(16, 185, 129, 0.35)';

                thinkingTimer = setTimeout(() => {
                    statusBanner.style.display = 'none';
                }, 15000);

            } else if (msg.type === 'status' && msg.status === 'idle') {
                // Brief toast, leave all answers intact
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
                liveTranscript.textContent = msg.text;
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
                setTimeout(() => { statusBanner.style.display = 'none'; }, 3500);
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

        function toggleLoopbackAudio() {
            const btn = document.getElementById('btn-loopback');
            const isCurrentlyActive = btn.classList.contains('active');
            const newState = !isCurrentlyActive;

            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'toggle_loopback', enable: newState }));
            } else {
                fetch('/api/loopback/toggle', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Pairing-Token': pairingToken
                    },
                    body: JSON.stringify({ enable: newState })
                });
            }
            updateLoopbackUI(newState);
        }

        function updateLoopbackUI(isActive) {
            const btn = document.getElementById('btn-loopback');
            const label = document.getElementById('loopback-label');
            if (!btn || !label) return;
            if (isActive) {
                btn.classList.add('active');
                label.textContent = 'Interviewer Voice';
                liveTranscript.textContent = 'Listening to interviewer...';
            } else {
                btn.classList.remove('active');
                label.textContent = 'Voice Paused';
                liveTranscript.textContent = 'Interviewer audio capture paused.';
            }
        }

        // Renders new answer at the TOP of the feed in descending order
        function renderAnswer(data) {
            if (isMicListening) {
                stopMicListening();
            }

            // Remove welcome or cleared card if present
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

            const headerBadge = speakerBadge;

            const qText = data.question
                ? `<div style="color:#94a3b8;font-size:0.95rem;font-weight:600;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.06);">Q: "${escapeHtml(data.question)}"</div>`
                : '';

            const card = document.createElement('div');
            card.className = 'answer-card-item';
            card.innerHTML = `
                <div class="answer-card-header">
                    <div style="display:flex;align-items:center;gap:8px;">
                        ${headerBadge}
                        ${providerBadge}
                    </div>
                    <span class="answer-time">${timeStr}</span>
                </div>
                ${qText}
                <div class="answer-card-body">
                    ${html}
                </div>
            `;

            // PREPEND TO TOP (Recent Answer ALWAYS on Top)
            answersFeed.insertBefore(card, answersFeed.firstChild);

            // Scroll container to the top so recent answer is in view immediately
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
            if (liveTranscript) liveTranscript.textContent = 'Recording candidate voice (Push-to-Talk)...';

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
                if (micLabel) micLabel.textContent = '🎙️ Hold to Speak';
                resumeLoopback();
                alert("Microphone access is not available. Please check the desktop app's microphone permissions.");
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
                if (micLabel) micLabel.textContent = '🎙️ Hold to Speak';
                return;
            }

            isPttRecording = false;
            const duration = Date.now() - pttStartTime;

            if (pttMediaRecorder && pttMediaRecorder.state !== 'inactive') {
                try { pttMediaRecorder.stop(); } catch (e) { }
            }

            // Discard accidental quick clicks (< 300ms)
            if (cancel || duration < 300) {
                if (micLabel) micLabel.textContent = '🎙️ Hold to Speak';
                if (liveTranscript) liveTranscript.textContent = 'Listening to interviewer...';
                return;
            }

            if (micLabel) micLabel.textContent = '⚡ Transcribing...';
            if (liveTranscript) liveTranscript.textContent = 'Processing candidate voice with Groq Whisper...';

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
                        if (micLabel) micLabel.textContent = '🎙️ Hold to Speak';
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

        // Sound Meter Equalizer
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

        // Manual Question Submit
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

        // Clear button: Clears screen answers and resets rolling conversation memory
        function clearOverlay() {
            answersFeed.innerHTML = `
                <div id="cleared-placeholder" class="empty-state">
                    <p style="font-size: 0.92rem; color: #94a3b8; margin-bottom: 6px;">All answers cleared.</p>
                    <p style="font-size: 0.80rem; color: #64748b;">Listening to questions from interviewer...</p>
                </div>
            `;
            statusBanner.style.display = 'none';
            liveTranscript.textContent = 'Listening...';

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

        // Backward compatibility helper
        function clearConversationMemory() {
            clearOverlay();
        }

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

        function toggleClickThrough() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_click_through) {
                window.pywebview.api.toggle_click_through().then(isActive => {
                    const btns = document.querySelectorAll('.btn-click-through');
                    btns.forEach(b => b.classList.toggle('active', Boolean(isActive)));
                });
            }
        }

        /* -------------------------------------------------------------------------
           NOTES / CHEAT SHEET OVERLAY LOGIC
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

        async function loadOverlayNotes() {
            try {
                const res = await fetch('/api/notes', { headers: { 'X-Pairing-Token': pairingToken } });
                const data = await res.json();
                if (res.ok && data.notes) {
                    cachedNotes = data.notes;
                    renderOverlayNotes(cachedNotes);
                }
            } catch (err) {
                console.error("Could not load notes:", err);
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
                if (cachedNotes.length === 0) loadOverlayNotes();
                else renderOverlayNotes(cachedNotes);
                const search = document.getElementById('overlay-notes-search');
                if (search) search.focus();
            }
        }

        function renderOverlayNotes(notesToRender) {
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
                copyBtn.className = 'overlay-note-copy btn-icon-copy';
                copyBtn.innerHTML = `
                    <svg class="icon-copy-default" width="15" height="15" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                        aria-hidden="true">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <svg class="icon-copy-check" width="15" height="15" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
                        aria-hidden="true" style="display: none;">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>`;
                copyBtn.title = 'Copy note content';
                copyBtn.setAttribute('aria-label', 'Copy note content');
                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(note.content || note.title)
                        .then(() => {
                            copyBtn.classList.add('copied');
                            copyBtn.title = 'Copied to clipboard';
                            copyBtn.setAttribute('aria-label', 'Copied to clipboard');
                            setTimeout(() => {
                                if (!copyBtn.isConnected) return;
                                copyBtn.classList.remove('copied');
                                copyBtn.title = 'Copy note content';
                                copyBtn.setAttribute('aria-label', 'Copy note content');
                            }, 1400);
                        })
                        .catch(error => {
                            console.error('Could not copy note content:', error);
                            copyBtn.title = 'Could not copy note content';
                            copyBtn.setAttribute('aria-label', 'Could not copy note content');
                        });
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
                renderOverlayNotes(cachedNotes);
                return;
            }
            const filtered = cachedNotes.filter(n =>
                (n.title && n.title.toLowerCase().includes(query)) ||
                (n.content && n.content.toLowerCase().includes(query))
            );
            renderOverlayNotes(filtered);
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

        function startCopilotTimer(forceReset = false) {
            if (forceReset || !copilotInterviewStartTime) {
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

        // Initialize on load
        window.addEventListener('DOMContentLoaded', () => {
            loadInterfacePreferences();
            loadOverlayNotes();
            initWebSocket();
            fetch('/api/copilot/status', { headers: { 'X-Pairing-Token': pairingToken } })
                .then(r => r.json())
                .then(d => {
                    if (d.is_active && d.started_at) {
                        copilotInterviewStartTime = d.started_at;
                        startCopilotTimer(false);
                    } else {
                        resetCopilotTimer();
                    }
                })
                .catch(() => resetCopilotTimer());
            isMicListening = false;
            if (btnMic) {
                btnMic.classList.remove('active');
                btnMic.classList.remove('recording');
            }
            if (micLabel) micLabel.textContent = '🎙️ Hold to Speak';
            if (dot) dot.classList.remove('listening');
            // Pre-warm mic stream in background so first hold has zero latency
            initPttMedia();

            const quickOpacityInput = document.getElementById('quick-opacity-slider');
            if (quickOpacityInput) {
                quickOpacityInput.addEventListener('input', (e) => {
                    updateBackgroundOpacity(e.target.value, true);
                });
            }
        });

        window.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === '[') {
                e.preventDefault();
                const slider = document.getElementById('quick-opacity-slider');
                const cur = slider ? parseInt(slider.value, 10) || 61 : 61;
                const nextVal = Math.max(0, cur - 10);
                updateBackgroundOpacity(nextVal, true);
            }
            if (e.ctrlKey && e.key === ']') {
                e.preventDefault();
                const slider = document.getElementById('quick-opacity-slider');
                const cur = slider ? parseInt(slider.value, 10) || 61 : 61;
                const nextVal = Math.min(100, cur + 10);
                updateBackgroundOpacity(nextVal, true);
            }
        });

        window.addEventListener('pywebviewready', () => {
            const slider = document.getElementById('quick-opacity-slider');
            const opacity = slider ? Number(slider.value) : 61;
            if (window.pywebview && window.pywebview.api && window.pywebview.api.set_opacity) {
                const nativeAlpha = Math.max(40, Math.min(255, Math.round((opacity / 100) * 255)));
                window.pywebview.api.set_opacity(nativeAlpha);
            }
        });

