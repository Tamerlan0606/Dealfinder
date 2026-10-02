# WORKMINE

> **Русский** | English below

WORKMINE — ферма микросервисов с оплатой за каждый вызов API. Она предоставляет множество небольших недорогих цифровых операций и поддерживает монетизацию через протокол x402 с оплатой в USDC в сети Base.

## Возможности

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

- Text normalization — `POST /v1/text/normalize` — $0.001
- Keyword extraction — `POST /v1/text/keywords` — $0.002
- JSON repair — `POST /v1/json/repair` — $0.003
- Identifier redaction — `POST /v1/text/redact` — $0.002
- HTML to clean text — `POST /v1/html/to-text` — $0.003
- PDF text-layer extraction — `POST /v1/pdf/extract-text` — $0.01
- Hashing, HMAC, Base64 and URL encode/decode — from $0.001

WORKMINE supports x402 v2 on Base mainnet using USDC. HTTP 402 responses are payment challenges, not revenue; revenue is recognized only from confirmed settlement events.

## Discovery

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
