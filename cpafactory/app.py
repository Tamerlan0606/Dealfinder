import os, re, sqlite3, json, urllib.request, urllib.parse, zipfile, io, html, threading, time
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, Response
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="CPA Factory")
ADMIN_TOKEN = os.environ.get("CPA_ADMIN_TOKEN", "")
print("ADMITAD_CONFIGURED=" + str(bool(os.getenv("ADMITAD_CLIENT_ID") and os.getenv("ADMITAD_CLIENT_SECRET"))), flush=True)

def require_admin(x_admin_token: str | None):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "CPA_ADMIN_TOKEN не настроен")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Требуется токен администратора")

class SQLiteConn:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
    def execute(self, sql, params=()):
        return self.conn.execute(sql.replace("%s", "?"), params)
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()

def db():
    url = os.environ.get("DATABASE_URL", "")
    if (not url or url.startswith("${{")) and os.getenv("CPA_ALLOW_SQLITE", "0").lower() not in {"1","true","yes"}:
        raise RuntimeError("DATABASE_URL is required in production; SQLite fallback is disabled")
    if not url or url.startswith("${{"):
        return SQLiteConn("/tmp/cpafactory.db")
    return psycopg.connect(url, row_factory=dict_row)

def using_sqlite():
    url = os.environ.get("DATABASE_URL", "")
    return (not url) or url.startswith("${{")

def init():
    with db() as c:
        if using_sqlite():
            c.execute("""create table if not exists offers(
              id integer primary key autoincrement, name text not null, merchant text, price real,
              commission real, tracking_url text, traffic_rules text,
              active integer default 1, created_at text default CURRENT_TIMESTAMP
            )""")
            c.execute("""create table if not exists content(
              id integer primary key autoincrement, offer_id integer references offers(id), title text,
              script text, platform text default 'rutube', status text default 'draft',
              views integer default 0, clicks integer default 0, conversions integer default 0,
              approved_commission real default 0, created_at text default CURRENT_TIMESTAMP
            )""")
            c.execute("""create table if not exists click_events(
              id integer primary key autoincrement, offer_id integer references offers(id),
              content_id integer references content(id), subid text, created_at text default CURRENT_TIMESTAMP
            )""")
        else:
            c.execute("""create table if not exists offers(
              id serial primary key, name text not null, merchant text, price numeric,
              commission numeric, tracking_url text, traffic_rules text,
              active boolean default true, created_at timestamptz default now()
            )""")
            c.execute("""create table if not exists content(
              id serial primary key, offer_id int references offers(id), title text,
              script text, platform text default 'rutube', status text default 'draft',
              views bigint default 0, clicks bigint default 0, conversions bigint default 0,
              approved_commission numeric default 0, created_at timestamptz default now()
            )""")
            c.execute("""create table if not exists click_events(
              id bigserial primary key, offer_id int references offers(id),
              content_id int references content(id), subid text, created_at timestamptz default now()
            )""")
        c.execute("create index if not exists idx_click_offer on click_events(offer_id)")
        c.execute("create index if not exists idx_click_content on click_events(content_id)")
        if using_sqlite():
            c.execute("""create table if not exists publish_queue(
              id integer primary key autoincrement, content_id integer references content(id),
              scheduled_at text, status text default 'queued', rutube_url text,
              published_at text, created_at text default CURRENT_TIMESTAMP
            )""")
            c.execute("""create table if not exists revenue_events(
              id integer primary key autoincrement, offer_id integer references offers(id),
              content_id integer references content(id), subid text, event_type text,
              amount real default 0, status text default 'approved',
              event_at text default CURRENT_TIMESTAMP
            )""")
        else:
            c.execute("""create table if not exists publish_queue(
              id serial primary key, content_id int references content(id),
              scheduled_at timestamptz, status text default 'queued', rutube_url text,
              published_at timestamptz, created_at timestamptz default now()
            )""")
            c.execute("""create table if not exists revenue_events(
              id bigserial primary key, offer_id int references offers(id),
              content_id int references content(id), subid text, event_type text,
              amount numeric default 0, status text default 'approved',
              event_at timestamptz default now()
            )""")
        c.execute("create index if not exists idx_queue_status on publish_queue(status)")
        c.execute("create index if not exists idx_revenue_offer on revenue_events(offer_id)")
        if using_sqlite():
            c.execute("""create table if not exists pipeline_runs(
              id integer primary key autoincrement, status text, offer_id integer references offers(id),
              content_id integer references content(id), queue_id integer references publish_queue(id),
              message text, created_at text default CURRENT_TIMESTAMP
            )""")
        else:
            c.execute("""create table if not exists pipeline_runs(
              id bigserial primary key, status text, offer_id int references offers(id),
              content_id int references content(id), queue_id int references publish_queue(id),
              message text, created_at timestamptz default now()
            )""")
        c.execute("create index if not exists idx_pipeline_runs_created on pipeline_runs(created_at)")
        if using_sqlite():
            for stmt in [
                "alter table offers add column source text",
                "alter table offers add column external_id text",
                "alter table offers add column rating real default 0",
                "alter table offers add column epc real default 0",
                "alter table offers add column cr real default 0",
                "alter table offers add column cpa_rate text",
                "alter table offers add column site_url text",
                "alter table offers add column image_url text",
                "alter table offers add column image_url2 text",
                "alter table content add column description text",
                "alter table content add column hook text",
                "alter table content add column cta text",
                "alter table content add column scenes text",
                "alter table content add column thumbnail_prompt text"
            ]:
                try: c.execute(stmt)
                except Exception: pass
        else:
            c.execute("alter table offers add column if not exists source text")
            c.execute("alter table offers add column if not exists external_id text")
            c.execute("alter table offers add column if not exists rating numeric default 0")
            c.execute("alter table offers add column if not exists epc numeric default 0")
            c.execute("alter table offers add column if not exists cr numeric default 0")
            c.execute("alter table offers add column if not exists cpa_rate text")
            c.execute("alter table offers add column if not exists site_url text")
            c.execute("alter table offers add column if not exists image_url text")
            c.execute("alter table offers add column if not exists image_url2 text")
            c.execute("alter table content add column if not exists description text")
            c.execute("alter table content add column if not exists hook text")
            c.execute("alter table content add column if not exists cta text")
            c.execute("alter table content add column if not exists scenes text")
            c.execute("alter table content add column if not exists thumbnail_prompt text")
        c.execute("create unique index if not exists uq_offers_source_external on offers(source,external_id) where external_id is not null")
        # CPA distribution engine schema (media, landing, channel plans, conversion tracking)
        distribution_alters = [
            ("offers","description","text"),
            ("offers","category","text"),
            ("offers","old_price","real default 0"),
            ("offers","discount","text"),
            ("offers","media_checked_at","text"),
            ("offers","media_type","text"),
            ("offers","traffic_allowed","text"),
            ("content","media_url","text"),
            ("content","media_type","text"),
            ("content","landing_slug","text"),
            ("content","variants_json","text"),
            ("content","source_text","text"),
        ]
        for table, column, ddl in distribution_alters:
            stmt = f"alter table {table} add column {'if not exists ' if not using_sqlite() else ''}{column} {ddl}"
            if using_sqlite():
                try:
                    c.execute(stmt)
                except Exception:
                    pass
            else:
                c.execute(stmt)
        if using_sqlite():
            c.execute("""create table if not exists distribution_queue(
              id integer primary key autoincrement, content_id integer references content(id),
              channel text not null, status text default 'planned', external_id text,
              external_url text, scheduled_at text, last_error text,
              created_at text default CURRENT_TIMESTAMP, published_at text
            )""")
        else:
            c.execute("""create table if not exists distribution_queue(
              id bigserial primary key, content_id int references content(id),
              channel text not null, status text default 'planned', external_id text,
              external_url text, scheduled_at timestamptz, last_error text,
              created_at timestamptz default now(), published_at timestamptz
            )""")
        c.execute("create index if not exists idx_distribution_status on distribution_queue(status)")
        c.execute("create index if not exists idx_distribution_content on distribution_queue(content_id)")
        c.execute("create unique index if not exists uq_distribution_content_channel on distribution_queue(content_id,channel)")


