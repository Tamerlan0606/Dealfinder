import io
import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
import unicodedata
import urllib.request
import urllib.parse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from json_repair import repair_json
from pydantic import BaseModel, Field
from pypdf import PdfReader

APP_NAME = "WORKMINE"
VERSION = "0.2.0"
PAYMENT_MODE = os.getenv("WORKMINE_PAYMENT_MODE", "open").strip().lower()
PAY_TO = os.getenv("PAY_TO", "").strip()
X402_NETWORK = os.getenv("X402_NETWORK", "eip155:8453").strip()
X402_FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
DB_PATH = os.getenv("WORKMINE_DB_PATH", "/tmp/workmine.db")
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "200000"))
MAX_PDF_BYTES = int(os.getenv("MAX_PDF_BYTES", str(8 * 1024 * 1024)))

PRODUCTS: dict[str, dict[str, Any]] = {
    "normalize": {
        "path": "/v1/text/normalize",
        "price": 0.001,
        "estimated_cost": 0.00003,
        "description": "Normalize whitespace, Unicode, case and accents in text.",
        "tags": ["text", "normalize", "cleanup"],
    },
    "keywords": {
        "path": "/v1/text/keywords",
        "price": 0.002,
        "estimated_cost": 0.00005,
        "description": "Extract high-signal keywords from text without an LLM.",
        "tags": ["text", "keywords", "nlp"],
    },
    "repair_json": {
        "path": "/v1/json/repair",
        "price": 0.003,
        "estimated_cost": 0.00005,
        "description": "Repair malformed JSON and return valid structured data.",
        "tags": ["json", "repair", "developer"],
    },
    "redact": {
        "path": "/v1/text/redact",
        "price": 0.002,
        "estimated_cost": 0.00004,
        "description": "Redact common emails, IPs, cards and phone-like identifiers.",
        "tags": ["text", "privacy", "redact"],
    },
    "html_to_text": {
        "path": "/v1/html/to-text",
        "price": 0.003,
        "estimated_cost": 0.00006,
        "description": "Convert HTML to clean readable text and extract links.",
        "tags": ["html", "extract", "text"],
    },
    "pdf_extract": {
        "path": "/v1/pdf/extract-text",
        "price": 0.01,
        "estimated_cost": 0.0007,
        "description": "Extract text from a text-based PDF.",
        "tags": ["pdf", "extract", "document"],
    },
    "hash": {
        "path": "/v1/hash",
        "price": 0.001,
        "estimated_cost": 0.00001,
        "description": "Generate SHA-256, SHA-512, SHA-1 or MD5 hex digests for agent pipelines, checksums and deduplication.",
        "tags": ["hash", "sha256", "sha512", "checksum", "encoding"],
    },
    "hmac": {
        "path": "/v1/hmac",
        "price": 0.001,
        "estimated_cost": 0.00001,
        "description": "Generate HMAC-SHA256 or HMAC-SHA512 signatures from a caller-supplied key and message.",
        "tags": ["hmac", "sha256", "signature", "encoding"],
    },
    "base64_encode": {
        "path": "/v1/base64/encode",
        "price": 0.001,
        "estimated_cost": 0.00001,
        "description": "Base64-encode UTF-8 text for binary-safe transport in agent and API pipelines.",
        "tags": ["base64", "encode", "encoding"],
    },
    "base64_decode": {
        "path": "/v1/base64/decode",
        "price": 0.001,
        "estimated_cost": 0.00001,
        "description": "Decode Base64 to UTF-8 text with strict validation.",
        "tags": ["base64", "decode", "encoding"],
    },
    "url_encode": {
        "path": "/v1/url/encode",
        "price": 0.001,
        "estimated_cost": 0.00001,
        "description": "RFC 3986 percent-encode text for safe URL path and query transport.",
        "tags": ["url", "percent-encoding", "encode"],
    },
    "url_decode": {
        "path": "/v1/url/decode",
        "price": 0.001,
        "estimated_cost": 0.00001,
        "description": "Decode RFC 3986 percent-encoded text back to Unicode.",
        "tags": ["url", "percent-encoding", "decode"],
    },
}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "are", "was", "were", "will", "your", "you",
    "but", "not", "all", "can", "into", "about", "как", "что", "это", "для", "или", "его", "она", "они", "так",
    "при", "без", "над", "под", "если", "уже", "еще", "ещё", "где", "чтобы", "который", "которые", "когда", "быть",
}

