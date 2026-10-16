"""MotionMint AI Video Generator using a public Hugging Face Gradio Space.

Free public Spaces have queues and usage limits; availability is not guaranteed.
"""
import base64
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
VIDEO_DIR = BASE_DIR / "videos"
VIDEO_DIR.mkdir(exist_ok=True)
# Public Space; change via Render environment if it becomes unavailable.
HF_SPACE_ID = os.getenv("HF_SPACE_ID", "OpenKing/wan2-video-generation").strip()
HF_SPACE_API_NAME = os.getenv("HF_SPACE_API_NAME", "/generate_video").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()  # optional for public Spaces; keep private
MAX_ACTIVE_JOBS = int(os.getenv("MAX_ACTIVE_JOBS", "1"))
app = FastAPI(title="MotionMint AI Video Generator", version="2.1.0")
# Allow a separately hosted frontend (for example Netlify) to call this backend.
# No credentials/cookies are used; keep provider tokens server-side.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=1500)
    aspect_ratio: str = Field("16:9", pattern=r"^(16:9|9:16)$")
    # The free public demo is optimized for short clips, not two-minute videos.
    duration: int = Field(3, ge=3, le=6)
    resolution: str = Field("720p", pattern=r"^(480p|720p)$")
    image_data: Optional[str] = Field(default=None, max_length=400_000)

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Please describe the video you want to create.")
        return value.strip()

    @field_validator("image_data")
    @classmethod
    def validate_image(cls, value):
        if value is not None and not value.startswith("data:image/"):
            raise ValueError("Please upload a valid image file.")
        return value

def get_client():
    try:
        from gradio_client import Client
    except ImportError as exc:
        raise RuntimeError("The free AI connector is not installed. Redeploy the service so requirements.txt is installed.") from exc
    kwargs = {"verbose": False}
    if HF_TOKEN:
        kwargs["hf_token"] = HF_TOKEN
    return Client(HF_SPACE_ID, **kwargs)

def run_generation(job_id: str, req: GenerateRequest):
    with LOCK:
        JOBS[job_id]["status"] = "processing"
    temp_image = None
    try:
        # Gradio's public Space API accepts a file path for its optional image input.
        image_path = None
        if req.image_data:
            try:
                header, encoded = req.image_data.split(",", 1)
                raw = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise RuntimeError("The uploaded image could not be decoded. Please choose the image again.") from exc
            suffix = ".png" if "png" in header.lower() else ".jpg"
            fd, temp_image = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            image_path = temp_image

        from gradio_client import handle_file
        client = get_client()
        width, height = (832, 480) if req.aspect_ratio == "16:9" else (480, 832)
        # Conservative settings improve the chance of completing within free GPU limits.
        # This public Space documents 73 frames (~3 seconds) as its default; longer
        # durations may time out on shared/free GPU capacity.
        num_frames = min(145, max(73, req.duration * 24 + 1))
        image_input = handle_file(image_path) if image_path else None
        api_name = HF_SPACE_API_NAME
        # Discover the current endpoint if the Space's API name has changed.
        try:
            api_info = client.view_api(return_format="dict")
            named = api_info.get("named_endpoints", {}) if isinstance(api_info, dict) else {}
            if api_name not in named and named:
                candidates = [name for name in named if "generate" in name.lower() or "video" in name.lower()]
                api_name = candidates[0] if candidates else next(iter(named))
        except Exception:
            # Older gradio_client versions may not support return_format; use configured name.
            pass
        result = client.predict(
            req.prompt, image_input, width, height, num_frames, 20, 5.0, -1,
            api_name=api_name,
        )
        output = result[0] if isinstance(result, (list, tuple)) else result
        if isinstance(output, dict):
            output = output.get("video") or output.get("path") or output.get("url")
        if not isinstance(output, str) or not output:
            raise RuntimeError("The free AI service did not return a video file. It may be busy; please try again later.")
        # Gradio clients generally return a local downloaded file path. Handle URL output too.
        if output.startswith("http://") or output.startswith("https://"):
            import requests
            response = requests.get(output, timeout=90)
            response.raise_for_status()
            video_bytes = response.content
            filename = f"{job_id}.mp4"
            (VIDEO_DIR / filename).write_bytes(video_bytes)
        else:
            source = Path(output)
            if not source.exists():
                raise RuntimeError("The AI service returned a video path that is no longer available. Please try again.")
            filename = f"{job_id}.mp4"
            shutil.copyfile(source, VIDEO_DIR / filename)
        with LOCK:
            JOBS[job_id].update(
                status="done", video_url=f"/videos/{filename}",
                completed_at=time.time(), duration=req.duration,
            )
    except Exception as exc:
        raw = str(exc)
        lowered = raw.lower()
        if "queue" in lowered or "rate limit" in lowered or "too many" in lowered or "429" in lowered:
            message = "The free AI service is busy or its usage limit has been reached. Wait and try again later."
        elif "not found" in lowered or "does not exist" in lowered or "api_name" in lowered:
            message = "The free AI service endpoint may have changed. Please contact the site administrator to update the Hugging Face Space settings."
        else:
            message = "Free video generation failed. The public AI service may be sleeping, busy, or temporarily unavailable. Please try again later."
        with LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(status="failed", error=message, completed_at=time.time())
    finally:
        if temp_image:
            try:
                os.unlink(temp_image)
            except OSError:
                pass

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/config")
def config():
    return {"configured": bool(HF_SPACE_ID), "provider": "Hugging Face public Space", "space": HF_SPACE_ID, "max_active_jobs": MAX_ACTIVE_JOBS, "max_duration_seconds": 6, "free_service": True, "version": "2.1.0"}

@app.post("/api/generate")
def generate(req: GenerateRequest):
    if not HF_SPACE_ID:
        raise HTTPException(status_code=503, detail="The free AI service is not configured.")
    with LOCK:
        active = sum(1 for job in JOBS.values() if job.get("status") in ("queued", "processing"))
        if active >= MAX_ACTIVE_JOBS:
            raise HTTPException(status_code=429, detail="The free AI service is busy. Please wait for the current video to finish, then try again.")
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"job_id": job_id, "status": "queued", "prompt": req.prompt, "video_url": None, "error": None, "created_at": time.time(), "aspect_ratio": req.aspect_ratio, "duration": req.duration}
    threading.Thread(target=run_generation, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}

@app.get("/api/status/{job_id}")
def status(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="This generation job was not found. It may have expired after a server restart.")
        return dict(job)

@app.get("/api/history")
def history():
    with LOCK:
        jobs = [dict(job) for job in JOBS.values() if job.get("status") == "done" and job.get("video_url")]
    jobs.sort(key=lambda job: job.get("created_at", 0), reverse=True)
    return {"jobs": jobs[:30]}

@app.get("/videos/{filename}")
def serve_video(filename: str):
    # Restrict path traversal and serve only generated MP4s.
    if Path(filename).name != filename or not filename.endswith(".mp4"):
        raise HTTPException(status_code=404, detail="Video not found.")
    path = VIDEO_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found. It may have expired after a server restart.")
    return FileResponse(path, media_type="video/mp4", filename=filename)

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred. Please refresh and try again."})
