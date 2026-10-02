# MarketStart AI

Production content funnel for the CPA Factory stack.

## Run
```bash
pip install -r marketstart/requirements.txt
uvicorn marketstart.app:app --host 0.0.0.0 --port 8000
```

## Environment
- `SITE_URL`: public canonical URL.
- `CPA_OUT`: CPA Factory tracking endpoint (defaults to `https://cpafactory-web.onrender.com/go/1`).

## Health
`GET /health`

The app exposes 90 evergreen content pages, sitemap, robots.txt, RSS and tracked outbound redirects.

## BYTE entertainment factory

`/content-factory` previews 12 family-friendly riddles and playful logic quizzes led by an original fictional robot. `/api/content-factory` supplies their scripts and captions. English-language MP4 videos are 720x1280 H.264/AAC, 24fps and 17-25 seconds long, with clear opening questions, changing robot expressions, captions and original synthesized audio. No human avatar or voice narration is configured. There is no affiliate CTA in this entertainment content.

New scripts use UTF-8 base64url JSON `{hook, scenes, cta}` (padding removed) at `/media/factory/script/{token}.mp4`. Hook and CTA limits are 90 characters; use 3-5 scenes of up to 130 characters each. Rendering uses bounded subprocess arguments, a 90-second timeout, one worker and a reproducible 40-file cache. HEAD and range requests are supported.

ChatGPT task `6abedc8aae848191ad2247b193ad82bd` creates fresh entertainment scripts and maintains two posts per day across three days for Metricool brand 6066678, TikTok `no.plan..just.cont`. It excludes adult material, cruelty, deception and dangerous challenges. Claims must be checked; virality is never guaranteed. For scheduling, download each video locally and send `mediaFiles:[absolute_path]` plus `info.media:[]`. Omit unrelated networkData. Metricool keeps the durable video and publication queue. Check real publication statuses and analytics there; reconnection, service errors and account quotas can interrupt the loop.
