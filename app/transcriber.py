"""Transcription module using faster-whisper."""
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, List, Callable
import numpy as np
from faster_whisper import WhisperModel
from . import config


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
        self._current_offset = 0.0  # Time offset for continuous transcription
        
        # Threading
        self._transcription_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._on_segment: Optional[Callable[[TranscriptSegment], None]] = None
    
    def load_model(self):
        """Load the Whisper model (can take a few seconds)."""
        if self._model is not None or self._loading:
            return
        
        self._loading = True
        print(f"Loading Whisper model '{self.model_size}'...")
        
        self._model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type=config.COMPUTE_TYPE,
            download_root=str(config.MODELS_DIR)
        )
        
        self._is_ready = True
        self._loading = False
        print(f"Model loaded successfully!")
    
    def set_language(self, language: str):
        """Set the transcription language."""
        self.language = language if language != 'auto' else None
    
    def set_segment_callback(self, callback: Callable[[TranscriptSegment], None]):
        """Set callback for when a new segment is transcribed."""
        self._on_segment = callback
    
    def _transcription_worker(self):
        """Background worker that processes audio chunks."""
        while self._running:
            try:
                audio_chunk = self._transcription_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            
            if audio_chunk is None:
                break
            
            try:
                segments, info = self._model.transcribe(
                    audio_chunk,
                    language=self.language,
                    beam_size=8,  # Increased for better accuracy
                    vad_filter=True,  # Filter out non-speech
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
                print(f"Transcription error: {e}")
            
            self._transcription_queue.task_done()
    
    def start(self):
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
    
    def stop(self) -> List[TranscriptSegment]:
        """Stop transcription and return all segments."""
        self._running = False
        
        # Signal worker to stop
        self._transcription_queue.put(None)
        
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None
        
        return self._segments
    
    def transcribe_chunk(self, audio: np.ndarray):
        """Queue an audio chunk for transcription."""
        if self._running and self._is_ready:
            self._transcription_queue.put(audio)
    
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
