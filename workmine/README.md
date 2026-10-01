# WORKMINE

WORKMINE is a pay-per-call microservice farm: many small, cheap digital operations exposed as APIs and optionally monetized by x402. The first release is deliberately CPU-first so it can launch on a normal cloud instance before renting GPUs.

## Included microservices

- `POST /v1/text/normalize` — `$0.001`
- `POST /v1/text/keywords` — `$0.002`
- `POST /v1/json/repair` — `$0.003`
- `POST /v1/text/redact` — `$0.002`
- `POST /v1/html/to-text` — `$0.003`
- `POST /v1/pdf/extract-text` — `$0.01`

The prices are initial hypotheses, not guaranteed profitable market prices. `/stats` records calls, modeled compute cost and gross margin so weak endpoints can be repriced or removed.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `/`, `/docs`, `/catalog`, `/stats`, and `/health`.

## Turn on real x402 payments

Start in test mode first. Then set:

```bash
WORKMINE_PAYMENT_MODE=x402
PAY_TO=0xYourPublicReceivingAddress
X402_NETWORK=eip155:8453
X402_FACILITATOR_URL=https://x402.org/facilitator
PUBLIC_BASE_URL=https://your-service.example
```

`PAY_TO` is a public receive address only. Never commit or configure a wallet private key on the seller server.

When x402 mode is enabled, protected routes return HTTP `402 Payment Required` until the client supplies a valid payment. The reference x402 server verifies and settles through the configured facilitator; route code runs only after payment succeeds.

For testnet use `X402_NETWORK=eip155:84532` (Base Sepolia) and a compatible facilitator.

## Render

Build command:

```bash
pip install -r workmine/requirements.txt
```

Start command:

```bash
uvicorn workmine.main:app --host 0.0.0.0 --port $PORT
```

This repository layout keeps WORKMINE isolated from the existing Dealfinder/CPA Factory application.

## Safety / limitations

- PDF extraction is text-layer extraction; it is not OCR.
- Redaction is heuristic, not a compliance guarantee.
- Prices and estimated compute costs are configurable assumptions; real unit economics must be measured from live traffic.
- Bazaar/discovery is supported by x402 metadata but indexing is facilitator-dependent and can change.
