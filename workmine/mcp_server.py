from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

API_BASE = os.getenv("WORKMINE_API_BASE", "https://workmine-api.onrender.com").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))

mcp = MCPServer(
    "WORKMINE Discovery",
    description="Discovery gateway for low-cost x402 pay-per-call utility APIs on Base USDC.",
    website_url=API_BASE,
)

CATALOG: dict[str, dict[str, Any]] = {
    "normalize_text": {"method": "POST", "path": "/v1/text/normalize", "price_usd": 0.001, "use": "normalize Unicode and whitespace"},
    "keywords": {"method": "POST", "path": "/v1/text/keywords", "price_usd": 0.002, "use": "extract keywords from text"},
    "repair_json": {"method": "POST", "path": "/v1/json/repair", "price_usd": 0.003, "use": "repair malformed JSON"},
    "redact_text": {"method": "POST", "path": "/v1/text/redact", "price_usd": 0.002, "use": "redact common identifiers"},
    "html_to_text": {"method": "POST", "path": "/v1/html/to-text", "price_usd": 0.003, "use": "extract clean text and links from HTML"},
    "pdf_extract": {"method": "POST", "path": "/v1/pdf/extract-text", "price_usd": 0.010, "use": "extract text layer from PDF"},
    "hash": {"method": "GET or POST", "path": "/v1/hash", "price_usd": 0.001, "use": "SHA-256, SHA-512, SHA-1 or MD5 digest"},
    "hmac": {"method": "POST", "path": "/v1/hmac", "price_usd": 0.001, "use": "HMAC SHA-256 or SHA-512"},
    "base64_encode": {"method": "GET or POST", "path": "/v1/base64/encode", "price_usd": 0.001, "use": "Base64 encode UTF-8"},
    "base64_decode": {"method": "GET or POST", "path": "/v1/base64/decode", "price_usd": 0.001, "use": "Base64 decode to UTF-8"},
    "url_encode": {"method": "GET or POST", "path": "/v1/url/encode", "price_usd": 0.001, "use": "percent-encode text for URLs"},
    "url_decode": {"method": "GET or POST", "path": "/v1/url/decode", "price_usd": 0.001, "use": "decode percent-encoded text"},
}


@mcp.tool()
def workmine_catalog() -> dict[str, Any]:
    """Discover WORKMINE paid APIs, prices, methods and x402 integration URLs."""
    return {
        "service": "WORKMINE",
        "protocol": "x402 v2",
        "network": "Base mainnet (eip155:8453)",
        "asset": "USDC",
        "api_base": API_BASE,
        "openapi": API_BASE + "/openapi.json",
        "x402_manifest": API_BASE + "/.well-known/x402",
        "llms_txt": API_BASE + "/llms.txt",
        "tools": {name: {**meta, "url": API_BASE + meta["path"]} for name, meta in CATALOG.items()},
    }


@mcp.tool()
def find_workmine_tool(task: str) -> dict[str, Any]:
    """Find the cheapest relevant WORKMINE paid API for a natural-language task."""
    q = task.lower()
    rules = [
        (["sha", "hash", "checksum", "digest"], "hash"),
        (["hmac", "signature", "sign"], "hmac"),
        (["base64", "b64"], "base64_decode" if "decode" in q else "base64_encode"),
        (["url", "percent"], "url_decode" if "decode" in q else "url_encode"),
        (["json", "repair", "malformed"], "repair_json"),
        (["keyword", "keywords"], "keywords"),
        (["redact", "email", "phone", "identifier"], "redact_text"),
        (["html", "webpage"], "html_to_text"),
        (["pdf"], "pdf_extract"),
        (["normalize", "whitespace", "unicode", "clean text"], "normalize_text"),
    ]
    for words, name in rules:
        if any(word in q for word in words):
            meta = CATALOG[name]
            return {"match": name, **meta, "url": API_BASE + meta["path"], "payment": "x402 Base USDC"}
    cheapest = min(CATALOG.items(), key=lambda item: item[1]["price_usd"])
    return {"match": cheapest[0], **cheapest[1], "url": API_BASE + cheapest[1]["path"], "payment": "x402 Base USDC", "note": "No exact semantic match; returning cheapest utility."}


@mcp.tool()
def workmine_payment_instructions(tool: str) -> dict[str, Any]:
    """Return machine-readable x402 payment and endpoint information for a WORKMINE tool."""
    meta = CATALOG.get(tool)
    if meta is None:
        return {"error": "Unknown tool", "available": sorted(CATALOG)}
    return {
        "tool": tool,
        "url": API_BASE + meta["path"],
        "method": meta["method"],
        "price_usd": meta["price_usd"],
        "protocol": "x402 v2",
        "network": "eip155:8453",
        "asset": "USDC",
        "flow": "Call endpoint without payment -> read 402 PAYMENT-REQUIRED -> sign payment -> retry request.",
        "openapi": API_BASE + "/openapi.json",
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=PORT,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
