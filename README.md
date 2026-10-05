# WORKMINE — x402 pay-per-call APIs for AI agents

WORKMINE is a remote MCP gateway and x402 API seller for autonomous agents. Discovery is free; paid execution settles in **USDC on Base mainnet** with no WORKMINE account or API key.

## Start here

- **$0.001 Paid Ping** — verify an end-to-end x402 purchase at minimum cost.
- **$0.001 Hash / HMAC / Base64 / URL encoding** — deterministic utilities for agent pipelines.
- **$0.003 JSON Repair** — repair malformed JSON into valid structured data.
- **$0.01 PDF text extraction** — extract a document's text layer.
- **$0.05 x402 Readiness Audit** — score an x402 seller manifest and return concrete fixes.
- **$19 x402 Launch Kit** — generate a deploy-ready seller package.

### Machine discovery

- MCP server: https://workmine-mcp.onrender.com/mcp
- API: https://workmine-api.onrender.com
- x402 manifest: https://workmine-api.onrender.com/.well-known/x402
- OpenAPI: https://workmine-api.onrender.com/openapi.json
- LLM discovery: https://workmine-api.onrender.com/llms.txt
- Discovery JSON: https://workmine-api.onrender.com/x402/discovery.json
- Official MCP Registry name: `io.github.Tamerlan0606/workmine`

For a new MCP client, call `workmine_start_here`. If you already know the task, call `find_workmine_tool`. Browsing and quoting do **not** purchase anything. A paid call is made only when an x402-aware buyer executes a priced endpoint and completes the payment challenge.

## Why agents use it

WORKMINE focuses on low-cost deterministic operations that are useful inside automated pipelines: hashing, HMAC, encoding, JSON repair, text processing, HTML/PDF extraction, plus seller tooling for the x402 ecosystem. Prices start at **$0.001 USDC per call**.

## Revenue semantics

HTTP `402 Payment Required`, crawler probes, modeled billable amounts and directory listings are **not revenue**. WORKMINE recognizes revenue only after a confirmed settlement and emits a `WORKMINE_SETTLEMENT` event with the transaction identifier.

## Protocol

- x402 v2
- Base mainnet (`eip155:8453`)
- USDC
- non-custodial seller settlement
- Streamable HTTP MCP

See `workmine/README.md` for implementation details and limitations.
