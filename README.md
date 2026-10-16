# MotionMint AI Video Generator — Free-service edition

A mobile-friendly FastAPI web app for text-to-video and image-to-video generation. This edition removes Replicate and uses a public Hugging Face Gradio Space (`OpenKing/wan2-video-generation`) as its AI provider.

## Important limitations

- The public Space is a community service, not a guaranteed production API. It can sleep, become unavailable, change its API, or impose queues and rate limits.
- Free does **not** mean unlimited. Hugging Face ZeroGPU has per-user daily quotas and request limits; the shared public service may refuse requests when busy. See the [official ZeroGPU documentation](https://huggingface.co/docs/hub/main/en/spaces-zerogpu).
- This demo is configured for short clips of about 3 seconds. It cannot reliably generate a 2-minute video for free.
- If the Space changes its API or stops running, update `HF_SPACE_ID` and `HF_SPACE_API_NAME` in Render. The current endpoint is configured as `/generate_video`, but should be checked using the Space's “Use via API” page.
- Generated files and job history are stored in the service's local ephemeral storage and may disappear when Render restarts.

## Deploy to Render

1. Extract this ZIP.
2. Upload the **contents** of `ai-video-generator-pro/` to the root of your GitHub repository (not the parent folder). Commit the changes.
3. In Render, open your existing web service and trigger a manual deploy. Keep the build command as `pip install -r requirements.txt` and the start command as `uvicorn main:app --host 0.0.0.0 --port $PORT`.
4. In Render → Environment, ensure these variables exist:
   - `HF_SPACE_ID` = `OpenKing/wan2-video-generation`
   - `HF_SPACE_API_NAME` = `/generate_video`
   - `MAX_ACTIVE_JOBS` = `1`
5. Delete the old `REPLICATE_API_TOKEN` and `REPLICATE_MODEL` environment variables if you no longer use Replicate. Never share or commit API tokens. `HF_TOKEN` is optional for public Spaces; if you use one, keep it private.
6. Open `https://YOUR-SERVICE.onrender.com/health`; it should return `{"status":"ok"}`. Then open the website and try a short prompt.

## Local run

Python 3.11 or 3.12 recommended.

```bash
python -m venv .venv
# Activate the environment, then:
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.
