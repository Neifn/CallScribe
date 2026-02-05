"""Transcription module using faster-whisper."""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Callable, Dict
import numpy as np
from faster_whisper import WhisperModel
from . import config

logger = logging.getLogger(__name__)


class TranscriptSegment:
    """A single transcribed segment with timing info."""
    
    def __init__(self, text: str, start: float, end: float, language: str):
        self.text = text
        self.start = start
        self.end = end
        self.language = language
        self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        return {
            'text': self.text,
            'start': self.start,
            'end': self.end,
            'language': self.language,
            'timestamp': self.timestamp.isoformat()
        }


class Transcriber:
    """Speech-to-text transcription using faster-whisper."""
    
    def __init__(self):
        self._models: Dict[str, WhisperModel] = {}  # Cache models by size
        self._current_language: str = config.DEFAULT_LANGUAGE
        self._segments: List[TranscriptSegment] = []
        self._on_segment: Optional[Callable[[TranscriptSegment], None]] = None
        self._on_progress: Optional[Callable[[int, int], None]] = None
    
    def get_model_for_language(self, language: str) -> WhisperModel:
        """Get or load the appropriate model for the specified language."""
        # Determine model size based on language
        model_size = config.LANGUAGE_MODELS.get(language, config.MODEL_SIZE)
        
        # Check if model is already loaded
        if model_size in self._models:
            logger.info(f"Using cached model '{model_size}' for language '{language}'")
            return self._models[model_size]
        
        # Load new model
        logger.info(f"Loading Whisper model '{model_size}' for language '{language}' with compute type '{config.COMPUTE_TYPE}'...")
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=config.COMPUTE_TYPE,
            download_root=str(config.MODELS_DIR)
        )
        
        # Cache it
        self._models[model_size] = model
        logger.info(f"Model '{model_size}' loaded successfully!")
        return model
    
    def set_language(self, language: str) -> None:
        """Set the transcription language."""
        if language not in config.LANGUAGES and language != 'auto':
            logger.warning(f"Unknown language '{language}', defaulting to English")
            language = 'en'
        self._current_language = language
    
    def set_segment_callback(self, callback: Callable[[TranscriptSegment], None]) -> None:
        """Set callback for when a new segment is transcribed."""
        self._on_segment = callback
    
    def set_progress_callback(self, callback: Callable[[int, int], None]) -> None:
        """Set callback for progress updates during transcription.
        
        Args:
            callback: Function that receives (current_segment, total_segments)
        """
        self._on_progress = callback
    
    def transcribe_file(self, audio_file: Path, language: Optional[str] = None) -> List[TranscriptSegment]:
        """Transcribe a complete audio file.
        
        Args:
            audio_file: Path to the audio file (WAV format)
            language: Language code or None for auto-detection
            
        Returns:
            List of transcribed segments
        """
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")
        
        # Use provided language or current language
        lang = language or self._current_language
        lang_code = lang if lang != 'auto' else None
        
        # Get appropriate model for this language
        model = self.get_model_for_language(lang)
        
        # Clear previous segments
        self._segments = []
        
        logger.info(f"Starting transcription of {audio_file} (language: {lang})")
        
        # Transcribe the file with accuracy optimizations
        segments_iterator, info = model.transcribe(
            str(audio_file),
            language=lang_code,
            beam_size=8,
            best_of=8,  # Test multiple candidates for accuracy
            temperature=0.0,  # Deterministic output
            vad_filter=True,
            vad_parameters=config.VAD_PARAMETERS,
            word_timestamps=False,
            condition_on_previous_text=True,  # Use context
            compression_ratio_threshold=2.2,  # Detect gibberish
            no_speech_threshold=0.5  # Filter silence hallucinations
        )
        
        # Convert iterator to list to get total count
        segments_list = list(segments_iterator)
        total_segments = len(segments_list)
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        logger.info(f"Processing {total_segments} segments...")
        
        # Process segments
        for idx, segment in enumerate(segments_list, 1):
            ts = TranscriptSegment(
                text=segment.text.strip(),
                start=segment.start,
                end=segment.end,
                language=info.language
            )
            
            if ts.text:  # Only add non-empty segments
                self._segments.append(ts)
                
                # Notify callback
                if self._on_segment:
                    self._on_segment(ts)
            
            # Notify progress
            if self._on_progress:
                self._on_progress(idx, total_segments)
        
        logger.info(f"Transcription complete: {len(self._segments)} segments")
        return self._segments
    
    def get_full_transcript(self) -> str:
        """Get the full transcript as a single string."""
        return ' '.join(seg.text for seg in self._segments if seg.text)
    
    def export_srt(self) -> str:
        """Export transcript in SRT subtitle format."""
        lines = []
        for i, seg in enumerate(self._segments, 1):
            start = self._format_time(seg.start)
            end = self._format_time(seg.end)
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(seg.text)
            lines.append("")
        return '\n'.join(lines)
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as SRT timestamp."""
        td = timedelta(seconds=seconds)
        hours, remainder = divmod(td.seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        millis = td.microseconds // 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    @property
    def segments(self) -> List[TranscriptSegment]:
        """Get all transcribed segments."""
        return self._segments
    
    @property
    def is_ready(self) -> bool:
        """Check if at least one model is loaded."""
        return len(self._models) > 0
    
    def preload_model(self, language: str) -> None:
        """Preload model for a specific language."""
        self.get_model_for_language(language)
