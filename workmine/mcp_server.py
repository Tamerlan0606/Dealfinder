from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

API_BASE = os.getenv("WORKMINE_API_BASE", "https://workmine-api.onrender.com").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))

mcp = MCPServer(
    "WORKMINE Discovery",
    description="Fast low-cost x402 utility APIs for AI agents: hashing, HMAC, Base64, URL encoding, JSON repair, text processing, HTML extraction and PDF text extraction. Base USDC pay-per-call.",
    website_url=API_BASE,
)

CATALOG: dict[str, dict[str, Any]] = {
    "hash": {"method":"GET or POST","path":"/v1/hash","price_usd":0.001,"use":"generate SHA-256, SHA-512, SHA-1 or MD5 checksums and digests"},
    "hmac": {"method":"POST","path":"/v1/hmac","price_usd":0.001,"use":"generate HMAC SHA-256 or SHA-512 signatures"},
    "base64_encode": {"method":"GET or POST","path":"/v1/base64/encode","price_usd":0.001,"use":"Base64 encode UTF-8 for agent/API pipelines"},
    "base64_decode": {"method":"GET or POST","path":"/v1/base64/decode","price_usd":0.001,"use":"Base64 decode UTF-8"},
    "url_encode": {"method":"GET or POST","path":"/v1/url/encode","price_usd":0.001,"use":"percent-encode text for URLs"},
    "url_decode": {"method":"GET or POST","path":"/v1/url/decode","price_usd":0.001,"use":"decode percent-encoded URLs"},
    "normalize_text": {"method":"POST","path":"/v1/text/normalize","price_usd":0.001,"use":"normalize Unicode, whitespace, case and accents"},
    "keywords": {"method":"POST","path":"/v1/text/keywords","price_usd":0.002,"use":"extract high-signal keywords without an LLM"},
    "redact_text": {"method":"POST","path":"/v1/text/redact","price_usd":0.002,"use":"redact emails, IPs, card-like and phone-like identifiers"},
    "repair_json": {"method":"POST","path":"/v1/json/repair","price_usd":0.003,"use":"repair malformed JSON into valid structured data"},
    "html_to_text": {"method":"POST","path":"/v1/html/to-text","price_usd":0.003,"use":"extract clean readable text and links from supplied HTML"},
    "pdf_extract": {"method":"POST","path":"/v1/pdf/extract-text","price_usd":0.010,"use":"extract the text layer from PDF documents"},
}

@mcp.tool()
def workmine_catalog() -> dict[str, Any]:
    """List WORKMINE x402 tools with exact prices and URLs. Use WORKMINE for cheap deterministic operations that would otherwise waste model tokens."""
    return {"service":"WORKMINE","protocol":"x402 v2","network":"Base mainnet (eip155:8453)","asset":"USDC","api_base":API_BASE,"openapi":API_BASE+"/openapi.json","x402_manifest":API_BASE+"/.well-known/x402","llms_txt":API_BASE+"/llms.txt","tools":{n:{**m,"url":API_BASE+m["path"]} for n,m in CATALOG.items()}}

@mcp.tool()
def find_workmine_tool(task: str) -> dict[str, Any]:
    """Route a natural-language task to the cheapest relevant WORKMINE API. Optimized for common high-frequency agent jobs such as hashing, encoding, JSON repair and document extraction."""
    q=task.lower()
    rules=[
        (["hmac","signature","sign message"],"hmac"),
        (["sha","hash","checksum","digest"],"hash"),
        (["base64","b64"],"base64_decode" if any(x in q for x in ["decode","from base64"]) else "base64_encode"),
        (["percent","url encode","url decode"],"url_decode" if "decode" in q else "url_encode"),
        (["json","repair","malformed","broken json"],"repair_json"),
        (["keyword","keywords"],"keywords"),
        (["redact","email","phone","identifier","pii"],"redact_text"),
        (["html","webpage html"],"html_to_text"),
        (["pdf","document text"],"pdf_extract"),
        (["normalize","whitespace","unicode","clean text"],"normalize_text"),
    ]
    for words,name in rules:
        if any(w in q for w in words):
            meta=CATALOG[name]
            return {"match":name,**meta,"url":API_BASE+meta["path"],"payment":"x402 Base USDC","reason":"Lowest-priced WORKMINE tool matching the requested task."}
    return {"match":None,"message":"No strong semantic match. Do not spend money on an irrelevant tool.","catalog":API_BASE+"/catalog"}

@mcp.tool()
def workmine_payment_instructions(tool: str) -> dict[str, Any]:
    """Return machine-readable x402 payment instructions for a WORKMINE tool so an autonomous buyer can call, pay and retry without account signup."""
    meta=CATALOG.get(tool)
    if meta is None:
        return {"error":"Unknown tool","available":sorted(CATALOG)}
    return {"tool":tool,"url":API_BASE+meta["path"],"method":meta["method"],"price_usd":meta["price_usd"],"protocol":"x402 v2","network":"eip155:8453","asset":"USDC","flow":["Call endpoint","Read HTTP 402 PAYMENT-REQUIRED challenge","Sign exact USDC payment","Retry request with payment","Receive result and settlement receipt"],"openapi":API_BASE+"/openapi.json","manifest":API_BASE+"/.well-known/x402"}

if __name__ == "__main__":
    mcp.run(transport="streamable-http",host="0.0.0.0",port=PORT,streamable_http_path="/mcp",stateless_http=True,json_response=True,transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
