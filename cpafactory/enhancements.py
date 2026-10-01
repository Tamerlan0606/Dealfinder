import os, re, json, html, urllib.request, urllib.parse, time, hashlib
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
        alters = [
            ("offers","video_url","text"),
            ("offers","video_url2","text"),
            ("offers","demand_count","real default 0"),
            ("offers","demand_checked_at","text"),
            ("offers","yandex_promise","real default 0"),
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
        for table, column, ddl in alters:
            stmt = f"alter table {table} add column {'if not exists ' if not core.using_sqlite() else ''}{column} {ddl}"
            if core.using_sqlite():
                try:
                    c.execute(stmt)
                except Exception:
                    pass
            else:
                c.execute(stmt)

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

        if core.using_sqlite():
            c.execute("""create table if not exists telegram_publications(
              dedup_key text primary key, queue_id integer, content_id integer, status text not null,
              message_id text, external_url text, created_at text default CURRENT_TIMESTAMP,
              published_at text, last_error text)""")
        else:
            c.execute("""create table if not exists telegram_publications(
              dedup_key text primary key, queue_id bigint, content_id int, status text not null,
              message_id text, external_url text, created_at timestamptz default now(),
              published_at timestamptz, last_error text)""")

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
    """Rank offers by expected economics, then demand and creative readiness.

    EPC is the strongest observed monetisation signal. When EPC is unavailable,
    CR * payout is used as a conservative proxy. Demand is logarithmic so a
    popular low-paying product cannot overwhelm a materially better offer.
    """
    import math
    with core.db() as c:
        rows=c.execute("""select o.*,count(e.id) clicks from offers o left join click_events e on e.offer_id=o.id
          where o.active=true group by o.id""").fetchall()
    out=[]
    for rr in rows:
        r=dict(rr)
        if not _traffic_ok(r): continue
        seller_referral=(str(r.get("source") or "")=="yandex_market_seller")
        media=3 if r.get("video_url") else (2 if r.get("image_url") else (1 if seller_referral else 0))
        if not media: continue
        epc=max(float(r.get("epc") or 0),0.0)
        cr=max(float(r.get("cr") or 0),0.0)
        demand=max(float(r.get("demand_count") or 0),0.0)
        clicks=max(int(r.get("clicks") or 0),0)
        payout=max(_effective_payout(r),0.0)
        # Networks commonly expose CR as percent. This proxy is only used when
        # EPC is absent, preventing payout alone from selecting an unconvertible offer.
        proxy_epc=(min(cr,100.0)/100.0)*payout if payout else 0.0
        expected_epc=epc if epc>0 else proxy_epc
        demand_factor=1.0 + min(math.log1p(demand),12.0)/12.0
        confidence=1.0 + min(math.log1p(clicks),7.0)*0.03
        media_factor=1.05 if media==3 else 1.0
        economic_value=expected_epc*demand_factor*confidence*media_factor
        # Small tie-break quality term; it cannot dominate actual economics.
        score=economic_value + min(cr,100.0)*0.0001 + min(math.log1p(payout),12.0)*0.0001
        r["effective_payout"]=round(payout,2)
        r["expected_epc"]=round(expected_epc,4)
        r["economic_value"]=round(economic_value,6)
        r["score"]=round(score,6)
        out.append(r)
    out.sort(key=lambda x:(x["economic_value"],x["expected_epc"],x["effective_payout"],float(x.get("demand_count") or 0),int(x["id"])),reverse=True)
    return out[:max(1,min(int(limit),50))]

core.cpa_top=distribution_top

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




def _public_base_url():
    return (os.getenv("CPA_PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://cpafactory-web.onrender.com").rstrip("/")

def _telegram_configured():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip() and os.getenv("TELEGRAM_CHAT_ID","").strip())

def _telegram_send(text):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not token or not chat:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are not configured")
    body=json.dumps({"chat_id":chat,"text":text,"disable_web_page_preview":False},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",data=body,headers={"Content-Type":"application/json","User-Agent":"CPAFactory/5.0"},method="POST")
    with urllib.request.urlopen(req,timeout=20) as r:
        payload=json.loads(r.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("Telegram API rejected message")
    return payload["result"]

def publish_telegram(limit=1):
    """Publish Telegram rows with persistent idempotency.

    Safety rules:
    - Never auto-publish from ephemeral SQLite in production-like operation.
    - Persist a deterministic dedup key BEFORE calling Telegram.
    - A successfully reserved/published content+channel fingerprint cannot be sent again,
      even if distribution_queue is recreated or a Render instance restarts.
    """
    if not _telegram_configured():
        return {"status":"not_configured","published":0}

    # /tmp SQLite is ephemeral on Render. Publishing from it caused the same queue row
    # to be recreated after restarts and sent repeatedly. Fail closed instead.
    if core.using_sqlite():
        print("CPA_TELEGRAM_BLOCKED_EPHEMERAL_DB", flush=True)
        return {"status":"blocked_ephemeral_db","published":0,
                "error":"Telegram auto-publish requires persistent DATABASE_URL/Postgres"}

    published=[]; errors=[]; skipped=[]
    for _ in range(max(1,min(int(limit),5))):
        with core.db() as c:
            row=c.execute("""select q.id queue_id,q.content_id,c.offer_id,c.variants_json,c.title,o.name offer_name
              from distribution_queue q join content c on c.id=q.content_id join offers o on o.id=c.offer_id
              where q.channel='telegram' and q.status='planned'
              order by q.id asc limit 1""").fetchone()
            if not row: break

            qid=int(row["queue_id"])
            variants=json.loads(row["variants_json"] or "{}")
            body_text=_text(variants.get("commercial") or row["title"] or row["offer_name"])
            # Stable across queue recreation/restarts: same offer + same commercial copy + telegram.
            material=f"telegram|offer:{int(row['offer_id'])}|{body_text}".encode("utf-8")
            dedup_key=hashlib.sha256(material).hexdigest()

            # Reserve idempotency key atomically before any external side effect.
            reserved=c.execute("""insert into telegram_publications(dedup_key,queue_id,content_id,status)
              values(%s,%s,%s,'sending') on conflict(dedup_key) do nothing returning dedup_key""",
              (dedup_key,qid,int(row["content_id"]))).fetchone()

            if not reserved:
                c.execute("""update distribution_queue set status='duplicate_suppressed',
                  last_error='duplicate telegram publication suppressed' where id=%s""",(qid,))
                skipped.append({"queue_id":qid,"reason":"duplicate_suppressed","dedup_key":dedup_key[:12]})
                print("CPA_TELEGRAM_DUPLICATE_SUPPRESSED",
                      json.dumps(skipped[-1],ensure_ascii=False),flush=True)
                continue

            claimed=c.execute("""update distribution_queue set status='publishing',last_error=null
              where id=%s and status='planned' returning id""",(qid,)).fetchone()
            if not claimed:
                c.execute("delete from telegram_publications where dedup_key=%s and status='sending'",(dedup_key,))
                continue

        try:
            text_to_send=body_text
            relative=f"/r/{int(row['content_id'])}?source=telegram&channel=telegram"
            text_to_send=text_to_send.replace(
                f"/r/{int(row['content_id'])}?source=content&channel=landing",
                _public_base_url()+relative)
            if relative not in text_to_send and _public_base_url()+relative not in text_to_send:
                text_to_send += "\n\n"+_public_base_url()+relative

            result=_telegram_send(text_to_send[:4096])
            mid=str(result.get("message_id",""))
            chat=result.get("chat") or {}; username=chat.get("username")
            external_url=(f"https://t.me/{username}/{mid}" if username and mid else None)

            with core.db() as c:
                c.execute("""update distribution_queue set status='published',external_id=%s,
                  external_url=%s,published_at=current_timestamp,last_error=null where id=%s""",
                  (mid,external_url,qid))
                c.execute("update content set status='published' where id=%s",(int(row["content_id"]),))
                c.execute("""update telegram_publications set status='published',message_id=%s,
                  external_url=%s,published_at=current_timestamp,last_error=null where dedup_key=%s""",
                  (mid,external_url,dedup_key))

            published.append({"queue_id":qid,"message_id":mid,"url":external_url,
                              "dedup_key":dedup_key[:12]})
            print("CPA_TELEGRAM_PUBLISHED",json.dumps(published[-1],ensure_ascii=False),flush=True)

        except Exception as e:
            err=f"{type(e).__name__}: {e}"[:1000]
            with core.db() as c:
                c.execute("update distribution_queue set status='planned',last_error=%s where id=%s",(err,qid))
                # Allow retry only when Telegram call failed.
                c.execute("delete from telegram_publications where dedup_key=%s and status='sending'",(dedup_key,))
            errors.append({"queue_id":qid,"error":err})
            print("CPA_TELEGRAM_ERROR",json.dumps(errors[-1],ensure_ascii=False),flush=True)
            break

    return {"status":"ok" if not errors else "error","published":len(published),
            "items":published,"duplicates_suppressed":len(skipped),"skipped":skipped,"errors":errors}

@core.app.post("/api/telegram/publish")
def telegram_publish_now(x_admin_token: str|None=Header(default=None)):
    core.require_admin(x_admin_token)
    return publish_telegram(int(os.getenv("TELEGRAM_PUBLISH_BATCH","1") or 1))

@core.app.get("/api/telegram/status")
def telegram_status():
    with core.db() as c:
        planned=c.execute("select count(*) n from distribution_queue where channel='telegram' and status='planned'").fetchone()["n"]
        last=c.execute("select * from distribution_queue where channel='telegram' and status='published' order by id desc limit 1").fetchone()
    return {"configured":_telegram_configured(),"planned":int(planned),"last_published":dict(last) if last else None}

@core.app.get("/api/wordstat/status")
def wordstat_status():
    try:
        import wordstat_monitor
        wordstat_monitor.init_schema()
        with wordstat_monitor.db() as c:
            run=wordstat_monitor.exec_sql(c,"select * from wordstat_runs order by id desc limit 1").fetchone()
            top=wordstat_monitor.exec_sql(c,"select phrase,count,seed_phrase from wordstat_queries order by run_date desc,count desc limit 20").fetchall()
        return {"configured":bool(os.getenv("YANDEX_WORDSTAT_API_KEY") and os.getenv("YANDEX_WORDSTAT_FOLDER_ID")),
                "folder_configured":bool(os.getenv("YANDEX_WORDSTAT_FOLDER_ID")),
                "last_run":dict(run) if run else None,
                "top":[dict(x) for x in top]}
    except Exception as e:
        return {"configured":False,"error":f"{type(e).__name__}: {e}"}

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

def _wordstat_daily_worker(today, wordstat_monitor):
    try:
        result=wordstat_monitor.run()
        if result==0:
            _WORDSTAT_DAILY_DATE["value"]=today
            print("CPA_WORDSTAT_DAILY_OK",flush=True)
        else:
            _WORDSTAT_DAILY_DATE["value"]=today
            print("CPA_WORDSTAT_DAILY_DEFERRED",json.dumps({"date":today,"exit_code":result},ensure_ascii=False),flush=True)
    except Exception as e:
        print("CPA_WORDSTAT_DAILY_ERROR",type(e).__name__,str(e),flush=True)
    finally:
        try:
            _WORDSTAT_DAILY_LOCK.release()
        except Exception:
            pass

def _wordstat_daily_hook():
    if not os.getenv("YANDEX_WORDSTAT_API_KEY") or not os.getenv("YANDEX_WORDSTAT_FOLDER_ID"):
        return
    import datetime, wordstat_monitor
    today=datetime.datetime.utcnow().date().isoformat()
    if _WORDSTAT_DAILY_DATE["value"]==today: return
    if not _WORDSTAT_DAILY_LOCK.acquire(blocking=False): return
    __import__("threading").Thread(
        target=_wordstat_daily_worker,
        args=(today,wordstat_monitor),
        daemon=True,
        name="cpa-wordstat-daily"
    ).start()

_original_cycle=core._autopilot_cycle
def _cycle_with_wordstat():
    result=_original_cycle()
    try:
        tg=publish_telegram(int(os.getenv("TELEGRAM_PUBLISH_BATCH","1") or 1))
        print("CPA_TELEGRAM_CYCLE",json.dumps(tg,ensure_ascii=False),flush=True)
    except Exception as e: print("CPA_TELEGRAM_CYCLE_ERROR",type(e).__name__,str(e),flush=True)
    try: _wordstat_daily_hook()
    except Exception as e: print("CPA_WORDSTAT_SCHEDULE_ERROR",type(e).__name__,str(e),flush=True)
    return result
core._autopilot_cycle=_cycle_with_wordstat

print("CPA_DISTRIBUTION_ENGINE_VERSION",json.dumps({"version":"2.0","video_generation":"disabled","tts":"disabled","advertiser_media":"original"},ensure_ascii=False),flush=True)
