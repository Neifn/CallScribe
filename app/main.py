"""FastAPI application for the transcription service."""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from . import config
from .audio_capture import AudioCapture
from .transcriber import Transcriber, TranscriptSegment

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global state
audio_capture: Optional[AudioCapture] = None
transcriber: Optional[Transcriber] = None
active_websockets: list[WebSocket] = []
session_start_time: Optional[datetime] = None
main_loop: Optional[asyncio.AbstractEventLoop] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    global transcriber, main_loop
    main_loop = asyncio.get_running_loop()
    transcriber = Transcriber()
    asyncio.get_event_loop().run_in_executor(None, transcriber.load_model)
    logger.info("Application started")
    yield
    if audio_capture and audio_capture.is_recording:
        audio_capture.stop()
    if transcriber and transcriber.is_running:
        transcriber.stop()
    logger.info("Application shutdown")

# ... (lines omitted)

    # Set up the pipeline: audio -> transcriber -> websocket
    def on_audio_chunk(audio):
        transcriber.transcribe_chunk(audio)
    
    def on_segment(segment: TranscriptSegment):
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_segment(segment), main_loop)
        
    def on_queue_update(count: int):
        # Broadcast queue size
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_message({"type": "queue", "count": count}), main_loop)
    
    audio_capture.set_chunk_callback(on_audio_chunk)


app = FastAPI(title="CallScribe", lifespan=lifespan)

# Mount static files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Serve the main UI."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "CallScribe API", "docs": "/docs"})


@app.get("/api/devices")
async def list_devices() -> Dict[str, Any]:
    """List available audio input devices."""
    devices = AudioCapture.list_devices()
    blackhole_id = AudioCapture.find_blackhole_device()
    return {
        "devices": devices,
        "recommended": blackhole_id
    }


@app.get("/api/languages")
async def list_languages() -> Dict[str, Any]:
    """List supported languages."""
    return {"languages": config.LANGUAGES, "default": config.DEFAULT_LANGUAGE}


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    """Get current transcription status."""
    return {
        "is_recording": audio_capture.is_recording if audio_capture else False,
        "is_model_ready": transcriber.is_ready if transcriber else False,
        "session_start": session_start_time.isoformat() if session_start_time else None,
        "segments_count": len(transcriber._segments) if transcriber else 0
    }


@app.post("/api/start")
async def start_transcription(device_id: Optional[int] = None, language: str = "en") -> Dict[str, Any]:
    """Start a new transcription session."""
    global audio_capture, transcriber, session_start_time
    
    # Validate language
    if language not in config.LANGUAGES:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported language '{language}'. Supported: {list(config.LANGUAGES.keys())}"
        )
    
    if audio_capture and audio_capture.is_recording:
        raise HTTPException(status_code=400, detail="Already recording")
    
    # Use BlackHole if no device specified
    if device_id is None:
        device_id = AudioCapture.find_blackhole_device()
        if device_id is None:
            raise HTTPException(
                status_code=400, 
                detail="BlackHole not found. Please install it or specify a device_id."
            )
    
    # Initialize components
    audio_capture = AudioCapture(device_id=device_id)
    
    if transcriber is None:
        transcriber = Transcriber(language=language)
    else:
        transcriber.set_language(language)
    
    # Ensure model is loaded
    if not transcriber.is_ready:
        transcriber.load_model()
    
    # Set up the pipeline: audio -> transcriber -> websocket
    # Set up the pipeline: audio -> transcriber -> websocket
    def on_audio_chunk(audio):
        transcriber.transcribe_chunk(audio)
    
    def on_segment(segment: TranscriptSegment):
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_segment(segment), main_loop)
        
    def on_queue_update(count: int):
        # Broadcast queue size
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_message({"type": "queue", "count": count}), main_loop)
    
    audio_capture.set_chunk_callback(on_audio_chunk)
    transcriber.set_segment_callback(on_segment)
    transcriber.set_queue_callback(on_queue_update)
    
    # Start components
    transcriber.start()
    audio_capture.start()
    session_start_time = datetime.now()
    
    logger.info(f"Started transcription: device={device_id}, language={language}")
    return {"status": "started", "device_id": device_id, "language": language}


