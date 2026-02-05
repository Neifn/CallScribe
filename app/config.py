"""Application configuration."""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
MODELS_DIR = BASE_DIR / "models"
TEMP_AUDIO_DIR = BASE_DIR / "temp_audio"

# Ensure directories exist
TRANSCRIPTS_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)
TEMP_AUDIO_DIR.mkdir(exist_ok=True)

# Audio settings
SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 2  # BlackHole 2ch needs 2 channels

# Whisper settings
# Language-specific model selection for optimal performance
LANGUAGE_MODELS = {
    "en": os.getenv("CALLSCRIBE_MODEL_EN", "large-v3"),     # Maximum accuracy for English
    "uk": os.getenv("CALLSCRIBE_MODEL_UK", "large-v3")    # Maximum quality for Ukrainian
}

# Fallback model size (deprecated, use LANGUAGE_MODELS instead)
MODEL_SIZE = os.getenv("CALLSCRIBE_MODEL", "large-v3")

# Auto-detect compute type based on available hardware
def get_compute_type() -> str:
    """Determine optimal compute type based on hardware."""
    try:
        import torch
        if torch.cuda.is_available():
            return "float16"
        # MPS (Apple Silicon) doesn't efficiently support float16 for Whisper
        # Use int8 for better compatibility
    except ImportError:
        pass
    return "int8"  # CPU/MPS fallback

COMPUTE_TYPE = os.getenv("CALLSCRIBE_COMPUTE_TYPE", get_compute_type())

# Temp audio file management
DELETE_TEMP_AUDIO = os.getenv("CALLSCRIBE_DELETE_TEMP_AUDIO", "false").lower() == "true"

# Accuracy optimizations - improved VAD parameters
VAD_PARAMETERS = {
    "threshold": 0.4,                    # Lower = more sensitive (default: 0.5)
    "min_speech_duration_ms": 100,       # Minimum duration for valid speech
    "min_silence_duration_ms": 1000,     # Longer silence before splitting (was 500)
    "speech_pad_ms": 200                 # Padding around detected speech
}

# Supported languages
LANGUAGES = {
    "en": "English",
    "uk": "Ukrainian"
}
DEFAULT_LANGUAGE = os.getenv("CALLSCRIBE_DEFAULT_LANGUAGE", "en")

# Logging
LOG_LEVEL = os.getenv("CALLSCRIBE_LOG_LEVEL", "INFO")
