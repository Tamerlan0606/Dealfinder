from __future__ import annotations

import os
import json
import urllib.request
import time
from datetime import datetime, timezone
from typing import Any, Annotated

from pydantic import Field

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, TextContent
from mcp.server.transport_security import TransportSecuritySettings

API_BASE = os.getenv("WORKMINE_API_BASE", "https://workmine-api.onrender.com").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))

mcp = MCPServer(
    "WORKMINE Discovery",
    description="Pay-per-call x402 products for AI agents and API operators, including a premium x402 seller launch kit plus low-cost utilities: hashing, HMAC, Base64, URL encoding, JSON repair, text processing, HTML extraction and PDF text extraction. Base USDC pay-per-call.",
    website_url=API_BASE,
)

def _track(tool: str, **data: Any) -> None:
    print(json.dumps({"event":"WORKMINE_MCP_TOOL","tool":tool,"ts":datetime.now(timezone.utc).isoformat(),**data}, separators=(",",":")), flush=True)

def _resolve_pay_to() -> str:
    direct = os.getenv("PAY_TO", "").strip()
    if direct:
        return direct
    try:
        with urllib.request.urlopen(API_BASE + "/.well-known/x402", timeout=5) as response:
            manifest = json.loads(response.read().decode("utf-8"))
        return str(manifest.get("payment", {}).get("x402", {}).get("payTo", "")).strip()
    except Exception as exc:
        print(json.dumps({"event":"WORKMINE_MCP_PAYMENT_SETUP","ok":False,"error":str(exc)[:200]}, separators=(",",":")), flush=True)
        return ""


PAID_PING_HANDLER = None
MCP_PAY_TO = _resolve_pay_to()
if MCP_PAY_TO:
    try:
        from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.mcp import MCPToolResult, ResourceInfo, SyncPaymentWrapperConfig, create_payment_wrapper_sync
        from x402.schemas import ResourceConfig
        from x402.server import x402ResourceServerSync

        _facilitator = HTTPFacilitatorClientSync(FacilitatorConfig(url=os.getenv("X402_FACILITATOR_URL", "https://facilitator.payai.network")))
        _resource_server = x402ResourceServerSync(_facilitator)
        _resource_server.register("eip155:8453", ExactEvmServerScheme())
        _init_error = None
        for _attempt in range(1, 5):
            try:
                _resource_server.initialize()
                _init_error = None
                break
            except Exception as exc:
                _init_error = exc
                if _attempt == 4:
                    raise
                print(json.dumps({"event":"WORKMINE_MCP_PAYMENT_RETRY","attempt":_attempt,"error":str(exc)[:200]}, separators=(",",":")), flush=True)
                time.sleep(min(2 ** (_attempt - 1), 4))
        _accepts = _resource_server.build_payment_requirements(
            ResourceConfig(
                scheme="exact",
                network="eip155:8453",
                pay_to=MCP_PAY_TO,
                price="$0.001",
                extra={"name":"USDC","version":"2"},
            )
        )
        _paid_ping = create_payment_wrapper_sync(
            _resource_server,
            SyncPaymentWrapperConfig(
                accepts=_accepts,
                resource=ResourceInfo(
                    url="mcp://tool/workmine_paid_ping",
                    description="WORKMINE minimum-cost paid x402 availability probe",
                    mime_type="application/json",
                ),
            ),
        )
        PAID_PING_HANDLER = _paid_ping(
            lambda args, _ctx: MCPToolResult(
                content=[{"type":"text","text":json.dumps({"ok":True,"service":"WORKMINE","nonce":args.get("nonce",""),"paid":True})}]
            )
        )
        print(json.dumps({"event":"WORKMINE_MCP_PAYMENT_SETUP","ok":True,"tool":"workmine_paid_ping","price_usdc":0.001}, separators=(",",":")), flush=True)
    except Exception as exc:
        print(json.dumps({"event":"WORKMINE_MCP_PAYMENT_SETUP","ok":False,"error":str(exc)[:300]}, separators=(",",":")), flush=True)


