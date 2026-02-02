"""FastAPI application for the transcription service."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from . import config
from .audio_capture import AudioCapture
from .transcriber import Transcriber, TranscriptSegment


# Global state
audio_capture: Optional[AudioCapture] = None
transcriber: Optional[Transcriber] = None
active_websockets: list[WebSocket] = []
session_start_time: Optional[datetime] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Preload model on startup
    global transcriber
    transcriber = Transcriber()
    # Load in background to not block startup
    asyncio.get_event_loop().run_in_executor(None, transcriber.load_model)
    yield
    # Cleanup on shutdown
    if audio_capture and audio_capture.is_recording:
        audio_capture.stop()
    if transcriber and transcriber.is_running:
        transcriber.stop()


app = FastAPI(title="Call Transcription", lifespan=lifespan)


# Mount static files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    """Serve the main UI."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Call Transcription API", "docs": "/docs"}


@app.get("/api/devices")
async def list_devices():
    """List available audio input devices."""
    devices = AudioCapture.list_devices()
    blackhole_id = AudioCapture.find_blackhole_device()
    return {
        "devices": devices,
        "recommended": blackhole_id
    }


@app.get("/api/languages")
async def list_languages():
    """List supported languages."""
    return {"languages": config.LANGUAGES, "default": config.DEFAULT_LANGUAGE}


@app.get("/api/status")
async def get_status():
    """Get current transcription status."""
    return {
        "is_recording": audio_capture.is_recording if audio_capture else False,
        "is_model_ready": transcriber.is_ready if transcriber else False,
        "session_start": session_start_time.isoformat() if session_start_time else None,
        "segments_count": len(transcriber._segments) if transcriber else 0
    }


@app.post("/api/start")
async def start_transcription(device_id: Optional[int] = None, language: str = "auto"):
    """Start a new transcription session."""
    global audio_capture, transcriber, session_start_time
    
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
    def on_audio_chunk(audio):
        transcriber.transcribe_chunk(audio)
    
    def on_segment(segment: TranscriptSegment):
        # Broadcast to all connected websockets
        asyncio.run(broadcast_segment(segment))
    
    audio_capture.set_chunk_callback(on_audio_chunk)
    transcriber.set_segment_callback(on_segment)
    
    # Start components
    transcriber.start()
    audio_capture.start()
    session_start_time = datetime.now()
    
    return {"status": "started", "device_id": device_id, "language": language}


async def broadcast_segment(segment: TranscriptSegment):
    """Send a segment to all connected WebSocket clients."""
    message = json.dumps(segment.to_dict())
    for ws in active_websockets[:]:
        try:
            await ws.send_text(message)
        except:
            active_websockets.remove(ws)


@app.post("/api/stop")
async def stop_transcription(save: bool = True):
    """Stop transcription and optionally save the transcript."""
    global audio_capture, session_start_time
    
    if not audio_capture or not audio_capture.is_recording:
        raise HTTPException(status_code=400, detail="Not recording")
    
    # Stop recording
    remaining_audio = audio_capture.stop()
    
    # Process any remaining audio
    if remaining_audio is not None and len(remaining_audio) > 0:
        transcriber.transcribe_chunk(remaining_audio)
    
    # Get final transcript
    segments = transcriber.stop()
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
    
    session_start_time = None
    return result


@app.get("/api/transcript")
async def get_current_transcript():
    """Get the current transcript (during or after recording)."""
    if not transcriber:
        return {"transcript": "", "segments": []}
    
    return {
        "transcript": transcriber.get_full_transcript(),
        "segments": [s.to_dict() for s in transcriber._segments]
    }


@app.websocket("/ws/transcription")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time transcription updates."""
    await websocket.accept()
    active_websockets.append(websocket)
    
    try:
        # Send current segments first
        if transcriber and transcriber._segments:
            for segment in transcriber._segments:
                await websocket.send_text(json.dumps(segment.to_dict()))
        
        # Keep connection alive
        while True:
            try:
                # Wait for any message (ping/pong or close)
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send ping to keep alive
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.get("/api/transcripts")
async def list_saved_transcripts():
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
