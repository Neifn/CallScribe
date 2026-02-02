"""Application configuration."""
import os
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
CHUNK_DURATION = int(os.getenv("CALLSCRIBE_CHUNK_DURATION", "5"))

# Whisper settings
MODEL_SIZE = os.getenv("CALLSCRIBE_MODEL", "large-v3")

# Auto-detect compute type based on available hardware
def get_compute_type() -> str:
    """Determine optimal compute type based on hardware."""
    try:
        import torch
        if torch.cuda.is_available():
            return "float16"
        elif torch.backends.mps.is_available():
            return "float16"  # Apple Silicon
    except ImportError:
        pass
    return "int8"  # CPU fallback

COMPUTE_TYPE = os.getenv("CALLSCRIBE_COMPUTE_TYPE", get_compute_type())

# Supported languages
LANGUAGES = {
    "en": "English",
    "uk": "Ukrainian"
}
DEFAULT_LANGUAGE = os.getenv("CALLSCRIBE_DEFAULT_LANGUAGE", "en")

# Logging
LOG_LEVEL = os.getenv("CALLSCRIBE_LOG_LEVEL", "INFO")
