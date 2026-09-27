import os, re, sqlite3, json, urllib.request, urllib.parse, tempfile, subprocess, shutil, textwrap, zipfile, io, html, threading
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse, Response
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="CPA Factory")
ADMIN_TOKEN = os.environ.get("CPA_ADMIN_TOKEN", "")

def require_admin(x_admin_token: str | None):
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
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

_AUTOPILOT_LOCK = threading.Lock()
_AUTOPILOT_INTERVAL = max(900, int(os.getenv("CPA_AUTOPILOT_INTERVAL", "3600") or 3600))

def _autopilot_loop():
    import time
    time.sleep(5)
    print("CPA_AUTOPILOT_STARTED", json.dumps({"interval_seconds": _AUTOPILOT_INTERVAL}, ensure_ascii=False))
    while True:
        try:
            if _AUTOPILOT_LOCK.acquire(blocking=False):
                try:
                    result = _pipeline_run()
                    print("CPA_AUTOPILOT", json.dumps(result, ensure_ascii=False, default=str))
                except Exception as e:
                    print("CPA_AUTOPILOT_ERROR", type(e).__name__, str(e))
                finally:
                    _AUTOPILOT_LOCK.release()
        except Exception as e:
            print("CPA_AUTOPILOT_LOOP_ERROR", type(e).__name__, str(e))
        time.sleep(_AUTOPILOT_INTERVAL)

