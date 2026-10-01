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
