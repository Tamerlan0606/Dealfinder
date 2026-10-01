# DealFinder Mobile

Облачный MVP под iPhone: мобильная веб-панель + Telegram-уведомления + API для покупателей/поставщиков/сопоставления.

## Deploy

Проект рассчитан на Render. Подключается как Web Service из GitHub. Build: `pip install -r requirements.txt`; Start: `uvicorn run:app --host 0.0.0.0 --port $PORT`.

После deploy панель открывается по URL Render и нормально работает в Safari на iPhone.

## Environment

`DRY_RUN=true` — безопасный режим. Для реальных писем и Telegram необходимо добавить соответствующие переменные в Render. Массовую рассылку без законного основания не включать.

## Что уже есть

- мобильная панель;
- горячие сделки;
- расчёт маржи;
- база покупателей и поставщиков;
- Telegram уведомления;
- email outreach;
- API;
- Render Blueprint.

Источники заявок подключаются отдельными адаптерами; CAPTCHA, авторизация и ограничения сайтов не обходятся.

## Render Free

На Free-инстансе локальная файловая система эфемерна и persistent disk недоступен. Поэтому SQLite используется как кэш: при старте DealFinder автоматически повторяет поиск и восстанавливает данные. Для постоянного хранения нужен платный persistent disk или внешняя БД.


## MarketStart AI

The repository also contains the production MarketStart AI content funnel in `marketstart/`.

- Production: https://marketstart-production.onrender.com
- 90 evergreen content pages (30 topics × 3 formats)
- SEO sitemap, robots.txt and RSS
- Outbound traffic is routed through CPA Factory for click attribution
- Render production service deploys automatically from `main`
- CI: `.github/workflows/marketstart-ci.yml`


## WORKMINE

WORKMINE is the repository's x402 pay-per-call utility API and remote MCP discovery gateway for autonomous agents.

- Paid API: https://workmine-api.onrender.com
- Remote MCP: https://workmine-mcp.onrender.com/mcp
- Protocol: x402 v2
- Settlement: USDC on Base mainnet (eip155:8453)
- Machine catalog: https://workmine-api.onrender.com/catalog
- Agent manifest: https://workmine-api.onrender.com/.well-known/x402
- LLM discovery: https://workmine-api.onrender.com/llms.txt
- OpenAPI: https://workmine-api.onrender.com/openapi.json
- MCP Registry descriptor: workmine/server.json

The WORKMINE implementation is isolated under `workmine/` and does not change the DealFinder runtime.