CATALOG: dict[str, dict[str, Any]] = {
    "paid_ping": {"method":"GET","path":"/v1/ping","price_usd":0.001,"use":"verify x402 payment capability and WORKMINE availability with the lowest-cost paid call"},
    "x402_readiness_audit": {
        "method": "POST",
        "path": "/v1/x402/readiness-audit",
        "price_usd": 0.05,
        "description": "Audit an x402 seller manifest for discoverability and payment readiness; returns a score, issues and concrete fixes.",
    },
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
    _track("workmine_catalog")
    return {"service":"WORKMINE","protocol":"x402 v2","network":"Base mainnet (eip155:8453)","asset":"USDC","recommended_first_purchase":{"tool":"paid_ping","price_usdc":0.001,"reason":"minimum-cost x402 payment capability check"},"api_base":API_BASE,"openapi":API_BASE+"/openapi.json","x402_manifest":API_BASE+"/.well-known/x402","llms_txt":API_BASE+"/llms.txt","tools":{n:{**m,"url":API_BASE+m["path"]} for n,m in CATALOG.items()}}

@mcp.tool()
def find_workmine_tool(task: Annotated[str, Field(description="Natural-language task the buyer needs completed, for example: 'repair malformed JSON', 'extract PDF text', or 'launch an x402 seller API'.")]) -> dict[str, Any]:
    """Find a relevant WORKMINE paid API from a natural-language task without purchasing it. Returns the selected tool, price and URL; actual execution requires a separate x402 USDC payment. Use workmine_catalog instead to browse all tools, or workmine_payment_instructions after selecting a tool."""
    _track("find_workmine_tool", task=task[:120])
    q=task.lower()
    rules=[
        (["try workmine","test workmine","test payment","x402 payment test","paid ping","payment probe","verify payment"],"paid_ping"),
        (["x402 audit","readiness","readiness audit","validate manifest","manifest audit","check manifest","x402 preflight"],"x402_readiness_audit"),
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
def workmine_start_here() -> dict[str, Any]:
    """Free WORKMINE entry point for new buyers. Use this when the buyer wants to try WORKMINE or is unsure what to purchase. It recommends the lowest-friction relevant paid action and never charges by itself."""
    _track("workmine_start_here")
    return {
        "service": "WORKMINE",
        "charged_now": False,
        "recommended_first_purchase": {
            "product": "paid_ping",
            "price_usdc": 0.001,
            "best_for": "new buyers and autonomous agents that want to verify x402 payment capability at minimum cost",
            "endpoint": API_BASE + CATALOG["paid_ping"]["path"],
        },
        "seller_next_purchase": {"product":"x402_readiness_audit","price_usdc":0.05,"endpoint":API_BASE + CATALOG["x402_readiness_audit"]["path"]},
        "micro_tools_from_usdc": 0.001,
        "premium_launch_kit_usdc": 19.0,
        "next": "Use find_workmine_tool for a specific task, or workmine_readiness_audit_offer for the $0.05 preflight audit.",
    }


@mcp.tool()
def workmine_paid_ping(ctx: Context, nonce: Annotated[str, Field(max_length=120, description="Optional caller nonce echoed after successful payment.")] = "") -> CallToolResult:
    """Execute WORKMINE's native MCP x402 payment test for $0.001 USDC on Base. First call returns PaymentRequired; an x402-aware MCP client can retry with payment metadata and settle directly to WORKMINE."""
    _track("workmine_paid_ping", nonce=nonce[:120])
    if PAID_PING_HANDLER is None:
        return CallToolResult(content=[TextContent(type="text", text="Native MCP payment is temporarily unavailable; use the HTTP /v1/ping x402 endpoint instead.")], is_error=True)
    request_meta: dict[str, Any] = {}
    try:
        meta_obj = ctx.request_context.meta
        if meta_obj is not None:
            if getattr(meta_obj, "model_extra", None):
                request_meta.update(meta_obj.model_extra)
            if hasattr(meta_obj, "model_dump"):
                request_meta.update({k:v for k,v in meta_obj.model_dump(exclude_none=True).items() if k not in request_meta})
    except Exception:
        request_meta = {}
    result = PAID_PING_HANDLER({"nonce":nonce}, {"_meta":request_meta,"toolName":"workmine_paid_ping"})
    receipt = getattr(result, "meta", None) or getattr(result, "_meta", None)
    if isinstance(receipt, dict):
        receipt = receipt.get("x402/payment-response")
    if isinstance(receipt, dict) and receipt.get("success") and receipt.get("transaction"):
        print(json.dumps({"event":"WORKMINE_SETTLEMENT","source":"mcp","product":"paid_ping","amount_usdc":0.001,"transaction":receipt.get("transaction"),"network":receipt.get("network","eip155:8453")}, separators=(",",":")), flush=True)
    return result

@mcp.tool()
def workmine_paid_ping_offer() -> dict[str, Any]:
    """Free quote for WORKMINE Paid Ping, the minimum-cost $0.001 USDC x402 purchase. Use this when an autonomous agent wants to verify that it can complete an x402 payment before buying a larger tool. This MCP call is free and does not charge anything."""
    _track("workmine_paid_ping_offer")
    return {
        "product": "paid_ping",
        "price_usdc": 0.001,
        "network": "Base mainnet (eip155:8453)",
        "endpoint": API_BASE + "/v1/ping",
        "method": "GET",
        "example": API_BASE + "/v1/ping?nonce=first-payment",
        "purpose": "Verify end-to-end x402 payment capability and WORKMINE availability at minimum cost.",
        "charged_now": False,
    }


@mcp.tool()
def workmine_readiness_audit_offer() -> dict[str, Any]:
    """Quote the WORKMINE x402 Readiness Audit without charging anything. Use this first for sellers who already have an x402 manifest and want a low-cost preflight check before marketplace registration. The audit costs $0.05 USDC on Base and checks identity, HTTPS resources, x402 v2 metadata, Base/USDC, payTo format, machine-readable discovery and origin consistency. This MCP call is free; payment occurs only when the buyer calls the returned HTTP endpoint."""
    _track("workmine_readiness_audit_offer")
    meta = CATALOG["x402_readiness_audit"]
    return {
        "product": "x402_readiness_audit",
        "price_usdc": 0.05,
        "network": "Base mainnet (eip155:8453)",
        "endpoint": API_BASE + meta["path"],
        "method": "POST",
        "input": {"manifest": "object: seller's /.well-known/x402 JSON", "expected_origin": "optional public HTTPS origin"},
        "output": ["0-100 readiness score", "ready/needs_work/not_ready grade", "concrete issues", "concrete fixes", "Launch Kit upgrade path"],
        "charged_now": False,
    }


@mcp.tool()
def workmine_launch_kit_offer() -> dict[str, Any]:
    """Quote the premium WORKMINE x402 Launch Kit without charging anything. Use this when an API developer or autonomous agent wants to monetize an HTTP service with x402 on Base. Returns the exact $19 USDC product URL, required request fields, deliverables and payment flow. This MCP call is free and read-only; payment occurs only if the buyer later calls the returned HTTP endpoint and signs its x402 challenge."""
    _track("workmine_launch_kit_offer")
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
    _track("workmine_payment_instructions", product=tool)
    meta=CATALOG.get(tool)
    if meta is None:
        return {"error":"Unknown tool","available":sorted(CATALOG)}
    return {"tool":tool,"url":API_BASE+meta["path"],"method":meta["method"],"price_usd":meta["price_usd"],"protocol":"x402 v2","network":"eip155:8453","asset":"USDC","flow":["Call endpoint","Read HTTP 402 PAYMENT-REQUIRED challenge","Sign exact USDC payment","Retry request with payment","Receive result and settlement receipt"],"openapi":API_BASE+"/openapi.json","manifest":API_BASE+"/.well-known/x402"}

if __name__ == "__main__":
    mcp.run(transport="streamable-http",host="0.0.0.0",port=PORT,streamable_http_path="/mcp",stateless_http=True,json_response=True,transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
