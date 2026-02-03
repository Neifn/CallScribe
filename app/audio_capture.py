"""Audio capture module for recording to WAV files."""
import logging
import tempfile
import threading
from pathlib import Path
from typing import Optional, List
import numpy as np
import sounddevice as sd
import soundfile as sf
from . import config

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures audio from a specified input device and saves to WAV file."""
    
    def __init__(self, device_id: Optional[int] = None):
        self.device_id = device_id
        self.sample_rate = config.SAMPLE_RATE
        self.channels = config.CHANNELS
        
        self._stream: Optional[sd.InputStream] = None
        self._is_recording = False
        self._wav_file: Optional[sf.SoundFile] = None
        self._temp_file_path: Optional[Path] = None
        self._device_channels: int = 1
        self._lock = threading.Lock()
    
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
    
    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """Callback for audio stream - writes to WAV file."""
        if status:
            logger.warning(f"Audio status: {status}")
        
        if not self._wav_file:
            return
        
        # Convert stereo to mono if needed (Whisper expects mono)
        if indata.ndim > 1 and indata.shape[1] > 1:
            audio_data = np.mean(indata, axis=1, keepdims=True)
        else:
            audio_data = indata
        
        # Write to WAV file
        with self._lock:
            try:
                self._wav_file.write(audio_data)
            except Exception as e:
                logger.error(f"Error writing audio: {e}")
    
    def start(self) -> None:
        """Start recording audio to a temporary WAV file."""
        if self._is_recording:
            return
        
        # Create temporary WAV file
        temp_file = tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.wav',
            dir=str(config.TEMP_AUDIO_DIR),
            delete=False
        )
        self._temp_file_path = Path(temp_file.name)
        temp_file.close()
        
        # Query the device to get its actual channel count
        if self.device_id is not None:
            device_info = sd.query_devices(self.device_id)
            device_channels = device_info['max_input_channels']
        else:
            device_channels = self.channels
        
        self._device_channels = device_channels
        
        # Open WAV file for writing (mono output for Whisper)
        self._wav_file = sf.SoundFile(
            str(self._temp_file_path),
            mode='w',
            samplerate=self.sample_rate,
            channels=1,  # Write as mono
            format='WAV',
            subtype='PCM_16'
        )
        
        # Start audio stream
        self._stream = sd.InputStream(
            device=self.device_id,
            channels=device_channels,
            samplerate=self.sample_rate,
            callback=self._audio_callback,
            dtype=np.float32
        )
        self._stream.start()
        self._is_recording = True
        
        logger.info(f"Started recording to {self._temp_file_path} from device {self.device_id} ({device_channels} channels)")
    
    def stop(self) -> Optional[Path]:
        """Stop recording and return the path to the WAV file."""
        if not self._is_recording:
            return None
        
        self._is_recording = False
        
        # Stop and close stream
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        # Close WAV file
        with self._lock:
            if self._wav_file:
                self._wav_file.close()
                self._wav_file = None
        
        temp_path = self._temp_file_path
        self._temp_file_path = None
        
        if temp_path and temp_path.exists():
            file_size = temp_path.stat().st_size
            logger.info(f"Stopped recording, saved {file_size} bytes to {temp_path}")
            return temp_path
        
        logger.warning("Stopped recording but no file was created")
        return None
    
    @property
    def is_recording(self) -> bool:
        return self._is_recording
