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

## TikTok content factory

`/content-factory` previews the 12 seed videos. `/api/content-factory` describes the feed and custom script format. All videos are 720x1280 MP4, H.264/AAC, 24fps, 22-32 seconds, with English text cards and original synthesized audio. No voice narration is configured.

New scripts can be rendered without storing credentials or user uploads: JSON `{hook, scenes, cta}` is UTF-8 base64url encoded (padding removed) into `/media/factory/script/{token}.mp4`. Limits: hook/CTA 90 characters; 3-5 scenes of up to 130 characters each. Text is drawn by Pillow, never executed. ffmpeg uses an argument list, a 90-second deadline and one render worker. A 40-file disposable cache is regenerated from immutable URLs after service restarts. HTTP HEAD/range requests are supported.

Metricool brand 6066678 publishes to `no.plan..just.cont`. The existing ChatGPT task `6abedc8aae848191ad2247b193ad82bd` maintains a three-day queue with two videos daily. Generation runs in that task; Metricool holds the durable publication queue. Actual publication statuses and analytics must be fetched from Metricool. The renderer does not claim a post is published. Do not run a second scheduler for the same slots. Free Render can sleep; prefetch videos before scheduling and let Metricool copy them. Reconnection, task execution failures, or exhausted platform quotas can stop the loop.
