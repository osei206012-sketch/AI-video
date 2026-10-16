# AI Video Generator — Deployment Package

Mobile-first text-to-video web app: FastAPI serves the HTML UI and calls Replicate's `wan-video/wan-2.2-5b-fast` model. The Replicate token stays on the server and must never be put in `static/index.html` or committed to GitHub.

## Deploy on Render (recommended starter path)

1. Extract this ZIP. Upload the **contents of the `aivideo` folder** to the root of a GitHub repository (so `main.py`, `requirements.txt`, and `render.yaml` are at the repository root).
2. Push/commit the files to GitHub.
3. In Render, choose **New + → Blueprint** and connect the repository. Render reads `render.yaml`. If you instead create a Web Service manually, use:
   - Runtime: **Python 3**
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`
4. In Render → your service → **Environment**, add `REPLICATE_API_TOKEN` with the token from your Replicate account. Do not put the token in HTML, JavaScript, GitHub, screenshots, or this README. Save changes and redeploy.
5. Wait for the deploy to finish, then open `https://YOUR-SERVICE.onrender.com/`. Open `https://YOUR-SERVICE.onrender.com/health`; it should return `{"status":"ok"}`.
6. Check `https://YOUR-SERVICE.onrender.com/api/config`. `demo_mode` should be `false` when the token is configured. Generate a short test video; real generation uses your Replicate account and may incur charges.

## Run locally

Python 3.11 or 3.12 recommended.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
# Set your token in the shell before starting; do not paste it into source code.
# PowerShell: $env:REPLICATE_API_TOKEN="r8_your_real_token"
# macOS/Linux: export REPLICATE_API_TOKEN="r8_your_real_token"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Important production notes

- If the token is missing, the app returns a clear setup error instead of pretending a sample clip is a newly generated video.
- Replicate model inputs are constrained to supported frame counts: 81 frames for the short option and 121 frames for the longer option. Model output and pricing can change; check the model page before launching commercially.
- The job list is held in memory and generated MP4 files are stored in `videos/`. A restart, redeploy, or free-host filesystem cleanup can clear these. This starter is suitable for initial testing, not multi-instance production. For reliable customer history, add a database plus object storage (for example S3-compatible storage) and a persistent job queue.
- Render free web services can sleep when idle; the first request after inactivity may be slow. Video generation is billed by Replicate separately from hosting.
- Do not promise users a particular generation time. Failures may be caused by an invalid token, insufficient Replicate balance, model/API changes, or provider limits.
- This project does not include user accounts, payment/subscription verification, quotas, or abuse prevention. Add these before charging customers.

## API

- `GET /health` — service health check
- `GET /api/config` — returns whether a token is configured and the model name
- `POST /api/generate` — JSON `{ "prompt": "...", "aspect_ratio": "16:9", "duration": 5 }`
- `GET /api/status/{job_id}` — job status and result URL
- `GET /api/history` — recent completed jobs for this running process

## Security

Never commit `.env` or expose `REPLICATE_API_TOKEN` in frontend code. If a token has ever been posted publicly, revoke it and create a new one in Replicate.
