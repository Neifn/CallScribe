# CallScribe

**Local, private speech-to-text for browser calls** — Transcribe Teams, Google Meet, and Slack calls in real-time without sending data to the cloud.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-macOS-lightgrey)

## Features

- **100% Local** — All processing happens on your machine, no data leaves your computer
- **Multilingual** — Supports English and Ukrainian (powered by OpenAI Whisper)
- **Real-time** — Live transcription as you speak
- **Browser Audio Capture** — Captures audio from any Chrome tab (Teams, Meet, Slack, etc.)
- **Export** — Download transcripts as text or SRT subtitles
- **Modern UI** — Clean, dark-themed web interface

## Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/callscribe.git
cd callscribe

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in your browser.

## Audio Setup (macOS)

To capture browser audio, you need to install [BlackHole](https://github.com/ExistentialAudio/BlackHole):

```bash
brew install blackhole-2ch
```

Then create a Multi-Output Device in **Audio MIDI Setup** that includes both BlackHole and your speakers. Set this as your system output.

See [setup_audio.md](setup_audio.md) for detailed instructions.

## Model Options

| Model | Accuracy | Speed | Size |
|-------|----------|-------|------|
| `tiny` | Basic | Fastest | 75MB |
| `small` | Good | Fast | 500MB |
| `medium` | Great | Moderate | 1.5GB |
| `large-v3` | Best | Slow | 3GB |

Configure in `app/config.py`.

## Tech Stack

- **Backend**: Python, FastAPI, faster-whisper
- **Frontend**: Vanilla JS, CSS (dark theme)
- **Audio**: sounddevice, BlackHole
- **Model**: OpenAI Whisper (via faster-whisper)

## License

MIT License — Use freely, modify as needed.

---

*Built for privacy-conscious professionals who need reliable transcription without cloud dependencies.*
