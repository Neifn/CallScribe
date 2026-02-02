"""Application configuration."""
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
MODELS_DIR = BASE_DIR / "models"

# Ensure directories exist
TRANSCRIPTS_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Audio settings
SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 2  # BlackHole 2ch needs 2 channels
CHUNK_DURATION = 5  # 5 seconds for more context = better accuracy

# Whisper settings
MODEL_SIZE = "large-v3"  # Best accuracy for all languages including Ukrainian
COMPUTE_TYPE = "int8"  # Faster inference on CPU

# Supported languages
LANGUAGES = {
    "en": "English",
    "uk": "Ukrainian"
}
DEFAULT_LANGUAGE = "en"
