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
    
    # Initialize transcriber and preload default model
    transcriber = Transcriber()
    logger.info("Preloading default model...")
    asyncio.get_event_loop().run_in_executor(
        None, 
        transcriber.preload_model, 
        config.DEFAULT_LANGUAGE
    )
    
    logger.info("Application started")
    yield
    
    # Cleanup
    if audio_capture and audio_capture.is_recording:
        audio_capture.stop()
    
    # Clean up temp files
    for temp_file in config.TEMP_AUDIO_DIR.glob("*.wav"):
        try:
            temp_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete temp file {temp_file}: {e}")
    
    logger.info("Application shutdown")


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
        "segments_count": len(transcriber.segments) if transcriber else 0
    }


@app.post("/api/start")
async def start_transcription(device_id: Optional[int] = None, language: str = "en") -> Dict[str, Any]:
    """Start a new recording session."""
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
    
    # Initialize audio capture
    audio_capture = AudioCapture(device_id=device_id)
    
    # Set language for transcriber
    if transcriber is None:
        transcriber = Transcriber()
    transcriber.set_language(language)
    
    # Preload model for this language in background
    asyncio.get_event_loop().run_in_executor(
        None,
        transcriber.preload_model,
        language
    )
    
    # Start recording
    audio_capture.start()
    session_start_time = datetime.now()
    
    logger.info(f"Started recording: device={device_id}, language={language}")
    return {"status": "recording", "device_id": device_id, "language": language}


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
    """Stop recording and transcribe the audio file."""
    global audio_capture, session_start_time, transcriber
    
    if not audio_capture or not audio_capture.is_recording:
        raise HTTPException(status_code=400, detail="Not recording")
    
    # Notify clients that processing is starting
    await broadcast_message({"type": "status", "status": "processing"})
    
    # Stop recording and get audio file
    audio_file = audio_capture.stop()
    
    if not audio_file or not audio_file.exists():
        raise HTTPException(status_code=500, detail="Failed to save recording")
    
    try:
        # Set up callbacks for real-time updates
        def on_segment(segment: TranscriptSegment):
            if main_loop and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(broadcast_segment(segment), main_loop)
        
        def on_progress(current: int, total: int):
            if main_loop and main_loop.is_running():
                progress_pct = int((current / total) * 100) if total > 0 else 0
                asyncio.run_coroutine_threadsafe(
                    broadcast_message({
                        "type": "progress", 
                        "current": current, 
                        "total": total,
                        "percent": progress_pct
                    }), 
                    main_loop
                )
        
        transcriber.set_segment_callback(on_segment)
        transcriber.set_progress_callback(on_progress)
        
        # Transcribe in executor to avoid blocking
        segments = await asyncio.get_event_loop().run_in_executor(
            None,
            transcriber.transcribe_file,
            audio_file,
            None  # Use language set in start()
        )
        
        full_text = transcriber.get_full_transcript()
        srt_content = transcriber.export_srt()
        
        result = {
            "status": "completed",
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
        
        # Notify completion
        await broadcast_message({"type": "status", "status": "completed"})
        
        session_start_time = None
        return result
        
    finally:
        # Clean up temporary audio file
        try:
            if audio_file and audio_file.exists():
                audio_file.unlink()
                logger.info(f"Deleted temporary audio file: {audio_file}")
        except Exception as e:
            logger.warning(f"Failed to delete temp file {audio_file}: {e}")


@app.post("/api/cancel")
async def cancel_recording() -> Dict[str, Any]:
    """Cancel recording without transcribing."""
    global audio_capture, session_start_time
    
    if not audio_capture or not audio_capture.is_recording:
        raise HTTPException(status_code=400, detail="Not recording")
    
    # Stop recording
    audio_file = audio_capture.stop()
    
    # Delete the temp file
    if audio_file and audio_file.exists():
        try:
            audio_file.unlink()
            logger.info(f"Deleted temporary audio file: {audio_file}")
        except Exception as e:
            logger.warning(f"Failed to delete temp file: {e}")
    
    session_start_time = None
    await broadcast_message({"type": "status", "status": "cancelled"})
    
    return {"status": "cancelled"}


@app.get("/api/transcript")
async def get_current_transcript() -> Dict[str, Any]:
    """Get the current transcript."""
    if not transcriber:
        return {"transcript": "", "segments": []}
    
    return {
        "transcript": transcriber.get_full_transcript(),
        "segments": [s.to_dict() for s in transcriber.segments]
    }


@app.websocket("/ws/transcription")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket for real-time transcription updates."""
    await websocket.accept()
    active_websockets.append(websocket)
    logger.debug("WebSocket client connected")
    
    try:
        # Send current segments if any
        if transcriber and transcriber.segments:
            for segment in transcriber.segments:
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