class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)

class NormalizeInput(TextInput):
    lowercase: bool = False
    strip_accents: bool = False

class KeywordsInput(TextInput):
    limit: int = Field(default=12, ge=1, le=50)

class HtmlInput(BaseModel):
    html: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)

class JsonRepairInput(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)

class HashInput(TextInput):
    algorithm: str = "sha256"

class HmacInput(TextInput):
    key: str = Field(min_length=1, max_length=10000)
    algorithm: str = "sha256"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def payment_enabled() -> bool:
    return PAYMENT_MODE == "x402" and bool(PAY_TO)


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                paid INTEGER NOT NULL,
                price_usd REAL NOT NULL,
                estimated_cost_usd REAL NOT NULL,
                gross_profit_usd REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS settlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                transaction_id TEXT NOT NULL UNIQUE,
                payer TEXT,
                network TEXT NOT NULL,
                amount_atomic TEXT,
                amount_usdc REAL,
                phase TEXT
            )
            """
        )
        con.commit()


def record_event(product: str, started: float) -> None:
    meta = PRODUCTS[product]
    paid = 1 if payment_enabled() else 0
    price = float(meta["price"]) if paid else 0.0
    cost = float(meta["estimated_cost"])
    profit = price - cost
    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT INTO events(ts, endpoint, duration_ms, paid, price_usd, estimated_cost_usd, gross_profit_usd) VALUES(?,?,?,?,?,?,?)",
                (utcnow(), product, (time.perf_counter() - started) * 1000.0, paid, price, cost, profit),
            )
            con.commit()
    except Exception:
        pass


def record_settlement(ctx: Any) -> None:
    result = ctx.result
    if not getattr(result, "success", False):
        return
    tx = str(getattr(result, "transaction", "") or "")
    if not tx:
        return
    raw_amount = getattr(result, "amount", None)
    amount_usdc = None
    try:
        if raw_amount is not None:
            amount_usdc = int(str(raw_amount)) / 1_000_000.0
    except (TypeError, ValueError):
        amount_usdc = None
    payload = {
        "event": "WORKMINE_SETTLEMENT",
        "ts": utcnow(),
        "transaction": tx,
        "payer": getattr(result, "payer", None),
        "network": str(getattr(result, "network", X402_NETWORK)),
        "amount_atomic": str(raw_amount) if raw_amount is not None else None,
        "amount_usdc": amount_usdc,
        "phase": getattr(ctx, "phase", None),
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT OR IGNORE INTO settlements(ts, transaction_id, payer, network, amount_atomic, amount_usdc, phase) VALUES(?,?,?,?,?,?,?)",
                (payload["ts"], tx, payload["payer"], payload["network"], payload["amount_atomic"], amount_usdc, payload["phase"]),
            )
            con.commit()
    except Exception as exc:
        print(json.dumps({"event": "WORKMINE_SETTLEMENT_DB_ERROR", "error": str(exc)}), flush=True)


def summary_stats() -> dict[str, Any]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        total = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(price_usd),0), COALESCE(SUM(estimated_cost_usd),0), COALESCE(SUM(gross_profit_usd),0) FROM events"
        ).fetchone()
        rows = con.execute(
            """
            SELECT endpoint, COUNT(*), COALESCE(SUM(price_usd),0), COALESCE(SUM(estimated_cost_usd),0),
                   COALESCE(SUM(gross_profit_usd),0), COALESCE(AVG(duration_ms),0)
            FROM events GROUP BY endpoint ORDER BY SUM(gross_profit_usd) DESC, COUNT(*) DESC
            """
        ).fetchall()
        settled = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount_usdc),0) FROM settlements"
        ).fetchone()
        recent_settlements = con.execute(
            "SELECT ts, transaction_id, payer, network, amount_usdc FROM settlements ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return {
        "calls": total[0],
        "modeled_billable_usd": round(total[1], 6),
        "actual_settlements": settled[0],
        "actual_settled_usdc": round(settled[1], 6),
        "estimated_cost_usd": round(total[2], 6),
        "modeled_gross_profit_usd": round(total[3], 6),
        "payment_mode": "x402" if payment_enabled() else "open",
        "products": [
            {
                "name": r[0], "calls": r[1], "revenue_usd": round(r[2], 6),
                "estimated_cost_usd": round(r[3], 6), "gross_profit_usd": round(r[4], 6),
                "avg_duration_ms": round(r[5], 2),
            }
            for r in rows
        ],
        "recent_settlements": [
            {"ts": r[0], "transaction": r[1], "payer": r[2], "network": r[3], "amount_usdc": r[4]}
            for r in recent_settlements
        ],
    }


def normalize_text(text: str, lowercase: bool, strip_accents: bool) -> str:
    value = unicodedata.normalize("NFKC", text)
    value = re.sub(r"[\t\r\f\v]+", " ", value)
    value = re.sub(r"[ ]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if strip_accents:
        value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    if lowercase:
        value = value.lower()
    return value


def extract_keywords(text: str, limit: int) -> list[dict[str, Any]]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_-]{2,}", text.lower())
    words = [w for w in words if w not in STOPWORDS and not w.isdigit()]
    counts = Counter(words)
    return [{"keyword": w, "count": c} for w, c in counts.most_common(limit)]


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    patterns = {
        "email": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "card_like": r"\b(?:\d[ -]*?){13,19}\b",
        "phone_like": r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)",
    }
    out = text
    counts: dict[str, int] = {}
    for label, pattern in patterns.items():
        out, count = re.subn(pattern, f"[REDACTED_{label.upper()}]", out, flags=re.IGNORECASE)
        counts[label] = count
    return out, counts


app = FastAPI(
    title="WORKMINE API",
    version=VERSION,
    description="A pay-per-call digital microservice farm with optional x402 USDC payments.",
)

init_db()

if PAYMENT_MODE == "x402":
    if not PAY_TO:
        raise RuntimeError("WORKMINE_PAYMENT_MODE=x402 requires PAY_TO receiving address")
    try:
        from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.server import x402ResourceServer

        facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=X402_FACILITATOR_URL))
        server = x402ResourceServer(facilitator)
        server.register(X402_NETWORK, ExactEvmServerScheme())
        server.on_after_settle(record_settlement)

        def discovery(sample_input: dict[str, Any], input_schema: dict[str, Any], example: Any) -> dict[str, Any]:
            return declare_discovery_extension(
                input=sample_input,
                input_schema=input_schema,
                output=OutputConfig(example=example),
            )

        routes: dict[str, RouteConfig] = {}
        for name, meta in PRODUCTS.items():
            # Bazaar extensions are omitted on POST because Bazaar discovery
            # currently validates GET/HEAD/DELETE inputs only.
            ext = {}
            kwargs: dict[str, Any] = {
                "accepts": [PaymentOption(scheme="exact", price=f"${meta['price']:.3f}" if meta["price"] < 0.01 else f"${meta['price']:.2f}", network=X402_NETWORK, pay_to=PAY_TO)],
                "description": meta["description"],
                "mime_type": "application/json",
                "service_name": "WORKMINE",
                "tags": meta["tags"],
            }
            if PUBLIC_BASE_URL:
                kwargs["resource"] = PUBLIC_BASE_URL + meta["path"]
            if ext:
                kwargs["extensions"] = ext
            routes[f"POST {meta['path']}"] = RouteConfig(**kwargs)

        get_products = [
            (
                {"path": "/v1/ping", "price": 0.001, "description": "Low-cost paid availability probe for autonomous agents.", "tags": ["ping", "availability", "agent"]},
                {"nonce": "agent-123"},
                {"type": "object", "properties": {"nonce": {"type": "string"}}},
                {"ok": True, "service": APP_NAME, "message": "paid pong", "nonce": "agent-123"},
            ),
            (
                PRODUCTS["hash"],
                {"text": "hello", "algorithm": "sha256"},
                {"type": "object", "properties": {"text": {"type": "string"}, "algorithm": {"type": "string"}}, "required": ["text"]},
                {"algorithm": "sha256", "digest": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"},
            ),
            (
                PRODUCTS["base64_encode"],
                {"text": "hello"},
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                {"value": "aGVsbG8="},
            ),
            (
                PRODUCTS["base64_decode"],
                {"text": "aGVsbG8="},
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                {"value": "hello"},
            ),
            (
                PRODUCTS["url_encode"],
                {"text": "hello world"},
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                {"value": "hello%20world"},
            ),
            (
                PRODUCTS["url_decode"],
                {"text": "hello%20world"},
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                {"value": "hello world"},
            ),
        ]
        for meta, sample, schema, example in get_products:
            ext = discovery(sample, schema, example)
            get_kwargs: dict[str, Any] = {
                "accepts": [PaymentOption(scheme="exact", price=f"$" + (f"{meta['price']:.3f}" if meta["price"] < 0.01 else f"{meta['price']:.2f}"), network=X402_NETWORK, pay_to=PAY_TO)],
                "description": meta["description"],
                "mime_type": "application/json",
                "service_name": APP_NAME,
                "tags": meta["tags"] + ["bazaar"],
                "extensions": ext,
            }
            if PUBLIC_BASE_URL:
                get_kwargs["resource"] = PUBLIC_BASE_URL + meta["path"]
            routes[f"GET {meta['path']}"] = RouteConfig(**get_kwargs)

        app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    except Exception as exc:
        raise RuntimeError(f"Unable to initialize x402 payment middleware: {exc}") from exc


@app.get("/v1/ping")
def paid_ping(nonce: str = "") -> dict[str, Any]:
    return {"ok": True, "service": APP_NAME, "message": "paid pong", "nonce": nonce, "ts": utcnow()}


@app.on_event("startup")
def register_agent_marketplaces() -> None:
    if not PUBLIC_BASE_URL:
        return
    payload = json.dumps({"origin": PUBLIC_BASE_URL}).encode("utf-8")
    req = urllib.request.Request(
        "https://agent402.tools/api/index/register",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "WORKMINE/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read(2000).decode("utf-8", errors="replace")
            print(f"Agent402 registration: HTTP {resp.status} {body}")
    except Exception as exc:
        print(f"Agent402 registration failed: {exc}")


@app.get("/.well-known/x402")
def well_known_x402() -> dict[str, Any]:
    base = PUBLIC_BASE_URL or ""
    resources = [base + "/v1/ping"] + [base + meta["path"] for meta in PRODUCTS.values()]
    return {
        "spec": "agent402-service-manifest/1",
        "version": 1,
        "resources": resources,
        "name": APP_NAME,
        "summary": "Low-cost deterministic utility APIs for autonomous agents, paid per call over x402.",
        "homepage": base,
        "ecosystem": {"primaryChain": "Base", "primaryChainId": 8453, "currency": "USDC", "protocol": "x402"},
        "payment": {
            "x402": {
                "version": 2,
                "currency": "USDC",
                "networks": [X402_NETWORK],
                "primaryNetwork": X402_NETWORK,
                "priceRange": "$0.001-$0.010",
                "payTo": PAY_TO,
                "nonCustodial": True,
            }
        },
        "machineReadable": {
            "openapi": base + "/openapi.json",
            "catalog": base + "/catalog",
            "llmsTxt": base + "/llms.txt",
            "discovery": base + "/x402/discovery.json",
        },
    }


@app.get("/x402/discovery.json")
def discovery_manifest() -> dict[str, Any]:
    base = PUBLIC_BASE_URL or ""
    items = [
        {
            "name": "paid_ping",
            "resource": base + "/v1/ping",
            "method": "GET",
            "price_usd": 0.001,
            "network": X402_NETWORK,
            "scheme": "exact",
            "description": "Low-cost paid availability probe for autonomous agents.",
        }
    ]
    for name, meta in PRODUCTS.items():
        items.append({
            "name": name,
            "resource": base + meta["path"],
            "method": "POST",
            "price_usd": meta["price"],
            "network": X402_NETWORK,
            "scheme": "exact",
            "description": meta["description"],
            "tags": meta["tags"],
        })
    return {"service": APP_NAME, "x402Version": 2, "payTo": PAY_TO, "items": items}


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt() -> str:
    base = PUBLIC_BASE_URL or ""
    return f"""# WORKMINE
