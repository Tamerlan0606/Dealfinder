from __future__ import annotations

import os
from typing import Any, Annotated

from pydantic import Field

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

API_BASE = os.getenv("WORKMINE_API_BASE", "https://workmine-api.onrender.com").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))

mcp = MCPServer(
    "WORKMINE Discovery",
    description="Pay-per-call x402 products for AI agents and API operators, including a premium x402 seller launch kit plus low-cost utilities: hashing, HMAC, Base64, URL encoding, JSON repair, text processing, HTML extraction and PDF text extraction. Base USDC pay-per-call.",
    website_url=API_BASE,
)

CATALOG: dict[str, dict[str, Any]] = {
    "x402_launch_kit": {"method":"POST","path":"/v1/x402/launch-kit","price_usd":19.0,"use":"generate a deploy-ready x402 seller launch kit with manifest, discovery metadata, implementation scaffold and marketplace registration checklist"},
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
    """Browse the complete WORKMINE catalog for free: paid API names, exact USDC-denominated prices, HTTP methods and URLs. Use this when comparing available tools; use find_workmine_tool when you already have a natural-language task. This catalog call itself does not execute or purchase a paid API."""
    return {"service":"WORKMINE","protocol":"x402 v2","network":"Base mainnet (eip155:8453)","asset":"USDC","api_base":API_BASE,"openapi":API_BASE+"/openapi.json","x402_manifest":API_BASE+"/.well-known/x402","llms_txt":API_BASE+"/llms.txt","tools":{n:{**m,"url":API_BASE+m["path"]} for n,m in CATALOG.items()}}

@mcp.tool()
def find_workmine_tool(task: Annotated[str, Field(description="Natural-language task the buyer needs completed, for example: 'repair malformed JSON', 'extract PDF text', or 'launch an x402 seller API'.")]) -> dict[str, Any]:
    """Find a relevant WORKMINE paid API from a natural-language task without purchasing it. Returns the selected tool, price and URL; actual execution requires a separate x402 USDC payment. Use workmine_catalog instead to browse all tools, or workmine_payment_instructions after selecting a tool."""
    q=task.lower()
    rules=[
        (["x402 launch","launch kit","x402 seller","monetize api","monetise api","bazaar setup","x402 deploy"],"x402_launch_kit"),
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
def workmine_launch_kit_offer() -> dict[str, Any]:
    """Quote the premium WORKMINE x402 Launch Kit without charging anything. Use this when an API developer or autonomous agent wants to monetize an HTTP service with x402 on Base. Returns the exact $19 USDC product URL, required request fields, deliverables and payment flow. This MCP call is free and read-only; payment occurs only if the buyer later calls the returned HTTP endpoint and signs its x402 challenge."""
    meta = CATALOG["x402_launch_kit"]
    return {
        "product": "x402_launch_kit",
        "price_usdc": meta["price_usd"],
        "network": "Base mainnet (eip155:8453)",
        "endpoint": API_BASE + meta["path"],
        "method": "POST",
        "what_you_get": [
            "x402 seller manifest",
            "discovery metadata",
            "FastAPI or Express implementation scaffold",
            "marketplace registration checklist",
            "seller economics metadata",
        ],
        "required_input": {
            "service_name": "Name of the API/service",
            "base_url": "Public HTTPS origin",
            "pay_to": "Seller EVM receiving address",
        },
        "optional_input": {
            "stack": "fastapi or express; default fastapi",
            "product_path": "Paid route; default /v1/tool",
            "price_usd": "Seller's intended price; default 0.01",
            "description": "What the seller's paid API does",
        },
        "payment": "Call the endpoint, read HTTP 402 PAYMENT-REQUIRED, sign the exact Base USDC payment, then retry.",
        "charged_now": False,
    }


@mcp.tool()
def workmine_payment_instructions(tool: Annotated[str, Field(description="Exact WORKMINE product slug returned by find_workmine_tool or workmine_catalog, for example x402_launch_kit, repair_json, or pdf_extract.")]) -> dict[str, Any]:
    """Return x402 payment and endpoint instructions for a selected WORKMINE tool without executing the paid call. Pass a tool slug returned by find_workmine_tool or workmine_catalog. The buyer then calls the endpoint, reads its HTTP 402 challenge, signs the exact Base USDC payment and retries."""
    meta=CATALOG.get(tool)
    if meta is None:
        return {"error":"Unknown tool","available":sorted(CATALOG)}
    return {"tool":tool,"url":API_BASE+meta["path"],"method":meta["method"],"price_usd":meta["price_usd"],"protocol":"x402 v2","network":"eip155:8453","asset":"USDC","flow":["Call endpoint","Read HTTP 402 PAYMENT-REQUIRED challenge","Sign exact USDC payment","Retry request with payment","Receive result and settlement receipt"],"openapi":API_BASE+"/openapi.json","manifest":API_BASE+"/.well-known/x402"}

if __name__ == "__main__":
    mcp.run(transport="streamable-http",host="0.0.0.0",port=PORT,streamable_http_path="/mcp",stateless_http=True,json_response=True,transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
