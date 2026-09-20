import os, html, json, threading, time
from fastapi import FastAPI, Query
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from .db import connect
from .scoring import calc, tender_economics
from .telegram import notify
from .outreach import send
from .ingest import refresh
from .review import review_unknown

load_dotenv()
DB=os.getenv("DB_PATH") or ("/data/deals.db" if os.path.isdir("/data") else "deals.db")
app=FastAPI(title="DealFinder Mobile v5-TEKHSTROY")

class Buyer(BaseModel):
    source:str; external_id:str|None=None; title:str; description:str=""; url:str=""; contact:str=""; budget_rub:float|None=None; city:str=""
class Supplier(BaseModel):
    name:str; website:str=""; email:str=""; phone:str=""; categories:str=""
class Match(BaseModel):
    buyer_id:int; supplier_id:int; buy_rub:float; logistics_rub:float=0

@app.on_event("startup")
def startup():
    connect(DB).close()
    if os.getenv("AUTO_REFRESH","true").lower()=="true":
        threading.Thread(target=_background_refresh, daemon=True).start()

_last_bg_error = None
_last_bg_result = None
_refresh_lock = threading.Lock()
_review_lock = threading.Lock()

def _run_review_background(result):
    global _last_bg_result
    if result.get("status") not in ("ok","fallback") or os.getenv("AUTO_REVIEW","true").lower()!="true":
        return
    if not _review_lock.acquire(blocking=False):
        return
    try:
        reviewed=review_unknown(DB, int(os.getenv("AUTO_REVIEW_LIMIT","20")))
        current=dict(_last_bg_result or result)
        current["review"]=reviewed
        _last_bg_result=current
    except Exception as e:
        current=dict(_last_bg_result or result)
        current["review_error"]=f"{type(e).__name__}: {e}"
        _last_bg_result=current
    finally:
        _review_lock.release()

def _background_refresh():
    global _last_bg_error, _last_bg_result
    time.sleep(3)
    while True:
        try:
            with _refresh_lock:
                result = refresh()
            _last_bg_result = result
            if result.get("status") in ("ok","fallback"):
                _last_bg_error = None
                if os.getenv("AUTO_REVIEW","true").lower()=="true":
                    threading.Thread(target=_run_review_background,args=(result,),daemon=True).start()
            else:
                _last_bg_error = result.get("error") or "refresh returned non-ok"
        except Exception as e:
            _last_bg_error = f"{type(e).__name__}: {e}"
            _last_bg_result = {"status":"error","error":_last_bg_error}
        time.sleep(int(os.getenv("REFRESH_SECONDS","3600")))

def _run_refresh_once():
    global _last_bg_error, _last_bg_result
    with _refresh_lock:
        result = refresh()
    _last_bg_result = result
    if result.get("status") in ("ok","fallback"):
        _last_bg_error = None
        if os.getenv("AUTO_REVIEW","true").lower()=="true":
            try:
                result = dict(result)
                result["review"] = review_unknown(DB, int(os.getenv("AUTO_REVIEW_LIMIT","20")))
            except Exception as e:
                result = dict(result)
                result["review_error"] = f"{type(e).__name__}: {e}"
    else:
        _last_bg_error = result.get("error") or "refresh returned non-ok"
    return result