_AUTOPILOT_LOCK = threading.Lock()
_AUTOPILOT_INTERVAL = max(900, int(os.getenv("CPA_AUTOPILOT_INTERVAL", "3600") or 3600))

def _autopilot_cycle():
    try:
        print("CPA_AUTOPILOT_CYCLE_START", flush=True)
        result = _pipeline_run()
        print("CPA_AUTOPILOT", json.dumps(result, ensure_ascii=False, default=str), flush=True)
        # Publish any newly planned Telegram item in the same autopilot cycle.
        # Import lazily so optional production integrations can finish loading first.
        try:
            import enhancements
            tg = enhancements.publish_telegram(int(os.getenv("TELEGRAM_PUBLISH_BATCH", "1") or 1))
            print("CPA_TELEGRAM_AFTER_PIPELINE", json.dumps(tg, ensure_ascii=False, default=str), flush=True)
        except Exception as tg_error:
            print("CPA_TELEGRAM_AFTER_PIPELINE_ERROR", type(tg_error).__name__, str(tg_error), flush=True)
        return result
    except Exception as e:
        print("CPA_AUTOPILOT_ERROR", type(e).__name__, str(e), flush=True)
        return {"status":"error","error":f"{type(e).__name__}: {e}"}

def _autopilot_loop():
    import time
    print("CPA_AUTOPILOT_STARTED", json.dumps({"interval_seconds": _AUTOPILOT_INTERVAL}, ensure_ascii=False), flush=True)
    while True:
        if _AUTOPILOT_LOCK.acquire(blocking=False):
            try:
                _autopilot_cycle()
            finally:
                _AUTOPILOT_LOCK.release()
        time.sleep(_AUTOPILOT_INTERVAL)

def _sync_yandex_market_seller_offer():
    url=os.getenv("YANDEX_MARKET_SELLER_REFERRAL_URL","").strip()
    if os.getenv("YANDEX_MARKET_SELLER_ENABLED","0").lower() not in {"1","true","yes","on"} or not url:
        return
    payout=float(os.getenv("YANDEX_MARKET_SELLER_PAYOUT_RUB","15000") or 15000)
    promo=os.getenv("YANDEX_MARKET_SELLER_PROMOCODE","").strip()
    description="Яндекс Маркет для продавцов: вознаграждение за нового продавца после выполнения условий программы."
    with db() as c:
        row=c.execute("select id from offers where source=%s and external_id=%s",("yandex_market_seller","seller_referral")).fetchone()
        if row:
            c.execute("update offers set name=%s,merchant=%s,commission=%s,tracking_url=%s,site_url=%s,description=%s,cpa_rate=%s,active=true where id=%s",("Яндекс Маркет для продавцов","Яндекс Маркет",payout,url,url,description,f"{payout:g} RUB / approved seller",row["id"]))
        else:
            c.execute("insert into offers(name,merchant,commission,tracking_url,site_url,description,cpa_rate,source,external_id,active) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",("Яндекс Маркет для продавцов","Яндекс Маркет",payout,url,url,description,f"{payout:g} RUB / approved seller","yandex_market_seller","seller_referral"))
    print("CPA_YANDEX_MARKET_SELLER_SYNCED",json.dumps({"payout":payout,"promocode":promo},ensure_ascii=False),flush=True)

@app.on_event("startup")
def startup():
    init()
    try:
        _sync_yandex_market_seller_offer()
    except Exception as e:
        print("CPA_YANDEX_MARKET_SELLER_SYNC_ERROR",type(e).__name__,str(e),flush=True)
    try:
        import enhancements
        enhancements.migrate()
    except Exception as e:
        print("CPA_ENHANCEMENTS_MIGRATION_ERROR", type(e).__name__, str(e), flush=True)
    print("CPA_FACTORY_MODE", json.dumps({"mode":"distribution_engine","video_generation":"removed","tts":"removed","media_source":"advertiser_original"}, ensure_ascii=False), flush=True)
    if os.getenv("CPA_AUTOPILOT_ENABLED", "1").strip().lower() not in {"0","false","no","off"}:
        threading.Thread(target=_autopilot_loop, daemon=True, name="cpa-autopilot").start()


@app.get("/health")
def health():
    return {"ok": True, "service": "cpa-factory", "admitad_configured": bool(os.getenv("ADMITAD_CLIENT_ID") and os.getenv("ADMITAD_CLIENT_SECRET"))}

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(PAGE)

def add_tracking(url: str, subid: str) -> str:
    if not url: return ""
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q["subid"] = subid
    return urlunparse(p._replace(query=urlencode(q)))

@app.get("/go/{offer_id}")
def go(offer_id: int, content_id: int = 0, source: str = "direct", channel: str = "unknown"):
    safe_source = re.sub(r"[^a-zA-Z0-9_-]", "", str(source))[:24] or "direct"
    safe_channel = re.sub(r"[^a-zA-Z0-9_-]", "", str(channel))[:24] or "unknown"
    with db() as c:
        offer = c.execute("select * from offers where id=%s and active=true", (offer_id,)).fetchone()
        if not offer or not offer["tracking_url"]:
            raise HTTPException(404, "Оффер не найден")
        subid = f"cf_{offer_id}_{content_id or 0}_{safe_source}_{safe_channel}"
        c.execute("insert into click_events(offer_id,content_id,subid) values(%s,%s,%s)",
                  (offer_id, content_id or None, subid))
        c.execute("update content set clicks=clicks+1 where id=%s", (content_id,)) if content_id else None
    return RedirectResponse(add_tracking(offer["tracking_url"], subid), status_code=302)

@app.get("/r/{content_id}")
def tracked_redirect(content_id:int, source:str="direct", channel:str="unknown"):
    with db() as c:
        row=c.execute("select c.id,c.offer_id,o.tracking_url,o.active from content c join offers o on o.id=c.offer_id where c.id=%s",(content_id,)).fetchone()
        if not row or not row["active"] or not row["tracking_url"]: raise HTTPException(404,"Материал не найден")
        subid=f"cf_{content_id}_{re.sub(r'[^a-zA-Z0-9_-]','',str(source))[:30]}_{re.sub(r'[^a-zA-Z0-9_-]','',str(channel))[:30]}"
        c.execute("insert into click_events(offer_id,content_id,subid) values(%s,%s,%s)",(row["offer_id"],content_id,subid))
        c.execute("update content set clicks=clicks+1 where id=%s",(content_id,))
    return RedirectResponse(add_tracking(row["tracking_url"],subid),status_code=302)

@app.get("/api/offers")
def offers():
    with db() as c:
        return c.execute("""select o.*, count(e.id) clicks
          from offers o left join click_events e on e.offer_id=o.id
          group by o.id order by o.id desc""").fetchall()

_ADMITAD_TOKEN_CACHE={"token":"","expires_at":0.0}

