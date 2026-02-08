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
        
        # Transcribe the file with strong anti-hallucination settings
        # These settings are aggressive to prevent loops on long files
        segments_iterator, info = model.transcribe(
            str(audio_file),
            language=lang_code,
            beam_size=5,  # Reduced from 8 for faster, more focused decoding
            temperature=0.0,  # Deterministic output
            vad_filter=True,
            vad_parameters=config.VAD_PARAMETERS,
            word_timestamps=False,
            condition_on_previous_text=False,  # CHANGED: Disable to prevent context-based hallucinations
            compression_ratio_threshold=2.4,  # Increased from 2.2 - more aggressive gibberish detection
            log_prob_threshold=-1.0,  # NEW: Filter out low-confidence segments (default is -inf)
            no_speech_threshold=0.6,  # Increased from 0.5 - more aggressive silence filtering
            repetition_penalty=1.2  # NEW: Penalize repetitive patterns
        )
        
        # Process segments as they come from the iterator for real-time progress
        # We don't know the total count ahead of time, so we'll estimate based on audio duration
        # Typical segment length is 2-10 seconds, we'll estimate ~5 seconds per segment
        estimated_total = int(info.duration / 5) if hasattr(info, 'duration') else 100
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        logger.info(f"Processing segments (estimated {estimated_total})...")
        
        
        # Process segments incrementally for real-time progress
        segment_count = 0
        last_texts = []  # Track last N segments for hallucination detection
        hallucination_threshold = 3  # REDUCED from 5: If same text appears 3 times in a row, stop
        
        for segment in segments_iterator:
            segment_count += 1
            
            ts = TranscriptSegment(
                text=segment.text.strip(),
                start=segment.start,
                end=segment.end,
                language=info.language
            )
            
            # Hallucination detection: check if we're repeating the same phrase
            if ts.text:
                # Keep last N texts
                last_texts.append(ts.text.lower())
                if len(last_texts) > hallucination_threshold:
                    last_texts.pop(0)
                
                # Check if all recent segments are identical
                if len(last_texts) >= hallucination_threshold:
                    if len(set(last_texts)) == 1:  # All segments are the same
                        logger.warning(f"Hallucination detected: phrase '{ts.text}' repeated {hallucination_threshold} times. Stopping transcription.")
                        break
                
                self._segments.append(ts)
                
                # Notify callback
                if self._on_segment:
                    self._on_segment(ts)
            
            # Notify progress with updated estimate
            if self._on_progress:
                # Update estimate as we go
                current_time = segment.end if hasattr(segment, 'end') else 0
                if hasattr(info, 'duration') and info.duration > 0:
                    # Calculate progress based on time position
                    progress_pct = min(int((current_time / info.duration) * 100), 99)
                # Use percentage for total, current for actual count
                self._on_progress(segment_count, max(estimated_total, segment_count))
        
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