> Pay-per-call x402 microservice API for autonomous agents.

Base URL: {base}
Protocol: x402 v2
Network: Base Mainnet (eip155:8453)
Settlement asset: USDC
Discovery manifest: {base}/x402/discovery.json
OpenAPI: {base}/openapi.json
Catalog: {base}/catalog

Paid endpoints:
- GET /v1/ping — $0.001 — availability probe
- POST /v1/text/normalize — $0.001 — Unicode/whitespace cleanup
- POST /v1/text/keywords — $0.002 — keyword extraction
- POST /v1/json/repair — $0.003 — malformed JSON repair
- POST /v1/text/redact — $0.002 — common identifier redaction
- POST /v1/html/to-text — $0.003 — HTML text/link extraction
- POST /v1/pdf/extract-text — $0.010 — text-layer PDF extraction
"""


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": VERSION,
        "payment_mode": "x402" if payment_enabled() else "open",
        "network": X402_NETWORK if payment_enabled() else None,
    }


@app.get("/catalog")
def catalog() -> dict[str, Any]:
    return {
        "service": APP_NAME,
        "version": VERSION,
        "payment_mode": "x402" if payment_enabled() else "open",
        "currency": "USD denominated; settled by x402 when enabled",
        "products": [
            {"name": name, **meta, "margin_per_call": round(meta["price"] - meta["estimated_cost"], 6)}
            for name, meta in PRODUCTS.items()
        ],
    }


@app.get("/stats")
def stats() -> dict[str, Any]:
    return summary_stats()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    stats_data = summary_stats()
    rows = "".join(
        f"<tr><td>{escape(name)}</td><td><code>POST {escape(meta['path'])}</code></td><td>${meta['price']:.3f}</td><td>{escape(meta['description'])}</td></tr>"
        for name, meta in PRODUCTS.items()
    )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>WORKMINE</title><style>
body{{font-family:ui-sans-serif,system-ui,-apple-system;max-width:1050px;margin:40px auto;padding:0 18px;color:#111}}
.hero{{padding:28px;border:1px solid #ddd;border-radius:18px;background:#fafafa}} h1{{font-size:44px;margin:0 0 8px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
.kpi{{border:1px solid #ddd;border-radius:12px;padding:14px}} .n{{font-size:28px;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin-top:22px}}th,td{{padding:12px;border-bottom:1px solid #e5e5e5;text-align:left;vertical-align:top}}
code{{font-size:12px}} .pill{{display:inline-block;padding:6px 10px;border-radius:999px;background:#111;color:white}}
a{{color:#111}} </style></head><body>
<div class='hero'><div class='pill'>{'LIVE x402' if payment_enabled() else 'OPEN TEST MODE'}</div><h1>WORKMINE</h1>
<p>Pay-per-call digital microservice farm. Machines call. Machines pay. The router measures margin per endpoint.</p>
<div class='kpis'><div class='kpi'><div>Calls</div><div class='n'>{stats_data['calls']}</div></div>
<div class='kpi'><div>Revenue</div><div class='n'>${stats_data['revenue_usd']:.4f}</div></div>
<div class='kpi'><div>Est. cost</div><div class='n'>${stats_data['estimated_cost_usd']:.4f}</div></div>
<div class='kpi'><div>Gross profit</div><div class='n'>${stats_data['gross_profit_usd']:.4f}</div></div></div>
<p><a href='/docs'>Interactive API docs</a> · <a href='/catalog'>Machine-readable catalog</a> · <a href='/stats'>Stats JSON</a></p></div>
<table><thead><tr><th>Product</th><th>Endpoint</th><th>Price/call</th><th>Purpose</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>"""


