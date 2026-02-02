"""Audio capture module for recording from BlackHole or other audio devices."""
import threading
import queue
import numpy as np
import sounddevice as sd
from typing import Optional, List, Callable
from . import config


class AudioCapture:
    """Captures audio from a specified input device."""
    
    def __init__(self, device_id: Optional[int] = None):
        self.device_id = device_id
        self.sample_rate = config.SAMPLE_RATE
        self.channels = config.CHANNELS
        self.chunk_duration = config.CHUNK_DURATION
        
        self._stream: Optional[sd.InputStream] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._is_recording = False
        self._buffer: List[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._on_chunk_ready: Optional[Callable[[np.ndarray], None]] = None
    
    @staticmethod
    def list_devices() -> List[dict]:
        """List all available audio input devices."""
        devices = sd.query_devices()
        input_devices = []
        
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                input_devices.append({
                    'id': i,
                    'name': device['name'],
                    'channels': device['max_input_channels'],
                    'sample_rate': device['default_samplerate'],
                    'is_blackhole': 'blackhole' in device['name'].lower()
                })
        
        return input_devices
    
    @staticmethod
    def find_blackhole_device() -> Optional[int]:
        """Find BlackHole device ID if available."""
        devices = AudioCapture.list_devices()
        for device in devices:
            if device['is_blackhole']:
                return device['id']
        return None
    
    def set_chunk_callback(self, callback: Callable[[np.ndarray], None]):
        """Set callback to be called when a chunk is ready for transcription."""
        self._on_chunk_ready = callback
    
    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """Callback for audio stream - called for each audio block."""
        if status:
            print(f"Audio status: {status}")
        
        # Convert stereo to mono if needed (Whisper expects mono)
        if indata.ndim > 1 and indata.shape[1] > 1:
            audio_data = np.mean(indata, axis=1)
        else:
            audio_data = indata.flatten()
        
        # Add to buffer
        with self._buffer_lock:
            self._buffer.append(audio_data.copy())
            
            # Calculate total duration in buffer
            total_samples = sum(chunk.shape[0] for chunk in self._buffer)
            duration = total_samples / self.sample_rate
            
            # If we have enough audio, trigger transcription
            if duration >= self.chunk_duration:
                # Concatenate buffer
                audio_chunk = np.concatenate(self._buffer, axis=0)
                self._buffer = []
                
                # Debug: check audio levels
                max_level = np.max(np.abs(audio_chunk))
                print(f"[Audio] Chunk ready: {len(audio_chunk)} samples, max level: {max_level:.4f}")
                
                # Notify callback
                if self._on_chunk_ready:
                    self._on_chunk_ready(audio_chunk)
    
    def start(self):
        """Start recording audio."""
        if self._is_recording:
            return
        
        self._is_recording = True
        self._buffer = []
        
        # Query the device to get its actual channel count
        if self.device_id is not None:
            device_info = sd.query_devices(self.device_id)
            device_channels = device_info['max_input_channels']
        else:
            device_channels = self.channels
        
        self._device_channels = device_channels
        
        self._stream = sd.InputStream(
            device=self.device_id,
            channels=device_channels,  # Use device's native channels
            samplerate=self.sample_rate,
            callback=self._audio_callback,
            dtype=np.float32
        )
        self._stream.start()
        print(f"Started recording from device {self.device_id} ({device_channels} channels)")
    
    def stop(self) -> Optional[np.ndarray]:
        """Stop recording and return any remaining audio."""
        if not self._is_recording:
            return None
        
        self._is_recording = False
        
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        # Return any remaining audio in buffer
        with self._buffer_lock:
            if self._buffer:
                remaining = np.concatenate(self._buffer, axis=0).flatten()
                self._buffer = []
                return remaining
        
        return None
    
    @property
    def is_recording(self) -> bool:
        return self._is_recording
