import os, re, json, html, urllib.request, urllib.parse
from fastapi import Header, HTTPException
from fastapi.responses import HTMLResponse
import app as core

MEDIA_KEYS=("image_url","image_url2","video_url","video_url2")
def _text(v): return re.sub(r"\s+"," ",str(v or "")).strip()
def _url(v):
    v=_text(v); return v if v.startswith(("http://","https://")) else ""

def fetch_media(url):
    out={k:"" for k in MEDIA_KEYS}; url=_url(url)
    if not url:return out
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"CPAFactory/2.0"})
        with urllib.request.urlopen(req,timeout=10) as r: raw=r.read(1800000).decode("utf-8","ignore")
    except Exception:return out
    def meta(name):
        for p in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)',
                  rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(name)}["\']'):
            m=re.search(p,raw,re.I)
            if m:return html.unescape(m.group(1)).strip()
        return ""
    imgs=[]; vids=[]
    for key in ("og:image","twitter:image"):
        u=meta(key)
        if u and (u:=urllib.parse.urljoin(url,u)) not in imgs: imgs.append(u)
    for key in ("og:video","og:video:url","twitter:player:stream"):
        u=meta(key)
        if u and (u:=urllib.parse.urljoin(url,u)) not in vids: vids.append(u)
    for m in re.finditer(r'<source[^>]+src=["\']([^"\']+)',raw,re.I):
        u=urllib.parse.urljoin(url,html.unescape(m.group(1)))
        if u.lower().split("?")[0].endswith((".mp4",".webm",".mov",".m4v")) and u not in vids: vids.append(u)
    out["image_url"]=imgs[0] if imgs else ""; out["image_url2"]=imgs[1] if len(imgs)>1 else ""
    out["video_url"]=vids[0] if vids else ""; out["video_url2"]=vids[1] if len(vids)>1 else ""
    return out

def migrate():
    with core.db() as c:
        for s in ["alter table offers add column video_url text","alter table offers add column video_url2 text",
                  "alter table offers add column demand_count real default 0","alter table offers add column demand_checked_at text",
                  "alter table offers add column yandex_promise real default 0","alter table offers add column description text",
                  "alter table offers add column category text","alter table offers add column old_price real default 0",
                  "alter table offers add column discount text","alter table offers add column media_checked_at text",
                  "alter table offers add column media_type text","alter table offers add column traffic_allowed text",
                  "alter table content add column media_url text","alter table content add column media_type text",
                  "alter table content add column landing_slug text","alter table content add column variants_json text",
                  "alter table content add column source_text text"]:
            try:c.execute(s)
            except Exception:pass
        if core.using_sqlite():
            c.execute("""create table if not exists distribution_queue(
              id integer primary key autoincrement,content_id integer references content(id),channel text not null,
              status text default 'planned',external_id text,external_url text,scheduled_at text,last_error text,
              created_at text default CURRENT_TIMESTAMP,published_at text)""")
        else:
            c.execute("""create table if not exists distribution_queue(
              id bigserial primary key,content_id int references content(id),channel text not null,
              status text default 'planned',external_id text,external_url text,scheduled_at timestamptz,last_error text,
              created_at timestamptz default now(),published_at timestamptz)""")
        c.execute("create unique index if not exists uq_distribution_content_channel on distribution_queue(content_id,channel)")
    print("CPA_DISTRIBUTION_MIGRATION_OK",flush=True)

def _enrich_rows(limit=100):
    with core.db() as c:
        rows=c.execute("select id,site_url,image_url,image_url2,video_url,video_url2 from offers where active=true order by id desc limit %s",(max(1,min(int(limit),200)),)).fetchall()
        changed=0
        for r in rows:
            if not r["site_url"] or r["video_url"] or r["image_url"]: continue
            m=fetch_media(r["site_url"])
            if any(m.values()):
                c.execute("update offers set image_url=%s,image_url2=%s,video_url=%s,video_url2=%s,media_type=%s,media_checked_at=current_timestamp where id=%s",
                          (m["image_url"],m["image_url2"],m["video_url"],m["video_url2"],"video" if m["video_url"] else "image",r["id"])); changed+=1
    return changed

_original_import=core.cpa_import_gdeslon
def import_gdeslon_with_media(x_admin_token: str|None=Header(default=None)):
    result=_original_import(x_admin_token)
    try: result["media_enriched"]=_enrich_rows(int(os.getenv("CPA_MEDIA_ENRICH_LIMIT","100") or 100))
    except Exception as e: result["media_enrich_error"]=f"{type(e).__name__}: {e}"
    return result
core.cpa_import_gdeslon=import_gdeslon_with_media

def _numeric_rate(value):
    if value is None: return 0.0
    m=re.search(r"(\d+(?:[.,]\d+)?)",str(value))
    return float(m.group(1).replace(",", ".")) if m else 0.0

def _effective_payout(r):
    explicit=float(r.get("commission") or 0)
    rate=_numeric_rate(r.get("cpa_rate"))
    price=float(r.get("price") or 0)
    if explicit > 0: return explicit
    if rate > 0 and price > 0: return price * rate / 100.0
    return 0.0

def _traffic_ok(r):
    raw=str(r.get("traffic_rules") or r.get("traffic_allowed") or "").strip().lower()
    if not raw: return True
    prohibited=("forbidden","запрещ","не разреш","prohibited","not allowed")
    return not any(x in raw for x in prohibited)

def distribution_top(limit=10):
    with core.db() as c:
        rows=c.execute("""select o.*,count(e.id) clicks from offers o left join click_events e on e.offer_id=o.id
          where o.active=true group by o.id""").fetchall()
    out=[]
    for rr in rows:
        r=dict(rr)
        if not _traffic_ok(r): continue
        media=3 if r.get("video_url") else (2 if r.get("image_url") else 0)
        if not media: continue
        epc=float(r.get("epc") or 0); cr=float(r.get("cr") or 0)
        demand=float(r.get("demand_count") or 0); clicks=int(r.get("clicks") or 0)
        payout=_effective_payout(r)
        score=(media*1.5
               +min(__import__("math").log1p(max(demand,0)),12)*0.9
               +min(__import__("math").log1p(max(epc,0)),8)*1.4
               +min(max(cr,0),100)*0.08
               +min(__import__("math").log1p(max(payout,0)),12)*0.9
               +min(clicks,1000)*0.001)
        r["effective_payout"]=round(payout,2)
        r["score"]=round(score,4)
        out.append(r)
    out.sort(key=lambda x:(x["score"],x["effective_payout"],float(x.get("demand_count") or 0),int(x["id"])),reverse=True)
    return out[:max(1,min(int(limit),50))]

CHANNELS=("rutube","vk","telegram","dzen","seo","avito","ads","email_optin")

def build_variants(content_id):
    with core.db() as c:
        row=c.execute("select c.*,o.name offer_name,o.price,o.description from content c join offers o on o.id=c.offer_id where c.id=%s",(content_id,)).fetchone()
    if not row: raise HTTPException(404,"Материал не найден")
    name=_text(row["offer_name"]); price=float(row["price"] or 0); price_label=f"{price:g} ₽" if price else "актуальная цена"
    link=f"/r/{content_id}?source=content&channel=landing"; desc=_text(row["description"])[:1800]
    v={"commercial":f"{name}. {price_label}. Проверьте характеристики, комплектацию и актуальные условия у продавца.\n\nАктуальное предложение: {link}",
       "short":f"{name} — актуальная цена и условия покупки. Проверить предложение: {link}",
       "problem_solution":f"Ищете {name.lower()}? Сначала сравните характеристики, комплектацию и цену. Актуальное предложение: {link}",
       "informational":f"Что проверить перед покупкой {name}: характеристики, комплектацию, наличие и итоговую цену. {desc}\n\nПроверить: {link}",
       "seo":f"{name}: цена, характеристики, условия покупки и актуальное предложение. Перед заказом проверьте данные продавца. {link}",
       "disclosure":f"Партнёрская ссылка: переход позволяет учитывать источник трафика. {name}. {price_label}. {link}"}
    with core.db() as c:c.execute("update content set variants_json=%s,landing_slug=%s where id=%s",(json.dumps(v,ensure_ascii=False),"offer-"+str(content_id),content_id))
    return v

def ensure_distribution_plan(content_id):
    build_variants(content_id)
    with core.db() as c:
        for ch in CHANNELS:
            c.execute("insert into distribution_queue(content_id,channel,status) values(%s,%s,'planned') on conflict(content_id,channel) do nothing",(content_id,ch))
        return int(c.execute("select count(*) n from distribution_queue where content_id=%s",(content_id,)).fetchone()["n"])

@core.app.get("/api/distribution")
def distribution_queue(limit:int=100):
    with core.db() as c:return c.execute("""select q.*,c.title,o.name offer_name from distribution_queue q join content c on c.id=q.content_id join offers o on o.id=c.offer_id order by q.id desc limit %s""",(max(1,min(limit,500)),)).fetchall()

@core.app.get("/api/distribution/plan/{content_id}")
def distribution_plan(content_id:int):
    ensure_distribution_plan(content_id)
    with core.db() as c:return c.execute("select * from distribution_queue where content_id=%s order by id",(content_id,)).fetchall()

@core.app.post("/api/distribution/{queue_id}/published")
async def distribution_published(queue_id:int,request,x_admin_token:str|None=Header(default=None)):
    core.require_admin(x_admin_token); data=await request.json()
    with core.db() as c:
        row=c.execute("""update distribution_queue set status='published',external_id=%s,external_url=%s,published_at=coalesce(%s,current_timestamp),last_error=null where id=%s returning *""",(data.get("external_id"),data.get("external_url"),data.get("published_at"),queue_id)).fetchone()
    if not row: raise HTTPException(404,"План публикации не найден")
    return row

@core.app.get("/api/landing/{content_id}",response_class=HTMLResponse)
def landing(content_id:int):
    with core.db() as c:
        row=c.execute("select c.*,o.name,o.merchant,o.price,o.description,o.image_url,o.video_url from content c join offers o on o.id=c.offer_id where c.id=%s and o.active=true",(content_id,)).fetchone()
    if not row: raise HTTPException(404,"Предложение не найдено")
    title=html.escape(_text(row["name"])); desc=html.escape(_text(row["description"])[:2500]); media=_url(row["video_url"]) or _url(row["image_url"])
    media_html=(f'<video controls playsinline preload="metadata" style="width:100%;max-height:65vh" src="{html.escape(media)}"></video>' if row["video_url"] else f'<img src="{html.escape(media)}" style="width:100%;max-height:65vh;object-fit:contain">') if media else ""
    cta=f"/r/{content_id}?source=landing&channel=landing"
    return HTMLResponse(f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:760px;margin:auto;padding:18px"><h1>{title}</h1>{media_html}<p>{desc}</p><p>Актуальная цена и условия могут измениться — проверяйте их на странице продавца.</p><a href="{cta}" style="display:block;padding:16px;background:#111;color:#fff;text-align:center;border-radius:10px;text-decoration:none">Проверить актуальное предложение</a><p style="font-size:12px;color:#777">Партнёрская ссылка. Некоторые ссылки могут приносить комиссию без изменения цены для покупателя.</p></body></html>""")

@core.app.get("/api/cpa/distribution-status")
def distribution_status():
    with core.db() as c:
        q=c.execute("select status,count(*) n from distribution_queue group by status").fetchall()
        m=c.execute("select media_type,count(*) n from offers where active=true group by media_type").fetchall()
        clicks=c.execute("select count(*) n from click_events").fetchone()["n"]
        sales=c.execute("select count(*) n from revenue_events where event_type in ('sale','approved_sale') and status='approved'").fetchone()["n"]
        commission=c.execute("select coalesce(sum(amount),0) n from revenue_events where status='approved'").fetchone()["n"]
    return {"mode":"distribution_engine","queue":q,"media_inventory":m,"clicks":int(clicks),"confirmed_sales":int(sales),"commission":float(commission or 0),"channels":CHANNELS}


@core.app.post("/api/wordstat/run")
def wordstat_run_now(x_admin_token: str|None=Header(default=None)):
    core.require_admin(x_admin_token)
    try:
        import wordstat_monitor
        result = wordstat_monitor.run()
        return {"status":"ok","exit_code":result}
    except Exception as e:
        print("CPA_WORDSTAT_MANUAL_ERROR", type(e).__name__, str(e), flush=True)
        raise HTTPException(500, f"Wordstat run failed: {type(e).__name__}: {e}")

_WORDSTAT_DAILY_LOCK=__import__("threading").Lock()
_WORDSTAT_DAILY_DATE={"value":None}

def _wordstat_daily_hook():
    if not os.getenv("YANDEX_WORDSTAT_API_KEY") or not os.getenv("YANDEX_WORDSTAT_FOLDER_ID"):
        return
    import datetime, wordstat_monitor
    today=datetime.datetime.utcnow().date().isoformat()
    if _WORDSTAT_DAILY_DATE["value"]==today: return
    if not _WORDSTAT_DAILY_LOCK.acquire(blocking=False): return
    try:
        if _WORDSTAT_DAILY_DATE["value"]!=today:
            _WORDSTAT_DAILY_DATE["value"]=today
            __import__("threading").Thread(target=wordstat_monitor.run,daemon=True,name="cpa-wordstat-daily").start()
    finally:
        _WORDSTAT_DAILY_LOCK.release()

_original_cycle=core._autopilot_cycle
def _cycle_with_wordstat():
    result=_original_cycle()
    try: _wordstat_daily_hook()
    except Exception as e: print("CPA_WORDSTAT_SCHEDULE_ERROR",type(e).__name__,str(e),flush=True)
    return result
core._autopilot_cycle=_cycle_with_wordstat

print("CPA_DISTRIBUTION_ENGINE_VERSION",json.dumps({"version":"2.0","video_generation":"disabled","tts":"disabled","advertiser_media":"original"},ensure_ascii=False),flush=True)
