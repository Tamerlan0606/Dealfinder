# WORKMINE

> **Русский** | English below

WORKMINE — ферма микросервисов с оплатой за каждый вызов API. Она предоставляет множество небольших недорогих цифровых операций и поддерживает монетизацию через протокол x402 с оплатой в USDC в сети Base.

## Возможности

- Paid Ping — `GET /v1/ping` — **$0.001** — минимальная проверка реальной x402-оплаты и доступности
- x402 Readiness Audit — `POST /v1/x402/readiness-audit` — **$0.05** — проверка manifest/discovery/payment readiness с конкретными исправлениями
- x402 Launch Kit — `POST /v1/x402/launch-kit` — **$19** — готовый пакет запуска платного x402 API
- Нормализация текста — `POST /v1/text/normalize` — $0.001
- Извлечение ключевых слов — `POST /v1/text/keywords` — $0.002
- Исправление некорректного JSON — `POST /v1/json/repair` — $0.003
- Скрытие распространённых идентификаторов — `POST /v1/text/redact` — $0.002
- Извлечение текста и ссылок из HTML — `POST /v1/html/to-text` — $0.003
- Извлечение текстового слоя PDF — `POST /v1/pdf/extract-text` — $0.01
- Хеширование, HMAC, Base64 и URL encode/decode — от $0.001

Цены являются текущими тарифами сервиса и могут корректироваться по результатам реального трафика и себестоимости.

## Оплата x402

WORKMINE поддерживает x402 v2. Защищённый endpoint без платежа возвращает HTTP `402 Payment Required`. Это **не считается доходом**. Выполнение платной операции происходит после проверки платежа; подтверждённое зачисление учитывается только после settlement.

- Сеть: Base mainnet (`eip155:8453`)
- Актив: USDC
- API: https://workmine-api.onrender.com
- MCP: https://workmine-mcp.onrender.com/mcp
- OpenAPI: https://workmine-api.onrender.com/openapi.json
- x402 manifest: https://workmine-api.onrender.com/.well-known/x402
- LLM discovery: https://workmine-api.onrender.com/llms.txt

## MCP

Официальное имя сервера в MCP Registry: `io.github.Tamerlan0606/workmine` (v0.5.2). Для нового клиента бесплатный MCP-инструмент `workmine_start_here` показывает самый короткий путь к первой полезной покупке; `find_workmine_tool` маршрутизирует задачи аудита x402 на недорогой Readiness Audit за $0.05.

WORKMINE предоставляет MCP discovery gateway для AI-агентов и MCP-клиентов. Он позволяет получить каталог платных API, подобрать подходящий инструмент по задаче и получить машиночитаемые инструкции x402.

## Ограничения

- Извлечение PDF работает с текстовым слоем и не является OCR.
- Redaction эвристический и не является гарантией соответствия требованиям комплаенса.
- Фактическая экономика определяется реальным трафиком и подтверждёнными settlement.
- Индексация в каталогах MCP/x402 зависит от сторонних реестров.

---

# English

WORKMINE is a pay-per-call microservice farm: many small, low-cost digital operations exposed as APIs and monetized through x402 on Base USDC.

## Included services

- Paid Ping — `GET /v1/ping` — **$0.001** — minimum-cost live x402 payment/availability check
- x402 Readiness Audit — `POST /v1/x402/readiness-audit` — **$0.05** — manifest/discovery/payment readiness audit with concrete fixes
- x402 Launch Kit — `POST /v1/x402/launch-kit` — **$19** — deploy-ready x402 seller package
- Text normalization — `POST /v1/text/normalize` — $0.001
- Keyword extraction — `POST /v1/text/keywords` — $0.002
- JSON repair — `POST /v1/json/repair` — $0.003
- Identifier redaction — `POST /v1/text/redact` — $0.002
- HTML to clean text — `POST /v1/html/to-text` — $0.003
- PDF text-layer extraction — `POST /v1/pdf/extract-text` — $0.01
- Hashing, HMAC, Base64 and URL encode/decode — from $0.001

WORKMINE supports x402 v2 on Base mainnet using USDC. HTTP 402 responses are payment challenges, not revenue; revenue is recognized only from confirmed settlement events.

## Discovery

Official MCP Registry server name: `io.github.Tamerlan0606/workmine` (v0.5.2). New clients can call the free `workmine_start_here` MCP tool for the shortest path to a useful first purchase; x402 audit/readiness/manifest-validation intents route to the $0.05 Readiness Audit.

- API: https://workmine-api.onrender.com
- MCP: https://workmine-mcp.onrender.com/mcp
- OpenAPI: https://workmine-api.onrender.com/openapi.json
- x402 manifest: https://workmine-api.onrender.com/.well-known/x402
- LLM discovery: https://workmine-api.onrender.com/llms.txt

The MCP discovery gateway exposes the WORKMINE catalog, natural-language tool discovery, and machine-readable x402 payment instructions.

## Safety / limitations

- PDF extraction is text-layer extraction; it is not OCR.
- Redaction is heuristic, not a compliance guarantee.
- Real unit economics must be measured from live traffic and confirmed settlements.
- MCP/x402 directory indexing depends on third-party registries.