async def broadcast_segment(segment: TranscriptSegment) -> None:
    """Send a segment to all connected WebSocket clients."""
    await broadcast_message(segment.to_dict())


async def broadcast_message(data: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    message = json.dumps(data)
    disconnected = []
    for ws in active_websockets:
        try:
            await ws.send_text(message)
        except (WebSocketDisconnect, RuntimeError) as e:
            logger.debug(f"WebSocket disconnected: {e}")
            disconnected.append(ws)
    
    # Clean up disconnected sockets
    for ws in disconnected:
        if ws in active_websockets:
            active_websockets.remove(ws)


@app.post("/api/stop")
async def stop_transcription(save: bool = True) -> Dict[str, Any]:
    """Stop transcription and optionally save the transcript."""
    global audio_capture, session_start_time
    
    if not audio_capture or not audio_capture.is_recording:
        raise HTTPException(status_code=400, detail="Not recording")
    
    # Signal busy state to UI via WS
    await broadcast_message({"type": "status", "status": "stopping"})
    
    # Stop recording immediately
    remaining_audio = audio_capture.stop()
    
    # Process any remaining audio
    if remaining_audio is not None and len(remaining_audio) > 0:
        transcriber.transcribe_chunk(remaining_audio)
    
    # Get final transcript - run in executor to avoid blocking WS updates
    # This allows on_queue_update to keep firing while we wait for the queue to drain
    segments = await asyncio.get_event_loop().run_in_executor(None, transcriber.stop)
    
    full_text = transcriber.get_full_transcript()
    srt_content = transcriber.export_srt()
    
    result = {
        "status": "stopped",
        "duration": (datetime.now() - session_start_time).total_seconds() if session_start_time else 0,
        "segments_count": len(segments),
        "transcript": full_text
    }
    
    # Save to file if requested
    if save and segments:
        timestamp = session_start_time.strftime("%Y%m%d_%H%M%S") if session_start_time else datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save as text
        txt_path = config.TRANSCRIPTS_DIR / f"transcript_{timestamp}.txt"
        txt_path.write_text(full_text)
        
        # Save as SRT
        srt_path = config.TRANSCRIPTS_DIR / f"transcript_{timestamp}.srt"
        srt_path.write_text(srt_content)
        
        # Save as JSON
        json_path = config.TRANSCRIPTS_DIR / f"transcript_{timestamp}.json"
        json_path.write_text(json.dumps([s.to_dict() for s in segments], indent=2))
        
        result["saved_files"] = {
            "txt": str(txt_path),
            "srt": str(srt_path),
            "json": str(json_path)
        }
        
        logger.info(f"Saved transcript to {txt_path}")
    
    session_start_time = None
    return result


@app.get("/api/transcript")
async def get_current_transcript() -> Dict[str, Any]:
    """Get the current transcript (during or after recording)."""
    if not transcriber:
        return {"transcript": "", "segments": []}
    
    return {
        "transcript": transcriber.get_full_transcript(),
        "segments": [s.to_dict() for s in transcriber._segments]
    }


@app.websocket("/ws/transcription")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket for real-time transcription updates."""
    await websocket.accept()
    active_websockets.append(websocket)
    logger.debug("WebSocket client connected")
    
    try:
        # Send current segments first
        if transcriber and transcriber._segments:
            for segment in transcriber._segments:
                await websocket.send_text(json.dumps(segment.to_dict()))
        
        # Keep connection alive
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.get("/api/transcripts")
async def list_saved_transcripts() -> Dict[str, Any]:
    """List all saved transcripts."""
    transcripts = []
    for txt_file in config.TRANSCRIPTS_DIR.glob("transcript_*.txt"):
        transcripts.append({
            "name": txt_file.stem,
            "txt": str(txt_file),
            "srt": str(txt_file.with_suffix(".srt")),
            "json": str(txt_file.with_suffix(".json")),
            "created": datetime.fromtimestamp(txt_file.stat().st_mtime).isoformat()
        })
    return {"transcripts": sorted(transcripts, key=lambda x: x["created"], reverse=True)}
