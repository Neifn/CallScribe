/**
 * Call Transcription - Frontend Application
 */

class TranscriptionApp {
    constructor() {
        // DOM Elements
        this.deviceSelect = document.getElementById('device-select');
        this.languageSelect = document.getElementById('language-select');
        this.startBtn = document.getElementById('start-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.statusDot = document.getElementById('status-dot');
        this.statusText = document.getElementById('status-text');
        this.durationEl = document.getElementById('duration');
        this.transcriptEl = document.getElementById('transcript');
        this.copyBtn = document.getElementById('copy-btn');
        this.downloadBtn = document.getElementById('download-btn');
        this.clearBtn = document.getElementById('clear-btn');
        this.loadingOverlay = document.getElementById('loading-overlay');

        // State
        this.isRecording = false;
        this.websocket = null;
        this.segments = [];
        this.startTime = null;
        this.durationInterval = null;

        // Initialize
        this.init();
    }

    async init() {
        // Load devices
        await this.loadDevices();

        // Check model status
        await this.checkStatus();

        // Bind events
        this.bindEvents();
    }

    bindEvents() {
        this.startBtn.addEventListener('click', () => this.startTranscription());
        this.stopBtn.addEventListener('click', () => this.stopTranscription());
        this.copyBtn.addEventListener('click', () => this.copyTranscript());
        this.downloadBtn.addEventListener('click', () => this.downloadTranscript());
        this.clearBtn.addEventListener('click', () => this.clearTranscript());
    }

    async loadDevices() {
        try {
            const response = await fetch('/api/devices');
            const data = await response.json();

            this.deviceSelect.innerHTML = '';

            if (data.devices.length === 0) {
                this.deviceSelect.innerHTML = '<option value="">No audio devices found</option>';
                return;
            }

            data.devices.forEach(device => {
                const option = document.createElement('option');
                option.value = device.id;
                option.textContent = device.name;
                if (device.is_blackhole) {
                    option.textContent += ' ⭐ (Recommended)';
                }
                if (device.id === data.recommended) {
                    option.selected = true;
                }
                this.deviceSelect.appendChild(option);
            });

            if (!data.recommended) {
                this.setStatus('warning', 'BlackHole not found. Please install it for browser audio capture.');
            }
        } catch (error) {
            console.error('Failed to load devices:', error);
            this.setStatus('error', 'Failed to connect to server');
        }
    }

    async checkStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();

            if (!data.is_model_ready) {
                this.showLoading(true);
                // Poll until ready
                const checkInterval = setInterval(async () => {
                    const res = await fetch('/api/status');
                    const status = await res.json();
                    if (status.is_model_ready) {
                        clearInterval(checkInterval);
                        this.showLoading(false);
                        this.setStatus('ready', 'Ready to transcribe');
                    }
                }, 2000);
            } else {
                this.setStatus('ready', 'Ready to transcribe');
            }
        } catch (error) {
            console.error('Failed to check status:', error);
        }
    }

    async startTranscription() {
        const deviceId = this.deviceSelect.value;
        const language = this.languageSelect.value;

        if (!deviceId) {
            this.setStatus('error', 'Please select an audio device');
            return;
        }

        try {
            this.startBtn.disabled = true;

            const response = await fetch(`/api/start?device_id=${deviceId}&language=${language}`, {
                method: 'POST'
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to start');
            }

            this.isRecording = true;
            this.startTime = Date.now();
            this.segments = [];
            this.clearTranscript();

            // Update UI
            this.stopBtn.disabled = false;
            this.deviceSelect.disabled = true;
            this.languageSelect.disabled = true;
            this.setStatus('recording', 'Recording...');

            // Start duration counter
            this.durationInterval = setInterval(() => this.updateDuration(), 1000);

            // Connect WebSocket for real-time updates
            this.connectWebSocket();

        } catch (error) {
            console.error('Failed to start:', error);
            this.setStatus('error', error.message);
            this.startBtn.disabled = false;
        }
    }

    async stopTranscription() {
        try {
            this.stopBtn.disabled = true;

            const response = await fetch('/api/stop?save=true', {
                method: 'POST'
            });

            const data = await response.json();

            this.isRecording = false;

            // Update UI
            this.startBtn.disabled = false;
            this.deviceSelect.disabled = false;
            this.languageSelect.disabled = false;

            // Stop duration counter
            if (this.durationInterval) {
                clearInterval(this.durationInterval);
                this.durationInterval = null;
            }

            // Disconnect WebSocket
            if (this.websocket) {
                this.websocket.close();
                this.websocket = null;
            }

            this.setStatus('ready', `Saved! ${data.segments_count} segments transcribed`);

        } catch (error) {
            console.error('Failed to stop:', error);
            this.setStatus('error', 'Failed to stop recording');
            this.stopBtn.disabled = false;
        }
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/transcription`;

        this.websocket = new WebSocket(wsUrl);

        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);

            // Ignore ping messages
            if (data.type === 'ping') return;

            // Add segment
            this.addSegment(data);
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        this.websocket.onclose = () => {
            console.log('WebSocket closed');
        };
    }

    addSegment(segment) {
        this.segments.push(segment);

        // Remove placeholder if present
        const placeholder = this.transcriptEl.querySelector('.placeholder');
        if (placeholder) {
            placeholder.remove();
        }

        // Create segment element
        const segmentEl = document.createElement('div');
        segmentEl.className = 'segment';

        const timeStr = this.formatTime(segment.start);
        const langBadge = segment.language ? `<span class="segment-language">${segment.language}</span>` : '';

        segmentEl.innerHTML = `
            <div class="segment-time">${timeStr}${langBadge}</div>
            <div class="segment-text">${this.escapeHtml(segment.text)}</div>
        `;

        this.transcriptEl.appendChild(segmentEl);

        // Scroll to bottom
        this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
    }

    setStatus(type, message) {
        this.statusDot.className = 'status-dot';
        if (type === 'recording') {
            this.statusDot.classList.add('recording');
        } else if (type === 'ready') {
            this.statusDot.classList.add('ready');
        }
        this.statusText.textContent = message;
    }

    showLoading(show) {
        this.loadingOverlay.classList.toggle('hidden', !show);
    }

    updateDuration() {
        if (!this.startTime) return;
        const elapsed = Math.floor((Date.now() - this.startTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        this.durationEl.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    copyTranscript() {
        const text = this.segments.map(s => s.text).join(' ');
        if (!text) {
            this.setStatus('warning', 'Nothing to copy');
            return;
        }

        navigator.clipboard.writeText(text).then(() => {
            this.setStatus('ready', 'Copied to clipboard!');
            setTimeout(() => this.setStatus('ready', 'Ready to transcribe'), 2000);
        });
    }

    downloadTranscript() {
        const text = this.segments.map(s => s.text).join('\n\n');
        if (!text) {
            this.setStatus('warning', 'Nothing to download');
            return;
        }

        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `transcript_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }

    clearTranscript() {
        this.segments = [];
        this.transcriptEl.innerHTML = '<p class="placeholder">Transcription will appear here...</p>';
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new TranscriptionApp();
});
