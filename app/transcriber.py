"""Transcription module using faster-whisper."""
import logging
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, List, Callable
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
    
    def __init__(self, model_size: str = config.MODEL_SIZE, language: str = config.DEFAULT_LANGUAGE):
        self.model_size = model_size
        self.language = language if language != 'auto' else None
        self._model: Optional[WhisperModel] = None
        self._is_ready = False
        self._loading = False
        
        # Transcription state
        self._segments: List[TranscriptSegment] = []
        self._current_offset = 0.0
        
        # Threading
        self._transcription_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._on_segment: Optional[Callable[[TranscriptSegment], None]] = None
        self._on_queue_update: Optional[Callable[[int], None]] = None
    
    def load_model(self) -> None:
        """Load the Whisper model (can take a few seconds)."""
        if self._model is not None or self._loading:
            return
        
        self._loading = True
        logger.info(f"Loading Whisper model '{self.model_size}' with compute type '{config.COMPUTE_TYPE}'...")
        
        self._model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type=config.COMPUTE_TYPE,
            download_root=str(config.MODELS_DIR)
        )
        
        self._is_ready = True
        self._loading = False
        logger.info("Model loaded successfully!")
    
    def set_language(self, language: str) -> None:
        """Set the transcription language."""
        if language not in config.LANGUAGES and language != 'auto':
            logger.warning(f"Unknown language '{language}', defaulting to English")
            language = 'en'
        self.language = language if language != 'auto' else None
    
    def set_segment_callback(self, callback: Callable[[TranscriptSegment], None]) -> None:
        """Set callback for when a new segment is transcribed."""
        self._on_segment = callback
    
    def set_queue_callback(self, callback: Callable[[int], None]) -> None:
        """Set callback for queue size updates."""
        self._on_queue_update = callback
    
    def _transcription_worker(self) -> None:
        """Background worker that processes audio chunks."""
        while True:
            try:
                # Get chunk
                audio_chunk = self._transcription_queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running:
                    # If stopped and queue empty, break
                    break
                continue
            
            # Sentinel to stop
            if audio_chunk is None:
                break
            
            try:
                segments, info = self._model.transcribe(
                    audio_chunk,
                    language=self.language,
                    beam_size=8,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500)
                )
                
                for segment in segments:
                    ts = TranscriptSegment(
                        text=segment.text.strip(),
                        start=self._current_offset + segment.start,
                        end=self._current_offset + segment.end,
                        language=info.language
                    )
                    self._segments.append(ts)
                    
                    if self._on_segment and ts.text:
                        self._on_segment(ts)
                
                # Update offset for next chunk
                self._current_offset += len(audio_chunk) / config.SAMPLE_RATE
                
            except Exception as e:
                logger.error(f"Transcription error: {e}", exc_info=True)
            
            self._transcription_queue.task_done()
            
            # Notify queue size update
            if self._on_queue_update:
                self._on_queue_update(self._transcription_queue.qsize())
    
    def start(self) -> None:
        """Start the transcription worker."""
        if self._running:
            return
        
        if not self._is_ready:
            self.load_model()
        
        self._running = True
        self._segments = []
        self._current_offset = 0.0
        
        self._worker_thread = threading.Thread(target=self._transcription_worker, daemon=True)
        self._worker_thread.start()
        logger.info("Transcription worker started")
    
    def stop(self) -> List[TranscriptSegment]:
        """Stop transcription and return all segments."""
        self._running = False
        
        # Signal worker to stop (will process queue first)
        self._transcription_queue.put(None)
        
        # Notify queue size (add pending stop sentinel)
        if self._on_queue_update:
            self._on_queue_update(self._transcription_queue.qsize())
        
        if self._worker_thread:
            # Wait for worker to finish (processing remainder of queue)
            # Remove timeout to ensure everything is processed
            self._worker_thread.join()
            self._worker_thread = None
        
        logger.info(f"Transcription stopped, {len(self._segments)} segments collected")
        return self._segments
    
    def transcribe_chunk(self, audio: np.ndarray) -> None:
        """Queue an audio chunk for transcription."""
        if self._is_ready:
            self._transcription_queue.put(audio)
            # Notify queue size
            if self._on_queue_update:
                self._on_queue_update(self._transcription_queue.qsize())
    
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
    def is_ready(self) -> bool:
        return self._is_ready
    
    @property
    def is_running(self) -> bool:
        return self._running