def _mp4_selftest():
    import os, shutil
    try:
        row = {
            "id": 0,
            "title": "CPA Factory MP4 self-test",
            "script": "MP4 self-test",
            "platform": "rutube",
            "scenes": '[{"time":"00:00-00:02","text":"CPA Factory MP4 test"},{"time":"00:02-00:04","text":"FFmpeg OK"}]'
        }
        offer = {"id": 0, "name": "MP4 self-test", "price": 0, "cpa_rate": ""}
        path, tmp = _make_mp4(0, row, offer)
        size = os.path.getsize(path)
        if size < 1000:
            raise RuntimeError(f"MP4 too small: {size} bytes")
        print("MP4_SELFTEST", json.dumps({"status":"ok","bytes":size}, ensure_ascii=False), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(path)
        except Exception:
            pass
    except Exception as e:
        print("MP4_SELFTEST", json.dumps({"status":"error","error":f"{type(e).__name__}: {e}"}, ensure_ascii=False), flush=True)

@app.on_event("startup")
def startup():
    init()
    if os.getenv("GDESLON_API_TOKEN", "").strip():
        threading.Thread(target=_auto_gdeslon_import, daemon=True).start()
    if os.getenv("CPA_AUTOPILOT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}:
        threading.Thread(target=_autopilot_loop, daemon=True).start()

@app.get("/health")
def health():
    return {"ok": True, "service": "cpa-factory"}

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
def go(offer_id: int, content_id: int = 0):
    with db() as c:
        offer = c.execute("select * from offers where id=%s and active=true", (offer_id,)).fetchone()
        if not offer or not offer["tracking_url"]:
            raise HTTPException(404, "Оффер не найден")
        subid = f"cf_{offer_id}_{content_id or 0}"
        c.execute("insert into click_events(offer_id,content_id,subid) values(%s,%s,%s)",
                  (offer_id, content_id or None, subid))
        c.execute("update content set clicks=clicks+1 where id=%s", (content_id,)) if content_id else None
    return RedirectResponse(add_tracking(offer["tracking_url"], subid), status_code=302)

@app.get("/api/offers")
def offers():
    with db() as c:
        return c.execute("""select o.*, count(e.id) clicks
          from offers o left join click_events e on e.offer_id=o.id
          group by o.id order by o.id desc""").fetchall()

def _admitad_get(url: str, token: str):
    req=urllib.request.Request(url, headers={"Authorization":f"Bearer {token}","Accept":"application/json","User-Agent":"CPAFactory/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))

def _gdeslon_get(url: str, token: str):
    # GdeSlon XML API: authentication is the _gs_at query parameter.
    req=urllib.request.Request(url, headers={"Accept":"application/xml,text/xml","User-Agent":"CPAFactory/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")

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
    token=os.getenv("ADMITAD_ACCESS_TOKEN","").strip()
    website=os.getenv("ADMITAD_WEBSITE_ID","").strip()
    if not token or not website:
        return {"status":"not_configured","message":"Нужны ADMITAD_ACCESS_TOKEN и ADMITAD_WEBSITE_ID"}
    url=f"https://api.admitad.com/advcampaigns/website/{urllib.parse.quote(website,safe='')}/?limit=100&connection_status=active&language=ru"
    try:
        data=_admitad_get(url,token)
    except Exception as e:
        raise HTTPException(502,f"Admitad API: {e}")
    items=data.get("results",[]) if isinstance(data,dict) else data
    added=updated=skipped=0
    with db() as c:
        for v in items:
            if str(v.get("connection_status","active"))!="active": continue
            cid=v.get("id"); name=v.get("name"); gotolink=v.get("gotolink")
            if not cid or not name or not gotolink:
                skipped+=1; continue
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
    return {"status":"ok","source":"admitad","received":len(items),"added":added,"updated":updated,"skipped":skipped}

@app.get("/api/cpa/import/gdeslon")
def cpa_import_gdeslon(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    token=os.getenv("GDESLON_API_TOKEN","").strip()
    if not token:
        return {"status":"not_configured","message":"Нужен GDESLON_API_TOKEN"}
    query=os.getenv("GDESLON_QUERY","").strip()
    limit=max(1,min(int(os.getenv("GDESLON_LIMIT","100") or 100),100))
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
                c.execute("""update offers set name=%s,merchant=%s,price=%s,tracking_url=%s,traffic_rules=%s,active=true,site_url=%s,image_url=%s where id=%s""",
                          (name,"Где Слон?",price,link,rules,link,v.get("image_url"),existing["id"]))
                updated+=1
            else:
                c.execute("""insert into offers(name,merchant,price,commission,tracking_url,traffic_rules,active,source,external_id,rating,epc,cr,cpa_rate,site_url)
                    values(%s,%s,%s,0,%s,%s,true,'gdeslon',%s,0,0,0,'',%s)""",
                    (name,"Где Слон?",price,link,rules,str(oid),link,v.get("image_url"))))
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
        "admitad_configured":bool(os.getenv("ADMITAD_ACCESS_TOKEN") and os.getenv("ADMITAD_WEBSITE_ID")),
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
        "admitad_configured": bool(os.getenv("ADMITAD_ACCESS_TOKEN") and os.getenv("ADMITAD_WEBSITE_ID")),
        "gdeslon_configured": bool(os.getenv("GDESLON_API_TOKEN")),
        "active_offers": active, "queued": queued,
        "top_offer": dict(top[0]) if top else None,
        "last_run": dict(last) if last else None
    }

def _pipeline_run():
    try:
        try:
            imported = cpa_import(ADMIN_TOKEN)
        except Exception:
            imported = {"status":"error"}
        if imported.get("status") == "not_configured" or imported.get("status") == "error":
            try:
                imported = cpa_import_gdeslon(ADMIN_TOKEN)
            except Exception:
                imported = {"status":"error"}
        if imported.get("status") == "not_configured":
            msg = "Не подключена CPA-сеть: Admitad или Где Слон?"
            with db() as c:
                c.execute("insert into pipeline_runs(status,message) values(%s,%s)", ("not_configured", msg))
            return {"status":"not_configured","message":msg}
        top = cpa_top(1)
        if not top:
            msg = "После импорта нет активных офферов"
            with db() as c:
                c.execute("insert into pipeline_runs(status,message) values(%s,%s)", ("empty", msg))
            return {"status":"empty","message":msg}
        o = top[0]
        offer_id = int(o["id"])
        name = o["name"]
        price = o["price"] or 0
        price_label = f"{price:g} ₽" if price else "цена уточняется"
        cpa_rate = o["cpa_rate"] or ""
        rate_text = f"{cpa_rate}%" if cpa_rate and "%" not in str(cpa_rate) else str(cpa_rate)
        title = f"{name}: стоит ли покупать? Цена {price_label}"
        # Avoid generating the same offer repeatedly within 24 hours.
        with db() as c:
            if using_sqlite():
                recent = c.execute("""select id from content
                  where offer_id=%s and created_at > datetime('now','-24 hours') limit 1""",(offer_id,)).fetchone()
            else:
                recent = c.execute("""select id from content
                  where offer_id=%s and created_at > now()-interval '24 hours' limit 1""",(offer_id,)).fetchone()
            if recent:
                msg = f"Для оффера уже есть свежий материал: #{recent['id']}"
                c.execute("insert into pipeline_runs(status,offer_id,message) values(%s,%s,%s)",("skipped",offer_id,msg))
                return {"status":"skipped","offer_id":offer_id,"content_id":recent["id"],"message":msg}
            script=(f"Сегодня разбираем товар «{name}». Цена — {price_label}. "
                    f"Смотрим характеристики, кому он подходит и на что обратить внимание перед покупкой. "
                    f"Ссылка на актуальную цену — в описании. "
                    f"Партнёрская ставка по программе: {rate_text or 'уточняется'}.")
            row=c.execute("""insert into content(offer_id,title,script,platform,status)
              values(%s,%s,%s,'rutube','ready') returning *""",
              (offer_id,title,script)).fetchone()
            content_id=int(row["id"])
            q=c.execute("""insert into publish_queue(content_id,scheduled_at,status)
              values(%s,null,'queued') returning *""",(content_id,)).fetchone()
            queue_id=int(q["id"])
            c.execute("""insert into pipeline_runs(status,offer_id,content_id,queue_id,message)
              values(%s,%s,%s,%s,%s)""",
              ("ok",offer_id,content_id,queue_id,"Оффер импортирован, материал создан и поставлен в очередь RUTUBE"))
        return {"status":"ok","offer_id":offer_id,"content_id":content_id,"queue_id":queue_id,
                "offer_name":name,"message":"Цикл выполнен"}
    except HTTPException as e:
        with db() as c:
            c.execute("insert into pipeline_runs(status,message) values(%s,%s)",("error",str(e.detail)))
        raise
    except Exception as e:
        with db() as c:
            c.execute("insert into pipeline_runs(status,message) values(%s,%s)",("error",str(e)))
        raise HTTPException(500, f"Pipeline: {e}")

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

def _video_text(s):
    s=re.sub(r'\s+',' ',str(s or '')).strip()
    return s

def _wrap_lines(text, font, max_width, draw):
    words=_video_text(text).split()
    lines=[]; cur=''
    for w in words:
        test=(cur+' '+w).strip()
        if not cur or draw.textbbox((0,0),test,font=font)[2] <= max_width:
            cur=test
        else:
            lines.append(cur); cur=w
    if cur: lines.append(cur)
    return lines

def _fit_font(text, font_path, max_size, min_size, max_width, max_height, draw):
    size=max_size
    while size >= min_size:
        f=ImageFont.truetype(font_path,size)
        lines=_wrap_lines(text,f,max_width,draw)
        bbox=draw.textbbox((0,0),'Ag',font=f)
        line_h=bbox[3]-bbox[1]+10
        if len(lines)*line_h <= max_height:
            return f,lines,line_h
        size-=2
    f=ImageFont.truetype(font_path,min_size)
    return f,_wrap_lines(text,f,max_width,draw),max(28,min_size+10)

def _download_product_image(offer,tmp):
    urls=[]
    for key in ('image_url','image_url2'):
        u=offer.get(key)
        if u and str(u).startswith(('http://','https://')): urls.append(str(u))
    # Last-resort: try the product/landing page and extract og:image.
    if not urls and offer.get('site_url'):
        try:
            req=urllib.request.Request(str(offer['site_url']),headers={'User-Agent':'Mozilla/5.0 CPAFactory/1.0'})
            with urllib.request.urlopen(req,timeout=10) as r:
                raw=r.read(400000).decode('utf-8','ignore')
            m=re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',raw,re.I)
            if not m:
                m=re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',raw,re.I)
            if m: urls.append(urllib.parse.urljoin(str(offer['site_url']),html.unescape(m.group(1))))
        except Exception:
            pass
    if not urls: return None
    try:
        req=urllib.request.Request(urls[0],headers={'User-Agent':'Mozilla/5.0 CPAFactory/1.0'})
        with urllib.request.urlopen(req,timeout=15) as r:
            data=r.read(5*1024*1024)
        path=os.path.join(tmp,'product.jpg')
        with open(path,'wb') as f: f.write(data)
        im=Image.open(path).convert('RGB')
        im.thumbnail((760,760),Image.Resampling.LANCZOS)
        canvas=Image.new('RGB',(760,760),'white')
        canvas.paste(im,((760-im.width)//2,(760-im.height)//2))
        canvas.save(path,'JPEG',quality=92)
        return path
    except Exception:
        return None

def _tts_audio(text,out_path):
    try:
        from gtts import gTTS
    except Exception:
        raise HTTPException(503,'Озвучка недоступна: не установлен gTTS')
    try:
        gTTS(text=text,lang='ru',slow=False).save(out_path)
    except Exception as e:
        raise HTTPException(502,f'Ошибка генерации озвучки: {e}')

def _make_scene_image(scene_text, product_path, index, total, font_path, tmp):
    im=Image.new('RGB',(720,1280),(14,16,22))
    d=ImageDraw.Draw(im)
    # Premium card background and hierarchy.
    d.rounded_rectangle((28,28,692,1252),radius=34,fill=(24,27,36))
    d.text((58,58),'CPA FACTORY',font=ImageFont.truetype(font_path,22),fill=(190,196,208))
    if product_path and os.path.exists(product_path):
        try:
            p=Image.open(product_path).convert('RGB')
            p.thumbnail((590,590),Image.Resampling.LANCZOS)
            card=(65,125,655,715)
            d.rounded_rectangle(card,radius=28,fill=(255,255,255))
            x=card[0]+(card[2]-card[0]-p.width)//2
            y=card[1]+(card[3]-card[1]-p.height)//2
            im.paste(p,(x,y))
        except Exception:
            pass
    d.rounded_rectangle((58,750,662,1135),radius=28,fill=(34,38,50))
    font,lines,line_h=_fit_font(scene_text,font_path,48,28,550,310,d)
    total_h=len(lines)*line_h
    y=750+(385-total_h)//2
    for line in lines:
        bbox=d.textbbox((0,0),line,font=font)
        x=(720-(bbox[2]-bbox[0]))//2
        d.text((x,y),line,font=font,fill=(248,249,251))
        y+=line_h
    d.text((58,1175),f'{index}/{total}',font=ImageFont.truetype(font_path,22),fill=(150,158,174))
    d.rounded_rectangle((150,1180,570,1188),radius=4,fill=(70,76,90))
    d.rounded_rectangle((150,1180,150+420*index/total,1188),radius=4,fill=(255,255,255))
    path=os.path.join(tmp,f'scene_{index:02d}.png')
    im.save(path,'JPEG',quality=92)
    return path

def _make_mp4(content_id, row, offer):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg=None
    if not ffmpeg:
        raise HTTPException(503,'Не удалось получить ffmpeg; MP4 пока недоступен')
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        raise HTTPException(503,'Не установлен Pillow')
    tmp=tempfile.mkdtemp(prefix='cfvideo_')
    try:
        pack=build_content_pack(row,offer)
        scenes=pack['scenes']
        font_paths=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf']
        font_path=next((p for p in font_paths if os.path.exists(p)),None)
        if not font_path: raise HTTPException(503,'Шрифт для MP4 не найден')
        product_path=_download_product_image(offer,tmp)
        image_file=_make_scene_image
        concat=os.path.join(tmp,'concat.txt')
        segment_files=[]
        durations=[]
        # Keep the video around 60 seconds, but change visuals every ~4-5 seconds.
        for i,sc in enumerate(scenes,1):
            text=_video_text(sc.get('text',''))
            img=image_file(text,product_path,i,len(scenes),font_path,tmp)
            audio=os.path.join(tmp,f'audio_{i:02d}.mp3')
            try:
                _tts_audio(text,audio)
                probe=subprocess.run([ffmpeg,'-i',audio],capture_output=True,text=True,timeout=15)
                m=re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)',probe.stderr)
                audio_dur=float(m.group(1))*3600+float(m.group(2))*60+float(m.group(3)) if m else 3.5
            except Exception:
                audio=None; audio_dur=3.5
            # Target visual cadence: roughly 4-5 sec per slide, while never cutting speech.
            dur=max(3.8,min(6.0,audio_dur+0.35))
            seg=os.path.join(tmp,f'segment_{i:02d}.mp4')
            cmd=[ffmpeg,'-y','-loop','1','-i',img]
            if audio:
                cmd += ['-i',audio,'-t',f'{dur:.2f}','-vf','scale=720:1280,format=yuv420p','-r','24','-c:v','libx264','-preset','veryfast','-crf','22','-c:a','aac','-b:a','128k','-shortest',seg]
            else:
                cmd += ['-t',f'{dur:.2f}','-vf','scale=720:1280,format=yuv420p','-r','24','-c:v','libx264','-preset','veryfast','-crf','22',seg]
            subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=45)
            segment_files.append(seg); durations.append(dur)
        with open(concat,'w',encoding='utf-8') as f:
            for p in segment_files: f.write(f"file '{p}'\n")
        out=os.path.join(tmp,f'content_{content_id}.mp4')
        subprocess.run([ffmpeg,'-y','-f','concat','-safe','0','-i',concat,'-c','copy','-movflags','+faststart',out],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=90)
        print('VIDEO_BUILD',json.dumps({'content_id':content_id,'scenes':len(scenes),'duration':round(sum(durations),1),'product_image':bool(product_path),'voice':True},ensure_ascii=False),flush=True)
        return out,tmp
    except subprocess.CalledProcessError as e:
        raise HTTPException(500,'Ошибка сборки MP4: '+e.stderr.decode('utf-8','ignore')[-800:])

def _make_pack_zip(content_id,row,offer):
    mp4,tmp=_make_mp4(content_id,row,offer)
    pack=build_content_pack(row,offer)
    z=io.BytesIO()
    with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as zz:
        zz.write(mp4,arcname=f'content_{content_id}.mp4')
        zz.writestr('description.txt',pack['description'])
        zz.writestr('voice_script.txt',pack['voice_script'])
        zz.writestr('scenes.json',json.dumps(pack['scenes'],ensure_ascii=False,indent=2))
        zz.writestr('thumbnail_prompt.txt',pack['thumbnail_prompt'])
    shutil.rmtree(tmp,ignore_errors=True); z.seek(0); return z

def build_content_pack(row, offer):
    name = offer["name"] or "товар"
    price = offer["price"] or 0
    price_label = f"{price:g} ₽" if price else "цена уточняется"
    rate = offer["cpa_rate"] or ""
    rate_text = f"{rate}%" if rate and "%" not in str(rate) else str(rate)
    link = f"/go/{offer['id']}?content_id={row['id']}"
    hook = f"СТОП. Вот что важно знать перед покупкой «{name}»."
    description = (f"Разбираем «{name}»: цена, ключевые характеристики, кому подходит и что проверить перед покупкой.\\n\\n"
                   f"🔗 Актуальная цена и предложение: {link}\\n\\n"
                   f"Партнёрская ставка: {rate_text or 'уточняется'}.\\n"
                   f"Информация об оффере может изменяться продавцом.")
    cta = f"Актуальная цена и предложение — по ссылке в описании: {link}"
    scenes = [
        {"time":"00:00-00:04","text":hook},
        {"time":"00:04-00:09","text":f"{name}. Цена сейчас — {price_label}."},
        {"time":"00:09-00:14","text":"Сначала смотрим, что именно вы получаете за эти деньги."},
        {"time":"00:14-00:19","text":"Ключевые характеристики — коротко и по делу."},
        {"time":"00:19-00:24","text":"Кому этот товар действительно подходит?"},
        {"time":"00:24-00:29","text":"Что проверить перед оформлением заказа."},
        {"time":"00:29-00:34","text":"Цена и условия могут меняться — проверяйте актуальное предложение."},
        {"time":"00:34-00:39","text":"Сравните комплектацию и характеристики перед оплатой."},
        {"time":"00:39-00:44","text":"Если характеристики подходят — переходите к актуальному предложению."},
        {"time":"00:44-00:49","text":"Ссылка на товар находится в описании ролика."},
        {"time":"00:49-00:55","text":cta},
        {"time":"00:55-01:00","text":"Сохраните ролик, чтобы быстро вернуться к товару."}
    ]
    thumb = f"Премиальная вертикальная обложка 9:16 для RUTUBE: крупно показать реальный товар «{name}», рядом короткий заголовок «Стоит ли покупать?», современный минималистичный дизайн, много воздуха, без мелкого текста."
    return {"content_id":int(row["id"]),"offer_id":int(offer["id"]),"title":row["title"],"hook":hook,
            "description":description,"cta":cta,"tracking_link":link,"scenes":scenes,
            "thumbnail_prompt":thumb,"voice_script":row["script"],"platform":row["platform"]}

@app.get("/api/content/{content_id}/mp4")
def content_mp4(content_id:int):
    with db() as c:
        row=c.execute("select * from content where id=%s",(content_id,)).fetchone()
        if not row: raise HTTPException(404,"Материал не найден")
        offer=c.execute("select * from offers where id=%s",(row["offer_id"],)).fetchone()
        if not offer: raise HTTPException(404,"Оффер не найден")
    path,tmp=_make_mp4(content_id,row,offer)
    return FileResponse(path,media_type="video/mp4",filename=f"rutube_content_{content_id}.mp4",background=None,content_disposition_type="inline")

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
    x=await request.json()
    offer_id=int(x["offer_id"])
    with db() as c:
        o=c.execute("select * from offers where id=%s", (offer_id,)).fetchone()
        if not o: raise HTTPException(404, "Оффер не найден")
        name=o["name"]; price=o["price"] or 0; commission=o["commission"] or 0
        price_label=f"{price:g} ₽" if price else "цена уточняется"
        cpa_rate=o["cpa_rate"] or ""
        rate_text=f"{cpa_rate}%" if cpa_rate and "%" not in str(cpa_rate) else str(cpa_rate)
        title=f"{name}: стоит ли покупать? Цена {price_label}"
        script=(f"Сегодня разбираем товар «{name}». Цена — {price:g} ₽. "
                f"Смотрим характеристики, кому он подходит и на что обратить внимание перед покупкой. "
                f"Ссылка на актуальную цену — в описании. Переход по ссылке помогает отследить предложение. "
                f"Партнёрская ставка по программе: {rate_text or 'уточняется'}.")
        return c.execute("""insert into content(offer_id,title,script,platform,status)
          values(%s,%s,%s,%s,'draft') returning *""",
          (offer_id,title,script,x.get("platform","rutube"))).fetchone()

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
 c.map(x=>'<tr><td>'+esc(x.offer_name)+'</td><td>'+esc(x.platform)+'</td><td>'+esc(x.status)+'</td><td>'+x.clicks+'</td><td><a href="/go/'+x.offer_id+'?content_id='+x.id+'" target="_blank">тест</a> · <a href="/api/content/'+x.id+'/pack" target="_blank">пакет</a> · <a href="/api/content/'+x.id+'/mp4" target="_blank">MP4</a> · <a href="/api/content/'+x.id+'/zip" target="_blank">ZIP</a></td></tr>').join('')+'</table>':'Пока нет материалов';
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

@app.get("/")
def home():
    return HTMLResponse(PAGE)