@app.get("/api/hot")
def hot(limit:int=50):
    c=connect(DB)
    min_r=float(os.getenv("DEAL_MIN_RUB","10000000")); max_r=float(os.getenv("DEAL_MAX_RUB","90000000"))
    rows=c.execute("""SELECT * FROM buyers WHERE budget_rub BETWEEN ? AND ? AND fit_status='ЗАХОДИМ' AND advance_pct >= ?
                      ORDER BY advance_pct DESC, created_at DESC LIMIT ?""",(min_r,max_r,float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")),limit)).fetchall()
    c.close()
    result=[]
    min_margin=float(os.getenv("MIN_MARGIN_RUB","200000"))
    min_margin_pct=float(os.getenv("MIN_MARGIN_PCT","10"))
    for r in rows:
        d=dict(r)
        e=tender_economics(d["budget_rub"],d["advance_pct"],security_rub=d.get("security_rub") or 0,
                           description=(d.get("title") or "")+" "+(d.get("description") or ""),
                           document_text=d.get("document_text") or "")
        d["economics"]=e
        d["economic_status"]="ЗАХОДИМ" if e and e["margin_rub"]>=min_margin and e["margin_pct"]>=min_margin_pct else "ПРОВЕРИТЬ ЭКОНОМИКУ"
        if d["economic_status"]=="ЗАХОДИМ":
            result.append(d)
    return result

@app.post("/api/review")
def api_review(limit:int=30):
    return review_unknown(DB,limit)

@app.get("/api/economics/{buyer_id}")
def economics(buyer_id:int):
    c=connect(DB); b=c.execute("SELECT * FROM buyers WHERE id=?",(buyer_id,)).fetchone(); c.close()
    if not b: return {"error":"not found"}
    e=tender_economics(b["budget_rub"],b["advance_pct"],security_rub=b["security_rub"] or 0,description=(b["title"] or "")+" "+(b["description"] or ""),document_text=b["document_text"] or "")
    return {"buyer":dict(b),"economics":e}

@app.get("/api/buyers")
def buyers(limit:int=100):
    c=connect(DB); rows=c.execute("SELECT * FROM buyers ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall(); c.close()
    return [dict(r) for r in rows]

@app.get("/api/suppliers")
def suppliers(limit:int=100):
    c=connect(DB); rows=c.execute("SELECT * FROM suppliers ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall(); c.close()
    return [dict(r) for r in rows]

@app.get("/api/health")
def health():
    try:
        c=connect(DB)
        buyers=c.execute("SELECT count(*) n FROM buyers").fetchone()["n"]
        hot=c.execute("SELECT count(*) n FROM buyers WHERE fit_status='ЗАХОДИМ'").fetchone()["n"]
        c.close()
        return {"status":"ok","buyers":buyers,"hot":hot,"profile":"ТЕХСТРОЙ","experience_contracts":9,"experience_total_rub":101822407.84,"search_keywords":["клининг","уборка территорий","снег","очистка крыш"]}
    except Exception as e:
        return {"status":"error","error":str(e)}

@app.get("/api/version")
def version():
    return {"version":"v5-TEKHSTROY","source":"GosPlan API v2","gosplan":"enabled","advance_min_pct":20.0,"profile":"ТЕХСТРОЙ","experience_contracts":9,"experience_total_rub":101822407.84,"manual_refresh":True}

@app.get("/api/stats")
def stats():
    c=connect(DB)
    buyers=c.execute("SELECT count(*) n FROM buyers").fetchone()["n"]
    suppliers=c.execute("SELECT count(DISTINCT source) n FROM buyers WHERE source IS NOT NULL AND source <> ''").fetchone()["n"]
    min_r=float(os.getenv("DEAL_MIN_RUB","10000000")); max_r=float(os.getenv("DEAL_MAX_RUB","90000000"))
    hot=c.execute("SELECT count(*) n FROM buyers WHERE budget_rub BETWEEN ? AND ? AND fit_status='ЗАХОДИМ' AND advance_pct >= ?",(min_r,max_r,float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")))).fetchone()["n"]
    c.close()
    return {"buyers":buyers,"suppliers":suppliers,"hot":hot}

def _manual_refresh():
    global _last_bg_error, _last_bg_result
    if not _refresh_lock.acquire(blocking=False):
        return {"status":"busy","error":"Обновление уже выполняется","last_result":_last_bg_result}
    try:
        result=refresh()
        _last_bg_result=result
        if result.get("status") in ("ok","fallback"):
            _last_bg_error=None
            if os.getenv("AUTO_REVIEW","true").lower()=="true":
                threading.Thread(target=_run_review_background,args=(result,),daemon=True).start()
        else:
            _last_bg_error=result.get("error") or "refresh returned non-ok"
        return result
    except Exception as e:
        _last_bg_error=f"{type(e).__name__}: {e}"
        _last_bg_result={"status":"error","error":_last_bg_error}
        return _last_bg_result
    finally:
        _refresh_lock.release()

@app.post("/api/refresh")
def api_refresh():
    return _manual_refresh()

@app.get("/api/refresh")
def api_refresh_get():
    return _manual_refresh()

@app.get("/api/refresh-status")
def refresh_status():
    running = _refresh_lock.locked() or _review_lock.locked()
    result = _last_bg_result or {}
    return {
        "status": "running" if running else (result.get("status") if result else "idle"),
        "running": running,
        "last_error": _last_bg_error,
        "last_result": result,
    }

@app.get("/api/test-gosplan")
def test_gosplan():
    import httpx
    key=os.getenv("GOSPLAN_API_KEY","").strip()
    base=os.getenv("GOSPLAN_BASE_URL","https://v2.gosplan.info" if key else "https://v2test.gosplan.info").rstrip("/")
    headers={"User-Agent":"DealFinder/diagnostic","Accept":"application/json"}
    if key: headers["X-API-Key"]=key
    try:
        r=httpx.get(base+"/fz44/purchases",params={"limit":1,"skip":0},headers=headers,timeout=12,follow_redirects=True)
        return {"status":"ok" if r.is_success else "error","http_status":r.status_code,"base":base,"body":r.text[:1000]}
    except Exception as e:
        return {"status":"error","base":base,"error":f"{type(e).__name__}: {e}"}

@app.get("/api/diagnostics")
def diagnostics():
    c=connect(DB)
    total=c.execute("SELECT count(*) n FROM buyers").fetchone()["n"]
    hot=c.execute("SELECT count(*) n FROM buyers WHERE fit_status='ЗАХОДИМ'").fetchone()["n"]
    by_status={}
    for row in c.execute("SELECT fit_status, count(*) n FROM buyers GROUP BY fit_status").fetchall():
        by_status[row["fit_status"] or "null"] = row["n"]
    sources=c.execute("SELECT count(DISTINCT source) n FROM buyers WHERE source IS NOT NULL AND source <> ''").fetchone()["n"]
    c.close()
    return {
        "status":"ok",
        "db_path":DB,
        "buyers":total,
        "sources":sources,
        "hot":hot,
        "by_fit_status":by_status,
        "api_key_configured":bool(os.getenv("GOSPLAN_API_KEY","").strip()),
        "endpoints":os.getenv("GOSPLAN_ENDPOINTS","/fz44/purchases,/fz223/purchases").split(","),
        "min_rub":float(os.getenv("DEAL_MIN_RUB","10000000")),
        "max_rub":float(os.getenv("DEAL_MAX_RUB","90000000")),
        "min_advance_pct":float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")),
        "bg_limit_rub":float(os.getenv("DEAL_BG_LIMIT_RUB","17000000")),
        "last_bg_error":_last_bg_error,
        "last_bg_result":{k:_last_bg_result.get(k) for k in ("status","loaded","raw","pages","source","server","api_mode","error","diagnostics") if _last_bg_result and k in _last_bg_result} if _last_bg_result else None,
    }

@app.post("/buyers")
def buyer(b:Buyer):
    c=connect(DB)
    c.execute("INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city) VALUES(?,?,?,?,?,?,?,?)",
              (b.source,b.external_id,b.title,b.description,b.url,b.contact,b.budget_rub,b.city))
    c.commit(); cid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.close()
    return {"id":cid}

@app.post("/suppliers")
def supplier(s:Supplier):
    c=connect(DB)
    c.execute("INSERT INTO suppliers(name,website,email,phone,categories) VALUES(?,?,?,?,?)",(s.name,s.website,s.email,s.phone,s.categories))
    c.commit(); cid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.close()
    return {"id":cid}

@app.post("/match")
def match(m:Match):
    c=connect(DB)
    b=c.execute("SELECT * FROM buyers WHERE id=?",(m.buyer_id,)).fetchone()
    if not b: c.close(); return {"error":"buyer not found"}
    e=calc(b["budget_rub"],m.buy_rub,m.logistics_rub)
    if not e: c.close(); return {"error":"bad numbers"}
    c.execute("INSERT OR REPLACE INTO matches(buyer_id,supplier_id,buy_rub,sell_rub,margin_rub,margin_pct,status) VALUES(?,?,?,?,?,?,?)",
              (m.buyer_id,m.supplier_id,m.buy_rub,b["budget_rub"],e["margin_rub"],e["margin_pct"],"new"))
    c.commit(); c.close()
    return e

@app.post("/outreach")
def outreach(to:str, subject:str, body:str):
    return send(to,subject,body)

@app.get("/", response_class=HTMLResponse)
def home():
    return '''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DealFinder — ТЕХСТРОЙ</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f7;margin:0;color:#111}.wrap{max-width:760px;margin:auto;padding:16px}
.head{display:flex;justify-content:space-between;align-items:center}.badge{background:#111;color:#fff;padding:6px 10px;border-radius:20px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.stat,.card{background:#fff;border-radius:16px;padding:14px;margin-top:10px;box-shadow:0 1px 4px #0001}
.stat b{display:block;font-size:24px}.card h3{margin:0 0 7px;font-size:17px}.money{font-size:21px;font-weight:700}.muted{color:#777;font-size:13px}
.btn{display:inline-block;margin-top:10px;background:#111;color:#fff;padding:10px 13px;border-radius:12px;text-decoration:none;border:0}
.refresh{cursor:pointer}@media(max-width:500px){.grid{grid-template-columns:1fr 1fr}.grid .stat:last-child{grid-column:span 2}}
</style><div class="wrap"><div class="head"><h1>DealFinder <span class="muted">ТЕХСТРОЙ</span></h1><button class="badge refresh" onclick="refresh()">ОБНОВИТЬ</button></div>
<div class="grid"><div class="stat"><span class="muted">Найдено закупок</span><b id="buyers">—</b></div><div class="stat"><span class="muted">Источники</span><b id="suppliers">—</b></div><div class="stat"><span class="muted">Горячие</span><b id="hot">—</b></div></div>
<h2>Горячие закупки</h2><div id="list">Загрузка…</div></div>
<script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){try{const sr=await fetch('/api/stats');if(!sr.ok)throw new Error('stats HTTP '+sr.status);const s=await sr.json();for(let k of ['buyers','suppliers','hot']){let el=document.getElementById(k);if(el)el.textContent=s[k]??0}const ar=await fetch('/api/hot');if(!ar.ok)throw new Error('hot HTTP '+ar.status);const a=await ar.json();const el=document.getElementById('list');el.innerHTML=a.length?'':'<div class="card">Пока подходящих закупок нет.</div>';a.forEach(x=>{const e=x.economics||{};el.innerHTML+=`<div class="card"><h3>ЗАХОДИМ · ${esc(x.title)}</h3><div class="muted">${esc(x.city||'Регион не указан')} · НМЦК ${Number(x.budget_rub||0).toLocaleString('ru-RU')} ₽ · аванс ${x.advance_pct??'—'}%</div><p>${esc((x.description||'').slice(0,280))}</p><div class="money">Маржа: ${Number(e.margin_rub||0).toLocaleString('ru-RU')} ₽</div><div class="muted">Свои деньги: ${Number(e.own_cash_needed_rub||0).toLocaleString('ru-RU')} ₽ · цена контракта: ${Number(e.contract_price||0).toLocaleString('ru-RU')} ₽</div>${x.deadline?'<div class="muted">Срок подачи: '+esc(x.deadline)+'</div>':''}${x.url?`<a class="btn" href="${esc(x.url)}" target="_blank">Открыть закупку</a>`:''}</div>`})}catch(e){document.getElementById('list').innerHTML='<div class="card">Ошибка загрузки: '+esc(e.message)+'</div>'}}
async function refresh(){const b=document.querySelector('.refresh');if(b){b.disabled=true;b.textContent='ОБНОВЛЕНИЕ…'}try{const url=new URL('/api/refresh',window.location.href).href;const r=await fetch(url,{method:'GET',cache:'no-store',headers:{'Accept':'application/json'}});const raw=await r.text();let x;try{x=JSON.parse(raw)}catch(_){throw new Error('HTTP '+r.status+': сервер вернул не JSON')}if(!r.ok){throw new Error('HTTP '+r.status+': '+(x.error||x.status||'ошибка сервера'))}if(x.status==='busy'){alert('Обновление уже выполняется. Результаты обновятся автоматически.');await load();return}else if(x.status==='started'){alert('Обновление запущено. Результаты появятся автоматически.');pollRefreshStatus();return}else if(x.status==='rate_limited'){alert('Источник временно ограничил запросы. Повторить через '+(x.retry_after||300)+' сек.')}else if(x.status!=='ok'&&x.status!=='fallback'){alert('Ошибка источника: '+(x.error||x.warning||('статус '+x.status)+' | raw '+(x.raw??0)));}else if(x.loaded===0){alert('Источник ответил, но 0 закупок прошло фильтры. RAW: '+(x.raw||0)+' | страницы: '+(x.pages||0))}else{alert('Загружено: '+x.loaded+' закупок')}}catch(e){alert('Ошибка соединения: '+(e&&e.message?e.message:String(e)))}finally{if(b){b.disabled=false;b.textContent='ОБНОВИТЬ'}}await load()}async function pollRefreshStatus(){for(let i=0;i<300;i++){try{const r=await fetch('/api/refresh-status',{cache:'no-store'});const s=await r.json();if(!s.running){await load();if(s.status==='error'){const msg=s.last_error||(s.last_result&&s.last_result.error)||'неизвестная ошибка';alert('Ошибка источника: '+msg)}return}}catch(e){}await new Promise(r=>setTimeout(r,2000))}await load()}load();setInterval(load,60000)
</script></html>'''