def _admitad_basic_header():
    raw=os.getenv("ADMITAD_BASE64_HEADER","").strip()
    if raw:
        return raw[6:].strip() if raw.lower().startswith("basic ") else raw
    cid=os.getenv("ADMITAD_CLIENT_ID","").strip()
    secret=os.getenv("ADMITAD_CLIENT_SECRET","").strip()
    if not cid or not secret:
        return ""
    import base64
    return base64.b64encode(f"{cid}:{secret}".encode()).decode()

def _admitad_access_token(force=False):
    now=time.time()
    cached=_ADMITAD_TOKEN_CACHE
    if not force and cached["token"] and cached["expires_at"] > now+120:
        return cached["token"]
    # Backward compatibility: an explicitly supplied bearer token still works.
    static=os.getenv("ADMITAD_ACCESS_TOKEN","").strip()
    if static and not os.getenv("ADMITAD_CLIENT_ID","").strip():
        return static
    cid=os.getenv("ADMITAD_CLIENT_ID","").strip()
    basic=_admitad_basic_header()
    if not cid or not basic:
        return ""
    scopes=os.getenv("ADMITAD_SCOPES","advcampaigns advcampaigns_for_website websites statistics deeplink_generator").strip()
    body=urllib.parse.urlencode({"grant_type":"client_credentials","client_id":cid,"scope":scopes}).encode()
    req=urllib.request.Request("https://api.admitad.com/token/",data=body,method="POST",headers={
        "Authorization":f"Basic {basic}",
        "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8",
        "Accept":"application/json",
        "User-Agent":"CPAFactory/2.1",
    })
    with urllib.request.urlopen(req,timeout=25) as r:
        data=json.loads(r.read().decode("utf-8"))
    token=str(data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError(f"Admitad token response has no access_token: {str(data)[:300]}")
    expires=max(300,int(data.get("expires_in") or 3600))
    cached["token"]=token; cached["expires_at"]=now+expires
    return token

def _admitad_get(url: str, token: str | None = None):
    token=(token or _admitad_access_token()).strip()
    if not token:
        raise RuntimeError("Admitad credentials are not configured")
    last=None
    for attempt in range(3):
        req=urllib.request.Request(url, headers={"Authorization":f"Bearer {token}","Accept":"application/json","User-Agent":"CPAFactory/2.2"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last=e
            if e.code == 401 and token == _ADMITAD_TOKEN_CACHE.get("token"):
                token=_admitad_access_token(force=True)
                continue
            raise
        except urllib.error.URLError as e:
            last=e
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last or RuntimeError("Admitad request failed")

def _admitad_website(token: str | None = None):
    configured=os.getenv("ADMITAD_WEBSITE_ID","").strip()
    token=token or _admitad_access_token()
    data=_admitad_get("https://api.admitad.com/websites/v2/",token)
    items=data.get("results",[]) if isinstance(data,dict) else data
    items=items or []
    if configured:
        for x in items:
            if str(x.get("id")) == configured:
                return x
        return {"id":configured,"name":"configured","status":"unknown"}
    target=os.getenv("ADMITAD_WEBSITE_MATCH","CPAFactory").lower()
    candidates=[]
    for x in items:
        hay=" ".join(str(x.get(k) or "") for k in ("name","site_url","url")).lower()
        if "cpafactory" in hay or "t.me/cpafactory" in hay or target in hay:
            candidates.append(x)
    if not candidates:
        candidates=[x for x in items if str(x.get("status") or "").lower()=="active"] or list(items)
    if not candidates:
        raise RuntimeError("Admitad returned no publisher ad spaces")
    candidates.sort(key=lambda x:(str(x.get("status") or "").lower()=="active", bool(x.get("validation_passed")), int(x.get("id") or 0)), reverse=True)
    return candidates[0]

def _admitad_configured():
    return bool((os.getenv("ADMITAD_CLIENT_ID") and (os.getenv("ADMITAD_CLIENT_SECRET") or os.getenv("ADMITAD_BASE64_HEADER"))) or os.getenv("ADMITAD_ACCESS_TOKEN"))

def _gdeslon_get(url: str, token: str):
    # Bound both socket latency and response size; an oversized feed must not
    # block the production content pipeline.
    req=urllib.request.Request(url, headers={"Accept":"application/xml,text/xml","User-Agent":"CPAFactory/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data=r.read(8*1024*1024)
    if len(data) >= 8*1024*1024:
        raise RuntimeError("GdeSlon XML response exceeded 8 MB; reduce GDESLON_LIMIT")
    return data.decode("utf-8")

def _gdeslon_parse_xml(raw: str):
    import xml.etree.ElementTree as ET
    root=ET.fromstring(raw)
    items=[]
    for node in root.iter():
        if node.tag.split("}")[-1].lower() != "offer":
            continue
        def child(name):
            for ch in list(node):
                if ch.tag.split("}")[-1].lower() == name.lower():
                    return (ch.text or "").strip()
            return ""
        attrs=dict(node.attrib)
        oid=attrs.get("id") or child("id") or child("offer_id")
        name=child("name") or child("title")
        link=child("url") or child("link")
        image=child("picture") or child("image") or child("image_url") or child("imageLink")
        price=child("price")
        vendor=child("vendor") or child("brand")
        desc=child("description")
        category=child("categoryId") or child("category_id")
        if oid and name and link:
            items.append({"id":oid,"name":name,"url":link,"price":price,"vendor":vendor,
                          "description":desc,"category_id":category,"image_url":image,"raw":attrs})
    return items

def _first_rate(v):
    if v is None: return ""
    if isinstance(v,(int,float)): return str(v)
    if isinstance(v,dict):
        for x in v.values():
            z=_first_rate(x)
            if z: return z
    if isinstance(v,list):
        for x in v:
            z=_first_rate(x)
            if z: return z
    m=re.search(r"(\d+(?:[.,]\d+)?)\s*%?",str(v))
    return m.group(1).replace(",",".") if m else str(v)[:120]

@app.get("/api/cpa/import")
def cpa_import(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    if not _admitad_configured():
        return {"status":"not_configured","message":"Нужны ADMITAD_CLIENT_ID и ADMITAD_CLIENT_SECRET/ADMITAD_BASE64_HEADER"}
    try:
        token=_admitad_access_token()
        website_obj=_admitad_website(token)
        website=str(website_obj.get("id") or "").strip()
        if not website:
            raise RuntimeError("Не удалось определить Admitad website id")
        url=f"https://api.admitad.com/advcampaigns/website/{urllib.parse.quote(website,safe='')}/?limit=100&connection_status=active&language=en"
        data=_admitad_get(url,token)
    except Exception as e:
        raise HTTPException(502,f"Admitad API: {e}")
    items=data.get("results",[]) if isinstance(data,dict) else data
    added=updated=skipped=0
    programs=[]
    with db() as c:
        for v in items:
            if str(v.get("connection_status","active"))!="active": continue
            cid=v.get("id"); name=v.get("name"); gotolink=v.get("gotolink")
            if not cid or not name or not gotolink:
                skipped+=1; continue
            if len(programs) < 10:
                programs.append({"id":cid,"name":name,"regions":[x.get("region") for x in (v.get("regions") or []) if x.get("region")],"traffics":[{"id":x.get("id"),"name":x.get("name"),"enabled":x.get("enabled")} for x in (v.get("traffics") or [])],"epc":v.get("epc"),"cr":v.get("cr")})
            rules=json.dumps({"regions":v.get("regions") or [],"traffics":v.get("traffics") or [],"moderation":v.get("moderation"),"action_countries":v.get("action_countries")},ensure_ascii=False)
            rating=float(v.get("rating") or 0); epc=float(v.get("epc") or 0); cr=float(v.get("cr") or 0)
            rate=_first_rate(v.get("action_ranges"))
            existing=c.execute("select id from offers where source='admitad' and external_id=%s",(str(cid),)).fetchone()
            if existing:
                c.execute("""update offers set name=%s,merchant=%s,tracking_url=%s,traffic_rules=%s,rating=%s,epc=%s,cr=%s,cpa_rate=%s,site_url=%s,active=true where id=%s""",
                    (name,"Admitad",gotolink,rules,rating,epc,cr,rate,v.get("site_url"),existing["id"]))
                updated+=1
            else:
                c.execute("""insert into offers(name,merchant,price,commission,tracking_url,traffic_rules,active,source,external_id,rating,epc,cr,cpa_rate,site_url)
                    values(%s,%s,0,0,%s,%s,true,'admitad',%s,%s,%s,%s,%s,%s)""",
                    (name,"Admitad",gotolink,rules,str(cid),rating,epc,cr,rate,v.get("site_url")))
                added+=1
    return {"status":"ok","source":"admitad","received":len(items),"added":added,"updated":updated,"skipped":skipped,"programs":programs}

@app.get("/api/cpa/admitad/status")
def admitad_status():
    result={"configured":_admitad_configured(),"token_ok":False,"website":None,"active_programs":None}
    if not result["configured"]:
        return result
    try:
        token=_admitad_access_token()
        result["token_ok"]=bool(token)
        website=_admitad_website(token)
        result["website"]={k:website.get(k) for k in ("id","name","status","site_url","validation_passed","kind") if k in website}
        wid=str(website.get("id") or "")
        if wid:
            data=_admitad_get(f"https://api.admitad.com/advcampaigns/website/{urllib.parse.quote(wid,safe='')}/?limit=1&connection_status=active&language=ru",token)
            if isinstance(data,dict):
                result["active_programs"]=(data.get("_meta") or {}).get("count",len(data.get("results") or []))
            else:
                result["active_programs"]=len(data or [])
        return result
    except Exception as e:
        result["error"]=f"{type(e).__name__}: {e}"
        return result

def _admitad_sync_revenue():
    """Reconcile Admitad actions into the local revenue ledger idempotently."""
    if not _admitad_configured():
        return {"status":"not_configured"}
    token=_admitad_access_token()
    import datetime as _dt
    start=(_dt.datetime.utcnow()-_dt.timedelta(days=35)).strftime("%d.%m.%Y")
    end=_dt.datetime.utcnow().strftime("%d.%m.%Y")
    data=_admitad_get(f"https://api.admitad.com/statistics/actions/?limit=500&date_start={start}&date_end={end}",token)
    items=data.get("results",[]) if isinstance(data,dict) else (data or [])
    added=updated=skipped=0
    with db() as c:
        if using_sqlite():
            for stmt in ["alter table revenue_events add column source text","alter table revenue_events add column external_id text"]:
                try: c.execute(stmt)
                except Exception: pass
        else:
            c.execute("alter table revenue_events add column if not exists source text")
            c.execute("alter table revenue_events add column if not exists external_id text")
        c.execute("create unique index if not exists uq_revenue_source_external on revenue_events(source,external_id) where external_id is not null")
        for a in items:
            ext=str(a.get("id") or a.get("action_id") or "").strip()
            if not ext: skipped+=1; continue
            campaign=str(a.get("advcampaign_id") or a.get("campaign_id") or a.get("campaign") or "").strip()
            offer=c.execute("select id from offers where source='admitad' and external_id=%s",(campaign,)).fetchone() if campaign else None
            if not offer: skipped+=1; continue
            subid=str(a.get("subid") or "").strip()
            content_id=None
            m=re.match(r"^cf_\\d+_(\\d+)_",subid)
            if m and int(m.group(1) or 0)>0: content_id=int(m.group(1))
            status_map={"approved":"approved","pending":"open","open":"open","declined":"declined"}
            status=status_map.get(str(a.get("status") or "").lower(),str(a.get("status") or "open").lower())
            amount=0.0
            for key in ("payment","payment_sum","payment_sum_approved","cart","commission"):
                try:
                    if a.get(key) not in (None,""): amount=float(a.get(key)); break
                except Exception: pass
            event_type=str(a.get("action_type") or a.get("type") or "action")
            existing=c.execute("select id from revenue_events where source='admitad' and external_id=%s",(ext,)).fetchone()
            if existing:
                c.execute("update revenue_events set offer_id=%s,content_id=%s,subid=%s,event_type=%s,amount=%s,status=%s where id=%s",
                          (int(offer["id"]),content_id,subid,event_type,amount,status,existing["id"]))
                updated+=1
            else:
                c.execute("insert into revenue_events(offer_id,content_id,subid,event_type,amount,status,source,external_id) values(%s,%s,%s,%s,%s,%s,'admitad',%s)",
                          (int(offer["id"]),content_id,subid,event_type,amount,status,ext))
                added+=1
    return {"status":"ok","received":len(items),"added":added,"updated":updated,"skipped":skipped}

@app.get("/api/cpa/import/gdeslon")
def cpa_import_gdeslon(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    token=os.getenv("GDESLON_API_TOKEN","").strip()
    if not token:
        return {"status":"not_configured","message":"Нужен GDESLON_API_TOKEN"}
    query=os.getenv("GDESLON_QUERY","").strip()
    limit=max(1,min(int(os.getenv("GDESLON_LIMIT","20") or 20),20))
    page=max(1,int(os.getenv("GDESLON_PAGE","1") or 1))
    params={"q":query,"l":str(limit),"p":str(page),"_gs_at":token}
    url="https://www.gdeslon.ru/api/search.xml?"+urllib.parse.urlencode(params)
    try:
        raw=_gdeslon_get(url,token)
        items=_gdeslon_parse_xml(raw)
    except Exception as e:
        raise HTTPException(502,f"GdeSlon XML API: {e}")
    added=updated=skipped=0
    with db() as c:
        for v in items:
            oid=v["id"]; name=v["name"]; link=v["url"]
            price=0.0
            try: price=float(str(v.get("price") or "0").replace(" ","").replace(",","."))
            except Exception: pass
            rules=json.dumps({
                "source":"gdeslon","vendor":v.get("vendor"),"category_id":v.get("category_id"),
                "description":v.get("description"),"raw":v.get("raw")
            },ensure_ascii=False)[:12000]
            existing=c.execute("select id from offers where source='gdeslon' and external_id=%s",(str(oid),)).fetchone()
            if existing:
                c.execute("""update offers set name=%s,merchant=%s,price=%s,tracking_url=%s,traffic_rules=%s,
                  active=true,site_url=%s,image_url=%s,description=%s,category=%s where id=%s""",
                  (name,"Где Слон?",price,link,rules,link,v.get("image_url"),v.get("description") or "",v.get("category_id") or "",existing["id"]))
                updated+=1
            else:
                img_url=v.get("image_url") or ""
                c.execute("""insert into offers(name,merchant,price,commission,tracking_url,traffic_rules,active,source,external_id,rating,epc,cr,cpa_rate,site_url,image_url,description,category)
                    values(%s,%s,%s,0,%s,%s,true,'gdeslon',%s,0,0,0,'',%s,%s,%s,%s)""",
                    (name,"Где Слон?",price,link,rules,str(oid),link,img_url,v.get("description") or "",v.get("category_id") or ""))
                added+=1
    return {"status":"ok","source":"gdeslon","api":"xml","received":len(items),"added":added,"updated":updated,"skipped":skipped,"query":query,"page":page,"limit":limit}

@app.get("/api/cpa/diagnostic")
def cpa_diagnostic(token: str | None = None):
    expected=os.getenv("CPA_CRON_TOKEN","").strip()
    if not expected or token != expected:
        raise HTTPException(401,"Недействительный диагностический токен")
    gs_token=os.getenv("GDESLON_API_TOKEN","").strip()
    result={"gdeslon_configured":bool(gs_token),"gdeslon_reachable":False,"received":0,"sample_names":[]}
    if not gs_token:
        result["error"]="GDESLON_API_TOKEN не задан"
        return result
    query=os.getenv("GDESLON_QUERY","").strip()
    limit=max(1,min(int(os.getenv("GDESLON_LIMIT","10") or 10),10))
    page=max(1,int(os.getenv("GDESLON_PAGE","1") or 1))
    params={"q":query,"l":str(limit),"p":str(page),"_gs_at":gs_token}
    url="https://www.gdeslon.ru/api/search.xml?"+urllib.parse.urlencode(params)
    try:
        raw=_gdeslon_get(url,gs_token)
        items=_gdeslon_parse_xml(raw)
        result["gdeslon_reachable"]=True
        result["received"]=len(items)
        result["sample_names"]=[str(x["name"])[:120] for x in items[:3]]
    except Exception as e:
        result["error"]=f"{type(e).__name__}: {e}"
    return result

def _auto_gdeslon_import():
    try:
        result = cpa_import_gdeslon(ADMIN_TOKEN or None)
        print("GDESLON_AUTO_IMPORT", json.dumps(result, ensure_ascii=False, default=str))
    except Exception as e:
        print("GDESLON_AUTO_IMPORT_ERROR", type(e).__name__, str(e))

def _count_active_offers():
    with db() as c:
        return c.execute("select count(*) n from offers where active=true").fetchone()["n"]

@app.get("/api/cpa/status")
def cpa_status():
    return {
        "admitad_configured":_admitad_configured(),
        "gdeslon_configured":bool(os.getenv("GDESLON_API_TOKEN")),
        "active_offers": int(_count_active_offers())
    }

@app.get("/api/cpa/top")
def cpa_top(limit: int = 10):
    limit=max(1,min(limit,50))
    with db() as c:
        rows=c.execute("""select o.*, count(e.id) clicks
          from offers o left join click_events e on e.offer_id=o.id
          where o.active=true
          group by o.id""").fetchall()
    out=[]
    for r in rows:
        epc=float(r["epc"] or 0)
        cr=float(r["cr"] or 0)
        rating=float(r["rating"] or 0)
        clicks=int(r["clicks"] or 0)
        price=float(r["price"] or 0)
        score=(__import__("math").log1p(max(epc,0))*0.55
               + min(max(cr,0),100)*0.30
               + min(max(rating,0),5)*0.15
               + min(clicks,1000)*0.002
               + (0.001 if price > 0 else 0))
        x=dict(r)
        x["score"]=round(score,4)
        out.append(x)
    out.sort(key=lambda x:(x["score"],float(x.get("epc") or 0),float(x.get("cr") or 0),int(x.get("clicks") or 0),int(x.get("id") or 0)),reverse=True)
    return out[:limit]

@app.get("/api/cpa/cron-import-gdeslon")
def cpa_cron_import_gdeslon(x_cron_token: str | None = Header(default=None)):
    expected=os.getenv("CPA_CRON_TOKEN","").strip()
    if not expected or x_cron_token != expected:
        raise HTTPException(401,"Недействительный cron-токен")
    return cpa_import_gdeslon(ADMIN_TOKEN)

@app.get("/api/cpa/cron-import")
def cpa_cron_import(x_cron_token: str | None = Header(default=None)):
    expected=os.getenv("CPA_CRON_TOKEN","").strip()
    if not expected or x_cron_token != expected:
        raise HTTPException(401,"Недействительный cron-токен")
    return cpa_import(ADMIN_TOKEN)


@app.get("/api/pipeline/status")
def pipeline_status():
    with db() as c:
        active = c.execute("select count(*) n from offers where active=true").fetchone()["n"]
        queued = c.execute("select count(*) n from publish_queue where status='queued'").fetchone()["n"]
        last = c.execute("""select p.*, o.name offer_name, c.title
          from pipeline_runs p
          left join offers o on o.id=p.offer_id
          left join content c on c.id=p.content_id
          order by p.id desc limit 1""").fetchone()
    top = cpa_top(1)
    return {
        "admitad_configured": _admitad_configured(),
        "gdeslon_configured": bool(os.getenv("GDESLON_API_TOKEN")),
        "active_offers": active, "queued": queued,
        "top_offer": dict(top[0]) if top else None,
        "last_run": dict(last) if last else None
    }

def _pipeline_run():
    try:
        import enhancements
        print("CPA_PIPELINE_STAGE", json.dumps({"stage":"start"}, ensure_ascii=False), flush=True)
        # Refresh inventory when possible; failures must not destroy an existing inventory.
        imported=[]
        if os.getenv("GDESLON_API_TOKEN","").strip():
            try:
                imported.append(cpa_import_gdeslon(ADMIN_TOKEN))
            except Exception as e:
                print("CPA_GDESLON_REFRESH_ERROR", type(e).__name__, str(e), flush=True)
                imported.append({"source":"gdeslon","status":"refresh_error","error":f"{type(e).__name__}: {e}"})
        if _admitad_configured():
            try:
                admitad_result=cpa_import(ADMIN_TOKEN)
                imported.append(admitad_result)
                print("CPA_ADMITAD_OFFER_SYNC", json.dumps(admitad_result,ensure_ascii=False,default=str), flush=True)
                try:
                    rev=_admitad_sync_revenue()
                    print("CPA_ADMITAD_REVENUE_SYNC", json.dumps(rev,ensure_ascii=False,default=str), flush=True)
                except Exception as rev_error:
                    print("CPA_ADMITAD_REVENUE_ERROR", type(rev_error).__name__, str(rev_error), flush=True)
            except Exception as e:
                print("CPA_ADMITAD_REFRESH_ERROR", type(e).__name__, str(e), flush=True)
                imported.append({"source":"admitad","status":"refresh_error","error":f"{type(e).__name__}: {e}"})
        with db() as c:
            active=int(c.execute("select count(*) n from offers where active=true").fetchone()["n"])
        if active == 0:
            msg="Нет активных офферов после импорта"
            with db() as c: c.execute("insert into pipeline_runs(status,message) values(%s,%s)",("empty",msg))
            return {"status":"empty","message":msg,"imports":imported}
        top=enhancements.distribution_top(1)
        if not top:
            msg="Нет офферов с допустимым рекламным материалом"
            with db() as c: c.execute("insert into pipeline_runs(status,message) values(%s,%s)",("empty",msg))
            return {"status":"empty","message":msg}
        o=top[0]; offer_id=int(o["id"]); name=str(o["name"] or "товар"); price=float(o["price"] or 0)
        media_url=str(o.get("video_url") or o.get("image_url") or "")
        seller_referral=(str(o.get("source") or "")=="yandex_market_seller")
        media_type="video" if o.get("video_url") else ("image" if o.get("image_url") else ("text" if seller_referral else ""))
        if not media_url and not seller_referral:
            return {"status":"skipped","offer_id":offer_id,"message":"Нет рекламного видео или фото"}
        with db() as c:
            if using_sqlite(): recent=c.execute("select id from content where offer_id=%s and created_at > datetime('now','-24 hours') limit 1",(offer_id,)).fetchone()
            else: recent=c.execute("select id from content where offer_id=%s and created_at > now()-interval '24 hours' limit 1",(offer_id,)).fetchone()
            if recent:
                enhancements.ensure_distribution_plan(int(recent["id"]))
                return {"status":"skipped","offer_id":offer_id,"content_id":int(recent["id"]),"message":"Свежая карточка уже существует"}
            price_label=f"{price:g} ₽" if price else "актуальная цена на странице продавца"
            title=f"{name} — актуальная цена и условия покупки"
            script=(f"{name}. {price_label}. Проверяйте характеристики, комплектацию, наличие и актуальную цену у продавца перед заказом. "
                    f"Рекламные материалы предоставлены рекламодателем.")
            row=c.execute("""insert into content(offer_id,title,script,platform,status,media_url,media_type,source_text)
              values(%s,%s,%s,'multi','ready',%s,%s,%s) returning *""",(offer_id,title,script,media_url,media_type,str(o.get("description") or ""))).fetchone()
            content_id=int(row["id"])
            c.execute("insert into publish_queue(content_id,scheduled_at,status) values(%s,null,'queued')",(content_id,))
            c.execute("insert into pipeline_runs(status,offer_id,content_id,message) values(%s,%s,%s,%s)",("ok",offer_id,content_id,"Создана CPA-карточка с рекламным материалом и планом распространения"))
        variants=enhancements.build_variants(content_id)
        planned=enhancements.ensure_distribution_plan(content_id)
        return {"status":"ok","offer_id":offer_id,"content_id":content_id,"media_type":media_type,"variants":len(variants),"planned_channels":planned}
    except Exception as e:
        try:
            with db() as c: c.execute("insert into pipeline_runs(status,message) values(%s,%s)",("error",f"{type(e).__name__}: {e}"))
        except Exception: pass
        raise HTTPException(500,f"Pipeline: {e}")

@app.post("/api/pipeline/run")
def pipeline_run(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    return _pipeline_run()

@app.post("/api/pipeline/cron")
def pipeline_cron(x_cron_token: str | None = Header(default=None)):
    expected=os.getenv("CPA_CRON_TOKEN","").strip()
    if not expected or x_cron_token != expected:
        raise HTTPException(401,"Недействительный cron-токен")
    return _pipeline_run()

@app.post("/api/offers")
async def add_offer(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json()
    if not x.get("name"): raise HTTPException(400, "name обязателен")
    with db() as c:
        return c.execute("""insert into offers(name,merchant,price,commission,tracking_url,traffic_rules)
          values(%s,%s,%s,%s,%s,%s) returning *""",
          (x.get("name"),x.get("merchant"),x.get("price") or 0,x.get("commission") or 0,
           x.get("tracking_url"),x.get("traffic_rules"))).fetchone()

@app.post("/api/offers/import")
async def import_offers(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json()
    items=x if isinstance(x,list) else x.get("offers",[])
    added=0
    with db() as c:
        for v in items:
            if not v.get("name") or not v.get("tracking_url"): continue
            c.execute("""insert into offers(name,merchant,price,commission,tracking_url,traffic_rules)
              values(%s,%s,%s,%s,%s,%s)""",
              (v.get("name"),v.get("merchant"),v.get("price") or 0,v.get("commission") or 0,
               v.get("tracking_url"),v.get("traffic_rules")))
            added += 1
    return {"added":added}

def build_content_pack(row, offer):
    name=str(offer["name"] or "товар")
    price=float(offer["price"] or 0)
    price_label=f"{price:g} ₽" if price else "цена уточняется"
    rate=offer["cpa_rate"] or ""
    rate_text=f"{rate}%" if rate and "%" not in str(rate) else str(rate)
    link=f"/go/{offer['id']}?content_id={row['id']}"
    description=(f"{name}. {price_label}.\\n\\n"
                 f"Проверьте характеристики, комплектацию, наличие и актуальные условия у продавца.\\n\\n"
                 f"Партнёрская ставка: {rate_text or 'уточняется'}.\\n"
                 f"Партнёрская ссылка: {link}")
    return {"content_id":int(row["id"]),"offer_id":int(offer["id"]),"title":row["title"],
            "media_url":offer.get("video_url") or offer.get("image_url") or "",
            "media_type":"video" if offer.get("video_url") else ("image" if offer.get("image_url") else ""),
            "variants":json.loads(row.get("variants_json") or "{}") if row.get("variants_json") else {},
            "description":description,"tracking_link":link,"platform":row["platform"]}

def _make_pack_zip(content_id,row,offer):
    pack=build_content_pack(row,offer)
    z=io.BytesIO()
    with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as zz:
        zz.writestr("description.txt",pack["description"])
        zz.writestr("variants.json",json.dumps(pack.get("variants",{}),ensure_ascii=False,indent=2))
        zz.writestr("media_url.txt",str(pack.get("media_url") or ""))
        zz.writestr("tracking_link.txt",str(pack.get("tracking_link") or ""))
    z.seek(0)
    return z

@app.get("/api/content/{content_id}/zip")
def content_zip(content_id:int):
    with db() as c:
        row=c.execute("select * from content where id=%s",(content_id,)).fetchone()
        if not row: raise HTTPException(404,"Материал не найден")
        offer=c.execute("select * from offers where id=%s",(row["offer_id"],)).fetchone()
        if not offer: raise HTTPException(404,"Оффер не найден")
    z=_make_pack_zip(content_id,row,offer)
    return StreamingResponse(z,media_type="application/zip",headers={"Content-Disposition":f'attachment; filename="rutube_pack_{content_id}.zip"'})

@app.get("/api/content/{content_id}/pack")
def content_pack(content_id:int):
    with db() as c:
        row=c.execute("select * from content where id=%s",(content_id,)).fetchone()
        if not row: raise HTTPException(404,"Материал не найден")
        offer=c.execute("select * from offers where id=%s",(row["offer_id"],)).fetchone()
        if not offer: raise HTTPException(404,"Оффер не найден")
    return build_content_pack(row,offer)

@app.get("/api/content")
def content():
    with db() as c:
        return c.execute("""select content.*, offers.name offer_name
          from content left join offers on offers.id=content.offer_id order by content.id desc""").fetchall()

@app.post("/api/content")
async def add_content(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json()
    with db() as c:
        return c.execute("""insert into content(offer_id,title,script,platform,status)
          values(%s,%s,%s,%s,%s) returning *""",
          (x.get("offer_id"),x.get("title"),x.get("script"),x.get("platform","rutube"),x.get("status","draft"))).fetchone()

@app.post("/api/content/generate")
async def generate_content(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json(); offer_id=int(x["offer_id"])
    with db() as c:
        o=c.execute("select * from offers where id=%s",(offer_id,)).fetchone()
        if not o: raise HTTPException(404,"Оффер не найден")
        media_url=str(o["video_url"] or o["image_url"] or "")
        media_type="video" if o["video_url"] else ("image" if o["image_url"] else "")
        if not media_url: raise HTTPException(409,"У оффера нет рекламного видео или фото")
        title=f"{o['name']} — актуальная цена и условия покупки"
        row=c.execute("""insert into content(offer_id,title,script,platform,status,media_url,media_type,source_text) values(%s,%s,%s,%s,'ready',%s,%s,%s) returning *""",(offer_id,title,str(o["description"] or ""),x.get("platform","multi"),media_url,media_type,str(o["description"] or ""))).fetchone()
    import enhancements; enhancements.build_variants(int(row["id"])); planned=enhancements.ensure_distribution_plan(int(row["id"]))
    return {"content":dict(row),"planned_channels":planned,"media_type":media_type}

@app.post("/api/content/{content_id}/publish-ready")
def publish_ready(content_id:int, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    with db() as c:
        row=c.execute("update content set status='ready' where id=%s returning *",(content_id,)).fetchone()
        if not row: raise HTTPException(404,"Материал не найден")
        return row

@app.post("/api/publish-queue")
async def queue_publish(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json()
    content_id=int(x["content_id"])
    with db() as c:
        row=c.execute("select * from content where id=%s",(content_id,)).fetchone()
        if not row: raise HTTPException(404,"Материал не найден")
        return c.execute("""insert into publish_queue(content_id,scheduled_at,status)
          values(%s,%s,'queued') returning *""",(content_id,x.get("scheduled_at"))).fetchone()

@app.get("/api/publish-queue")
def publish_queue():
    with db() as c:
        return c.execute("""select q.*, c.title, c.platform, c.status content_status
          from publish_queue q join content c on c.id=q.content_id
          order by q.id desc""").fetchall()

@app.post("/api/publish-queue/{queue_id}/published")
async def mark_published(queue_id:int, request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json()
    with db() as c:
        row=c.execute("""update publish_queue set status='published', rutube_url=%s,
          published_at=coalesce(%s,current_timestamp) where id=%s returning *""",
          (x.get("rutube_url"),x.get("published_at"),queue_id)).fetchone()
        if not row: raise HTTPException(404,"Элемент очереди не найден")
        c.execute("update content set status='published' where id=%s",(row["content_id"],))
        return row

@app.post("/api/revenue")
async def add_revenue(request: Request, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    x=await request.json()
    with db() as c:
        return c.execute("""insert into revenue_events(offer_id,content_id,subid,event_type,amount,status,event_at)
          values(%s,%s,%s,%s,%s,%s,coalesce(%s,current_timestamp)) returning *""",
          (x.get("offer_id"),x.get("content_id"),x.get("subid"),x.get("event_type","sale"),
           x.get("amount") or 0,x.get("status","approved"),x.get("event_at"))).fetchone()

@app.get("/api/revenue")
def revenue():
    with db() as c:
        return c.execute("""select r.*, o.name offer_name, c.title
          from revenue_events r left join offers o on o.id=r.offer_id
          left join content c on c.id=r.content_id order by r.id desc""").fetchall()

@app.get("/api/stats")
def stats():
    with db() as c:
        if using_sqlite():
            return c.execute("""select
              (select count(*) from offers where active=1) offers,
              (select count(*) from content) content,
              (select coalesce(sum(clicks),0) from content) clicks,
              (select coalesce(sum(conversions),0) from content) conversions,
              (select coalesce(sum(approved_commission),0) from content) commission,
              (select coalesce(sum(amount),0) from revenue_events where status='approved') revenue,
              (select count(*) from publish_queue where status='queued') queued,
              (select count(*) from click_events where created_at > datetime('now','-24 hours')) clicks24""").fetchone()
        return c.execute("""select
          (select count(*) from offers where active) offers,
          (select count(*) from content) content,
          (select coalesce(sum(clicks),0) from content) clicks,
          (select coalesce(sum(conversions),0) from content) conversions,
          (select coalesce(sum(approved_commission),0) from content) commission,
          (select coalesce(sum(amount),0) from revenue_events where status='approved') revenue,
          (select count(*) from publish_queue where status='queued') queued,
          (select count(*) from click_events where created_at > now()-interval '24 hours') clicks24""").fetchone()

PAGE=r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CPA Factory</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#f5f6f8;margin:0;color:#111}
main{max-width:1100px;margin:auto;padding:16px}.card{background:#fff;border-radius:16px;padding:18px;margin:10px 0;box-shadow:0 2px 10px #0000000b}
h1{margin:0}.muted{color:#69707d}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.metric{font-size:24px;font-weight:700}
button{border:0;border-radius:10px;padding:10px 13px;background:#111;color:#fff;margin:3px;cursor:pointer}
input,textarea,select{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ddd;border-radius:9px;margin:5px 0 9px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:8px;border-bottom:1px solid #eee}
.small{font-size:12px}.ok{color:#16803c}@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}table{display:block;overflow:auto;white-space:nowrap}}
</style></head><body><main>
<div class="card"><h1>CPA Factory</h1><div class="muted">Оффер → трекинг → контент → очередь публикации → аналитика</div>
<div class="small muted">GdeSlon XML API: <span id="gdeslonStatus">проверка…</span> · офферов: <span id="offerCount">0</span></div>
<div class="small muted">Admitad: <span id="cpaStatus">опционально</span></div>
<div style="margin-top:10px"><b>Автопилот:</b> <span id="pipelineStatus">проверка…</span>
<button onclick="runPipeline()">Запустить цикл</button></div>
<button onclick="importGdeSlon()">Обновить офферы из GdeSlon</button>
<button onclick="importCPA()">Обновить офферы из Admitad</button>
<button onclick="showTop()">Показать приоритетные офферы</button>
<div id="topOffers"></div>
<div class="small muted">Административные операции защищены токеном.</div></div>
<div class="grid"><div class="card"><div class="muted">Активные офферы</div><div id="m1" class="metric">0</div></div>
<div class="card"><div class="muted">Материалы</div><div id="m2" class="metric">0</div></div>
<div class="card"><div class="muted">Переходы</div><div id="m3" class="metric">0</div></div>
<div class="card"><div class="muted">Доход</div><div id="m4" class="metric">0 ₽</div></div></div>
<div class="card"><h2>Добавить оффер</h2>
<input id="name" placeholder="Название товара"><input id="merchant" placeholder="Магазин / CPA-сеть">
<input id="price" placeholder="Цена"><input id="commission" placeholder="Комиссия, ₽">
<input id="url" placeholder="Партнёрская ссылка"><input id="rules" placeholder="Разрешённые источники трафика">
<button onclick="addOffer()">Сохранить оффер</button></div>
<div class="card"><h2>Офферы</h2><div id="offers">Загрузка…</div></div>
<div class="card"><h2>Генератор контента</h2>
<select id="offerSelect"></select><select id="platform"><option>rutube</option><option>vk</option><option>dzen</option></select>
<button onclick="generate()">Сгенерировать сценарий</button><div id="generated"></div></div>
<div class="card"><h2>Контент</h2><div id="content">Загрузка…</div></div>
<div class="card"><h2>Очередь RUTUBE</h2><p class="small muted">Подготовленные материалы. Загрузку и отложенную публикацию выполняем в Студии RUTUBE.</p><div id="queue">Загрузка…</div></div>
<div class="card"><h2>Доход</h2><div id="revenue">Загрузка…</div></div>
</main><script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){
 let o=await (await fetch('/api/offers')).json(), c=await (await fetch('/api/content')).json(), s=await (await fetch('/api/stats')).json();
 let cs=await (await fetch('/api/cpa/status')).json();
 gdeslonStatus.textContent=cs.gdeslon_configured?'подключён':'не настроен';
 cpaStatus.textContent=cs.admitad_configured?'подключён':'не подключён';
 offerCount.textContent=Number(cs.active_offers||0);
 m1.textContent=s.offers;m2.textContent=s.content;m3.textContent=s.clicks;m4.textContent=Number(s.revenue||0).toLocaleString('ru-RU')+' ₽';
 offerSelect.innerHTML=o.map(x=>'<option value="'+x.id+'">'+esc(x.name)+'</option>').join('');
 offers.innerHTML=o.length?'<table><tr><th>Товар</th><th>Сеть</th><th>Цена</th><th>Комиссия</th><th>Переходы</th></tr>'+
 o.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.merchant)+'</td><td>'+Number(x.price||0).toLocaleString('ru-RU')+'</td><td>'+Number(x.commission||0).toLocaleString('ru-RU')+' ₽</td><td>'+x.clicks+'</td></tr>').join('')+'</table>':'Пока нет офферов';
 content.innerHTML=c.length?'<table><tr><th>Оффер</th><th>Площадка</th><th>Статус</th><th>Переходы</th><th>Ссылки</th></tr>'+
 c.map(x=>'<tr><td>'+esc(x.offer_name)+'</td><td>'+esc(x.platform)+'</td><td>'+esc(x.status)+'</td><td>'+x.clicks+'</td><td><a href="/go/'+x.offer_id+'?content_id='+x.id+'" target="_blank">тест</a> · <a href="/api/content/'+x.id+'/pack" target="_blank">пакет</a> · <a href="/api/content/'+x.id+'/zip" target="_blank">ZIP</a></td></tr>').join('')+'</table>':'Пока нет материалов';
 let q=await (await fetch('/api/publish-queue')).json();
 queue.innerHTML=q.length?'<table><tr><th>Материал</th><th>Дата</th><th>Статус</th><th>RUTUBE</th></tr>'+
 q.map(x=>'<tr><td>'+esc(x.title)+'</td><td>'+esc(x.scheduled_at||'—')+'</td><td>'+esc(x.status)+'</td><td>'+(x.rutube_url?'<a href="'+esc(x.rutube_url)+'" target="_blank">открыть</a>':'—')+'</td></tr>').join('')+'</table>':'Очередь пуста';
 let rv=await (await fetch('/api/revenue')).json();
 revenue.innerHTML=rv.length?'<table><tr><th>Оффер</th><th>Событие</th><th>Сумма</th><th>Статус</th></tr>'+
 rv.map(x=>'<tr><td>'+esc(x.offer_name)+'</td><td>'+esc(x.event_type)+'</td><td>'+Number(x.amount||0).toLocaleString('ru-RU')+' ₽</td><td>'+esc(x.status)+'</td></tr>').join('')+'</table>':'Пока нет событий дохода';
}
function adminToken(){
 let t=localStorage.getItem('cf_admin_token')||'';
 if(!t){t=prompt('Введите токен администратора CPA Factory'); if(t)localStorage.setItem('cf_admin_token',t);}
 return t||'';
}
async function adminFetch(url,opts={}){
 opts.headers=Object.assign({'Content-Type':'application/json','X-Admin-Token':adminToken()},opts.headers||{});
 let r=await fetch(url,opts);
 if(r.status===401){localStorage.removeItem('cf_admin_token'); alert('Неверный токен администратора.');}
 return r;
}
async function importGdeSlon(){
 let r=await adminFetch('/api/cpa/import/gdeslon');
 let x=await r.json().catch(()=>({}));
 if(x.status==='not_configured'){alert('GdeSlon не настроен в Render.');return;}
 if(!r.ok){alert(x.detail||'Ошибка импорта GdeSlon');return;}
 alert('GdeSlon: получено '+(x.received||0)+', добавлено '+(x.added||0)+', обновлено '+(x.updated||0)+'.');
 load(); refreshPipelineStatus();
}
async function importCPA(){
 let r=await adminFetch('/api/cpa/import');
 let x=await r.json().catch(()=>({}));
 if(x.status==='not_configured'){alert('Admitad пока не подключён. Нужны API-токен и ID площадки в защищённых переменных Render.');return;}
 if(!r.ok){alert(x.detail||'Ошибка импорта');return;}
 alert('Импорт завершён: добавлено '+(x.added||0)+', обновлено '+(x.updated||0)+'.');
 load();
}
async function showTop(){
 let r=await fetch('/api/cpa/top?limit=10'), x=await r.json();
 topOffers.innerHTML=x.length?'<table><tr><th>Оффер</th><th>EPC</th><th>CR</th><th>Рейтинг</th><th>Приоритет</th></tr>'+
 x.map(v=>'<tr><td>'+esc(v.name)+'</td><td>'+Number(v.epc||0).toLocaleString('ru-RU')+'</td><td>'+Number(v.cr||0).toLocaleString('ru-RU')+'%</td><td>'+Number(v.rating||0).toLocaleString('ru-RU')+'</td><td>'+v.score+'</td></tr>').join('')+'</table>':'Подходящих активных офферов пока нет';
}
async function refreshPipelineStatus(){
 try{
  let p=await (await fetch('/api/pipeline/status')).json();
  if(p.last_run){pipelineStatus.textContent=p.last_run.status==='ok'?'готов: материал в очереди':p.last_run.message||p.last_run.status;}
  else if(p.gdeslon_configured) pipelineStatus.textContent='готов к запуску через GdeSlon';
  else if(p.admitad_configured) pipelineStatus.textContent='готов к запуску через Admitad';
  else pipelineStatus.textContent='нет подключённой CPA-сети';
 }catch(e){pipelineStatus.textContent='ошибка проверки';}
}
async function runPipeline(){
 let r=await adminFetch('/api/pipeline/run',{method:'POST'});
 let x=await r.json().catch(()=>({}));
 if(x.status==='not_configured'){alert('Не подключена ни одна CPA-сеть: GdeSlon или Admitad.');return;}
 if(!r.ok){alert(x.detail||x.message||'Ошибка автопилота');return;}
 alert(x.status==='skipped'?'Свежий материал уже существует.':'Готово: оффер выбран, материал создан и поставлен в очередь RUTUBE.');
 load(); refreshPipelineStatus();
}
async function addOffer(){
 let r=await adminFetch('/api/offers',{method:'POST',body:JSON.stringify({name:name.value,merchant:merchant.value,price:price.value,commission:commission.value,tracking_url:url.value,traffic_rules:rules.value})});
 if(r.ok){['name','merchant','price','commission','url','rules'].forEach(x=>document.getElementById(x).value='');load();}
}
async function generate(){
 let r=await adminFetch('/api/content/generate',{method:'POST',body:JSON.stringify({offer_id:offerSelect.value,platform:platform.value})});
 if(!r.ok)return;
 let x=await r.json(); generated.innerHTML='<p><b>'+esc(x.title)+'</b></p><textarea rows="6" readonly>'+esc(x.script)+'</textarea><button onclick="queueItem('+x.id+')">Поставить в очередь RUTUBE</button><div class="ok">Материал создан со статусом draft.</div>';load();
}
async function queueItem(id){
 let when=prompt('Дата/время публикации ISO, например 2026-09-27T12:00:00+03:00','');
 if(when===null)return;
 let r=await adminFetch('/api/publish-queue',{method:'POST',body:JSON.stringify({content_id:id,scheduled_at:when||null})});
 if(r.ok){alert('Добавлено в очередь.');load();}
}
load(); refreshPipelineStatus();
</script></body></html>"""

@app.head("/")
def home_head():
    return Response(status_code=200)


# Load optional production integrations after all core routes/functions are defined.
try:
    import enhancements
except Exception as e:
    print("CPA_ENHANCEMENTS_IMPORT_ERROR", type(e).__name__, str(e), flush=True)
