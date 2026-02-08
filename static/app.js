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

        // Manual transcription elements
        this.fileUploadInput = document.getElementById('file-upload-input');
        this.fileUploadBtn = document.getElementById('file-upload-btn');
        this.uploadFilename = document.getElementById('upload-filename');
        this.savedFileSelect = document.getElementById('saved-file-select');
        this.refreshFilesBtn = document.getElementById('refresh-files-btn');
        this.manualLanguageSelect = document.getElementById('manual-language-select');
        this.transcribeFileBtn = document.getElementById('transcribe-file-btn');
        this.cancelTranscriptionBtn = document.getElementById('cancel-transcription-btn');
        this.transcriptionProgress = document.getElementById('transcription-progress');
        this.progressText = document.getElementById('progress-text');
        this.progressPercent = document.getElementById('progress-percent');
        this.progressBarFill = document.getElementById('progress-bar-fill');

        // State
        this.isRecording = false;
        this.isProcessing = false;
        this.websocket = null;
        this.segments = [];
        this.startTime = null;
        this.durationInterval = null;
        this.selectedFile = null;

        // Initialize
        this.init();
    }

    async init() {
        // Load devices
        await this.loadDevices();

        // Check model status
        await this.checkStatus();

        // Load saved files
        await this.loadSavedFiles();

        // Bind events
        this.bindEvents();
    }

    bindEvents() {
        this.startBtn.addEventListener('click', () => this.startTranscription());
        this.stopBtn.addEventListener('click', () => this.stopTranscription());
        this.copyBtn.addEventListener('click', () => this.copyTranscript());
        this.downloadBtn.addEventListener('click', () => this.downloadTranscript());
        this.clearBtn.addEventListener('click', () => this.clearTranscript());

        // Manual transcription events
        this.fileUploadBtn.addEventListener('click', () => this.fileUploadInput.click());
        this.fileUploadInput.addEventListener('change', (e) => this.handleFileSelect(e));
        this.savedFileSelect.addEventListener('change', () => this.handleSavedFileSelect());
        this.refreshFilesBtn.addEventListener('click', () => this.loadSavedFiles());
        this.transcribeFileBtn.addEventListener('click', () => this.transcribeSelectedFile());
        this.cancelTranscriptionBtn.addEventListener('click', () => this.cancelTranscription());
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
            if (this.durationInterval) clearInterval(this.durationInterval);
            this.durationInterval = setInterval(() => this.updateDuration(), 1000);

            // Connect WebSocket for updates
            this.connectWebSocket();

        } catch (error) {
            console.error('Failed to start:', error);
            this.setStatus('error', error.message);
            this.startBtn.disabled = false;
        }
    }

    async stopTranscription() {
        if (!this.isRecording) return;

        // Stop timer immediately
        if (this.durationInterval) {
            clearInterval(this.durationInterval);
            this.durationInterval = null;
        }

        try {
            this.stopBtn.disabled = true;
            this.isProcessing = true;
            this.setStatus('processing', 'Processing recording...');

            const response = await fetch('/api/stop?save=true', {
                method: 'POST'
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to stop');
            }

            const data = await response.json();

            this.isRecording = false;
            this.isProcessing = false;

            // Update UI
            this.startBtn.disabled = false;
            this.deviceSelect.disabled = false;
            this.languageSelect.disabled = false;

            this.setStatus('ready', `Saved! ${data.segments_count} segments transcribed`);

        } catch (error) {
            console.error('Failed to stop:', error);
            this.setStatus('error', 'Failed to stop recording');
            this.stopBtn.disabled = false;
            this.isProcessing = false;
        }
    }

    connectWebSocket() {
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/transcription`;

        this.websocket = new WebSocket(wsUrl);

        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);

            // Ignore ping messages
            if (data.type === 'ping') return;

            // Handle status updates
            if (data.type === 'status') {
                if (data.status === 'processing') {
                    this.setStatus('processing', 'Processing recording...');
                } else if (data.status === 'completed') {
                    this.setStatus('ready', 'Transcription completed!');
                }
                return;
            }

            // Handle progress updates
            if (data.type === 'progress') {
                this.setStatus('processing', `Processing... ${data.percent}% (${data.current}/${data.total} segments)`);
                this.updateProgress(data.percent, `Processing segment ${data.current} of ${data.total}`);
                return;
            }

            // Add segment
            if (data.text) {
                this.addSegment(data);
            }
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
        } else if (type === 'processing') {
            this.statusDot.classList.add('processing');
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

    // Manual transcription methods
    async loadSavedFiles() {
        try {
            const response = await fetch('/api/temp-files');
            const data = await response.json();

            // Clear and populate dropdown
            this.savedFileSelect.innerHTML = '<option value="">Select a recording...</option>';

            if (data.files && data.files.length > 0) {
                data.files.forEach(file => {
                    const option = document.createElement('option');
                    option.value = file.path;
                    const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                    const date = new Date(file.modified).toLocaleString();
                    option.textContent = `${file.filename} (${sizeMB} MB) - ${date}`;
                    this.savedFileSelect.appendChild(option);
                });
            }
        } catch (error) {
            console.error('Failed to load saved files:', error);
        }
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (file) {
            this.selectedFile = file;
            this.uploadFilename.textContent = file.name;
            this.savedFileSelect.value = '';  // Clear saved file selection
            this.transcribeFileBtn.disabled = false;
        }
    }

    handleSavedFileSelect() {
        const selectedPath = this.savedFileSelect.value;
        if (selectedPath) {
            this.selectedFile = null;  // Clear uploaded file
            this.fileUploadInput.value = '';
            this.uploadFilename.textContent = '';
            this.transcribeFileBtn.disabled = false;
        } else {
            this.transcribeFileBtn.disabled = !this.selectedFile;
        }
    }

    async transcribeSelectedFile() {
        if (this.isProcessing) {
            return;
        }

        const language = this.manualLanguageSelect.value;

        try {
            this.isProcessing = true;
            this.transcribeFileBtn.disabled = true;
            this.transcribeFileBtn.style.display = 'none';
            this.cancelTranscriptionBtn.style.display = 'inline-block';
            this.transcriptionProgress.style.display = 'block';
            this.updateProgress(0, 'Starting transcription...');
            this.clearTranscript();
            this.setStatus('processing', 'Processing file...');

            // Connect WebSocket for real-time updates
            this.connectWebSocket();

            let response;

            // Upload file or use saved file path
            if (this.selectedFile) {
                // Upload new file
                const formData = new FormData();
                formData.append('file', this.selectedFile);
                formData.append('language', language);
                formData.append('save', 'true');

                response = await fetch('/api/transcribe-file', {
                    method: 'POST',
                    body: formData
                });
            } else {
                // Use saved file - send as query parameters
                const filePath = this.savedFileSelect.value;
                console.log('Selected file path:', filePath);

                if (!filePath) {
                    throw new Error('No file selected');
                }

                const params = new URLSearchParams({
                    file_path: filePath,
                    language: language,
                    save: 'true'
                });

                console.log('Request URL:', `/api/transcribe-file?${params}`);

                response = await fetch(`/api/transcribe-file?${params}`, {
                    method: 'POST'
                });
            }

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Transcription failed');
            }

            const result = await response.json();

            // Status will be updated via WebSocket, but set final message
            this.setStatus('ready', `Saved! ${result.segments_count} segments transcribed`);

            // Reset selections
            this.selectedFile = null;
            this.fileUploadInput.value = '';
            this.uploadFilename.textContent = '';
            this.savedFileSelect.value = '';

        } catch (error) {
            console.error('File transcription error:', error);
            this.setStatus('error', error.message || 'Transcription failed');
        } finally {
            this.isProcessing = false;
            this.transcribeFileBtn.disabled = false;
            this.transcribeFileBtn.style.display = 'inline-block';
            this.cancelTranscriptionBtn.style.display = 'none';
            this.transcriptionProgress.style.display = 'none';
        }
    }

    updateProgress(percent, text) {
        this.progressPercent.textContent = `${percent}%`;
        this.progressText.textContent = text;
        this.progressBarFill.style.width = `${percent}%`;
    }

    async cancelTranscription() {
        if (!this.isProcessing) {
            return;
        }

        try {
            const response = await fetch('/api/cancel', { method: 'POST' });
            if (response.ok) {
                this.setStatus('ready', 'Transcription cancelled');
                this.isProcessing = false;
                this.transcribeFileBtn.style.display = 'inline-block';
                this.cancelTranscriptionBtn.style.display = 'none';
                this.transcriptionProgress.style.display = 'none';
            }
        } catch (error) {
            console.error('Cancel error:', error);
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new TranscriptionApp();
});
