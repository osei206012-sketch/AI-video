"""
AI Video Generator — FastAPI backend
====================================
Text-to-video generation via Replicate API, with a graceful demo fallback
when no API key is configured. Mobile-first web UI served from /static.

Run:  uvicorn main:app --host 0.0.0.0 --port 8000
Env:  REPLICATE_API_TOKEN   (optional — without it the app runs in demo mode)
"""

import os
import uuid
import time
import shutil
import threading
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).parent
VIDEO_DIR = BASE_DIR / "videos"
VIDEO_DIR.mkdir(exist_ok=True)

REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()
DEMO_MODE = not bool(REPLICATE_TOKEN)

# Replicate text-to-video model (public, cheap, fast). Swap the version slug
# for any other text-to-video model you prefer (minimax/video-01, kling, ...).
REPLICATE_MODEL = "wan-video/wan-2.2-5b-fast"

app = FastAPI(title="AI Video Generator")

# In-memory job store: {job_id: {status, prompt, video_url, error, created_at}}
JOBS: dict[str, dict] = {}


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=1000)
    aspect_ratio: str = Field("16:9", pattern="^(16:9|9:16|1:1)$")
    duration: int = Field(5, ge=3, le=10)


# ---------------------------------------------------------------------------
# Generation workers
# ---------------------------------------------------------------------------

def _save_video(job_id: str, source_url: str) -> str:
    """Download a remote video into ./videos and return its local web path."""
    local_name = f"{job_id}.mp4"
    local_path = VIDEO_DIR / local_name
    with requests.get(source_url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            shutil.copyfileobj(r.raw, f)
    return f"/videos/{local_name}"


def _run_replicate(job_id: str, req: GenerateRequest):
    """Real generation path — Replicate API."""
    try:
        JOBS[job_id]["status"] = "processing"
        headers = {
            "Authorization": f"Bearer {REPLICATE_TOKEN}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        # This model accepts 81–121 frames. Map the UI's duration choices to
        # the supported frame range instead of sending invalid values (e.g. 72).
        frames = 81 if req.duration <= 5 else 121
        payload = {
            "input": {
                "prompt": req.prompt,
                "aspect_ratio": req.aspect_ratio,
                "num_frames": frames,
                "frames_per_second": 16,
                "resolution": "720p",
                "go_fast": True,
            }
        }
        resp = requests.post(
            f"https://api.replicate.com/v1/models/{REPLICATE_MODEL}/predictions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        prediction = resp.json()

        # Poll until done (max ~8 min)
        poll_url = prediction["urls"]["get"]
        deadline = time.time() + 480
        while time.time() < deadline:
            time.sleep(4)
            poll = requests.get(poll_url, headers=headers, timeout=60)
            poll.raise_for_status()
            data = poll.json()
            status = data.get("status")
            if status == "succeeded":
                output = data.get("output")
                if isinstance(output, list):
                    remote_url = output[0] if output else None
                elif isinstance(output, dict):
                    remote_url = output.get("url") or output.get("video")
                else:
                    remote_url = output
                if not isinstance(remote_url, str) or not remote_url.startswith(("https://", "http://")):
                    raise RuntimeError("The video model returned no usable video URL")
                JOBS[job_id]["video_url"] = _save_video(job_id, remote_url)
                JOBS[job_id]["status"] = "done"
                return
            if status in ("failed", "canceled"):
                raise RuntimeError(data.get("error") or f"Prediction {status}")

        raise TimeoutError("Generation timed out")
    except Exception as e:  # noqa: BLE001
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)


def _run_demo(job_id: str, req: GenerateRequest):
    """Demo path — simulates latency then serves a bundled sample clip."""
    try:
        time.sleep(6)  # pretend to generate
        sample = VIDEO_DIR / "sample.mp4"
        if not sample.exists():
            raise RuntimeError("Demo sample video missing")
        dest = VIDEO_DIR / f"{job_id}.mp4"
        shutil.copy(sample, dest)
        JOBS[job_id]["video_url"] = f"/videos/{job_id}.mp4"
        JOBS[job_id]["status"] = "done"
    except Exception as e:  # noqa: BLE001
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/generate")
def generate(req: GenerateRequest):
    if DEMO_MODE:
        raise HTTPException(
            status_code=503,
            detail="Real video generation is not configured yet. Add REPLICATE_API_TOKEN in your hosting provider's environment variables, then redeploy.",
        )
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "status": "queued",
        "prompt": req.prompt,
        "video_url": None,
        "error": None,
        "created_at": time.time(),
    }
    threading.Thread(target=_run_replicate, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "mode": "replicate"}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/history")
def history():
    """Recent completed jobs, newest first (for the gallery tab)."""
    done = [
        {
            "job_id": jid,
            "prompt": j["prompt"],
            "video_url": j["video_url"],
            "created_at": j["created_at"],
        }
        for jid, j in JOBS.items()
        if j["status"] == "done" and j["video_url"]
    ]
    done.sort(key=lambda x: x["created_at"], reverse=True)
    return {"jobs": done[:30], "demo_mode": DEMO_MODE}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {"demo_mode": DEMO_MODE, "model": None if DEMO_MODE else REPLICATE_MODEL}


# Static files & SPA entry
app.mount("/videos", StaticFiles(directory=VIDEO_DIR), name="videos")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.exception_handler(Exception)
async def unhandled(_, exc):
    # Avoid returning internal exception details to public users.
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred. Please try again."})