@app.post("/v1/text/normalize")
def api_normalize(payload: NormalizeInput) -> dict[str, Any]:
    started = time.perf_counter()
    value = normalize_text(payload.text, payload.lowercase, payload.strip_accents)
    record_event("normalize", started)
    return {"text": value, "chars": len(value)}


@app.post("/v1/text/keywords")
def api_keywords(payload: KeywordsInput) -> dict[str, Any]:
    started = time.perf_counter()
    result = extract_keywords(payload.text, payload.limit)
    record_event("keywords", started)
    return {"keywords": result, "count": len(result)}


@app.post("/v1/json/repair")
def api_repair_json(payload: JsonRepairInput) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        repaired = repair_json(payload.text, return_objects=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not repair JSON: {exc}") from exc
    record_event("repair_json", started)
    return {"value": repaired}


@app.post("/v1/text/redact")
def api_redact(payload: TextInput) -> dict[str, Any]:
    started = time.perf_counter()
    value, counts = redact_text(payload.text)
    record_event("redact", started)
    return {"text": value, "redactions": counts}


@app.post("/v1/html/to-text")
def api_html_to_text(payload: HtmlInput) -> dict[str, Any]:
    started = time.perf_counter()
    soup = BeautifulSoup(payload.html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    links = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href", "")).strip()
        if href and href not in links:
            links.append(href)
        if len(links) >= 100:
            break
    record_event("html_to_text", started)
    return {"text": text[:MAX_TEXT_CHARS], "links": links}


@app.post("/v1/hash")
def api_hash(payload: HashInput) -> dict[str, Any]:
    started = time.perf_counter()
    algo = payload.algorithm.lower().replace("-", "")
    allowed = {"sha256": hashlib.sha256, "sha512": hashlib.sha512, "sha1": hashlib.sha1, "md5": hashlib.md5}
    if algo not in allowed:
        raise HTTPException(status_code=422, detail="algorithm must be sha256, sha512, sha1 or md5")
    digest = allowed[algo](payload.text.encode("utf-8")).hexdigest()
    record_event("hash", started)
    return {"algorithm": algo, "digest": digest}


@app.post("/v1/hmac")
def api_hmac(payload: HmacInput) -> dict[str, Any]:
    started = time.perf_counter()
    algo = payload.algorithm.lower().replace("-", "")
    allowed = {"sha256": hashlib.sha256, "sha512": hashlib.sha512}
    if algo not in allowed:
        raise HTTPException(status_code=422, detail="algorithm must be sha256 or sha512")
    digest = hmac.new(payload.key.encode("utf-8"), payload.text.encode("utf-8"), allowed[algo]).hexdigest()
    record_event("hmac", started)
    return {"algorithm": algo, "digest": digest}


@app.post("/v1/base64/encode")
def api_base64_encode(payload: TextInput) -> dict[str, Any]:
    started = time.perf_counter()
    value = base64.b64encode(payload.text.encode("utf-8")).decode("ascii")
    record_event("base64_encode", started)
    return {"value": value}


@app.post("/v1/base64/decode")
def api_base64_decode(payload: TextInput) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        value = base64.b64decode(payload.text.encode("ascii"), validate=True).decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid Base64 UTF-8 payload") from exc
    record_event("base64_decode", started)
    return {"value": value}


@app.post("/v1/url/encode")
def api_url_encode(payload: TextInput) -> dict[str, Any]:
    started = time.perf_counter()
    value = urllib.parse.quote(payload.text, safe="")
    record_event("url_encode", started)
    return {"value": value}


@app.post("/v1/url/decode")
def api_url_decode(payload: TextInput) -> dict[str, Any]:
    started = time.perf_counter()
    value = urllib.parse.unquote(payload.text)
    record_event("url_decode", started)
    return {"value": value}


@app.post("/v1/pdf/extract-text")
async def api_pdf_extract(file: UploadFile = File(...)) -> dict[str, Any]:
    started = time.perf_counter()
    raw = await file.read(MAX_PDF_BYTES + 1)
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"PDF exceeds {MAX_PDF_BYTES} bytes")
    if not raw.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Expected a PDF file")
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = []
        for index, page in enumerate(reader.pages[:200], start=1):
            pages.append({"page": index, "text": page.extract_text() or ""})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {exc}") from exc
    record_event("pdf_extract", started)
    return {"filename": file.filename, "pages": len(pages), "content": pages}
