import os, html
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from .db import connect
from .scoring import calc
from .telegram import notify
from .outreach import send
from .ingest import refresh

load_dotenv()
DB=os.getenv("DB_PATH","deals.db")
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

@app.get("/api/hot")
def hot(limit:int=50):
    c=connect(DB)
    min_r=float(os.getenv("DEAL_MIN_RUB","10000000")); max_r=float(os.getenv("DEAL_MAX_RUB","90000000"))
    rows=c.execute("""SELECT * FROM buyers WHERE budget_rub BETWEEN ? AND ? AND fit_status='ЗАХОДИМ' AND advance_pct >= ?
                      ORDER BY advance_pct DESC, created_at DESC LIMIT ?""",(min_r,max_r,float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")),limit)).fetchall()
    c.close()
    return [dict(r) for r in rows]

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
    return {"version":"v5-TEKHSTROY","source":"GosPlan API v2","gosplan":"enabled","advance_min_pct":float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")),"profile":"ТЕХСТРОЙ","experience_contracts":9,"experience_total_rub":101822407.84,"manual_refresh":True}

@app.get("/api/stats")
def stats():
    c=connect(DB)
    buyers=c.execute("SELECT count(*) n FROM buyers").fetchone()["n"]
    suppliers=c.execute("SELECT count(*) n FROM suppliers").fetchone()["n"]
    min_r=float(os.getenv("DEAL_MIN_RUB","10000000")); max_r=float(os.getenv("DEAL_MAX_RUB","90000000"))
    hot=c.execute("SELECT count(*) n FROM buyers WHERE budget_rub BETWEEN ? AND ? AND fit_status='ЗАХОДИМ' AND advance_pct >= ?",(min_r,max_r,float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")))).fetchone()["n"]
    c.close()
    return {"buyers":buyers,"suppliers":suppliers,"hot":hot}

@app.post("/api/refresh")
def api_refresh():
    return refresh()

@app.get("/api/diagnostics")
def diagnostics():
    c=connect(DB)
    total=c.execute("SELECT count(*) n FROM buyers").fetchone()["n"]
    hot=c.execute("SELECT count(*) n FROM buyers WHERE fit_status='ЗАХОДИМ'").fetchone()["n"]
    c.close()
    return {"status":"ok","db_path":DB,"buyers":total,"hot":hot,"api_key_configured":bool(os.getenv("GOSPLAN_API_KEY","").strip()),"endpoints":os.getenv("GOSPLAN_ENDPOINTS","/fz44/purchases,/fz223/purchases").split(","),"min_rub":float(os.getenv("DEAL_MIN_RUB","10000000")),"max_rub":float(os.getenv("DEAL_MAX_RUB","90000000")),"min_advance_pct":float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")),"bg_limit_rub":float(os.getenv("DEAL_BG_LIMIT_RUB","17000000"))}

@app.post("/buyers")
def buyer(x:Buyer):
    c=connect(DB)
    c.execute("INSERT OR IGNORE INTO buyers(source,external_id,title,description,url,contact,budget_rub,city) VALUES(?,?,?,?,?,?,?,?)",
              (x.source,x.external_id,x.title,x.description,x.url,x.contact,x.budget_rub,x.city)); c.commit()
    r=c.execute("SELECT * FROM buyers WHERE source=? AND external_id=?",(x.source,x.external_id)).fetchone(); c.close()
    return dict(r)

@app.post("/suppliers")
def supplier(x:Supplier):
    c=connect(DB); cur=c.execute("INSERT INTO suppliers(name,website,email,phone,categories) VALUES(?,?,?,?,?)",(x.name,x.website,x.email,x.phone,x.categories)); c.commit()
    r=c.execute("SELECT * FROM suppliers WHERE id=?",(cur.lastrowid,)).fetchone(); c.close(); return dict(r)

@app.post("/match")
def match(x:Match):
    c=connect(DB); b=c.execute("SELECT * FROM buyers WHERE id=?",(x.buyer_id,)).fetchone(); s=c.execute("SELECT * FROM suppliers WHERE id=?",(x.supplier_id,)).fetchone()
    if not b or not s: c.close(); return {"error":"not found"}
    e=calc(b["budget_rub"],x.buy_rub,x.logistics_rub)
    hot=e and e["margin_rub"]>=float(os.getenv("MIN_MARGIN_RUB","200000")) and e["margin_pct"]>=float(os.getenv("MIN_MARGIN_PCT","10"))
    status="hot" if hot else "watch"
    c.execute("INSERT OR REPLACE INTO matches(buyer_id,supplier_id,buy_rub,sell_rub,margin_rub,margin_pct,status) VALUES(?,?,?,?,?,?,?)",(x.buyer_id,x.supplier_id,x.buy_rub,b["budget_rub"],e["margin_rub"],e["margin_pct"],status)); c.commit(); c.close()
    if hot: notify(f"🔥 ГОРЯЧАЯ СДЕЛКА\n{b['title']}\n{b['url']}")
    return {"status":status,"economics":e,"buyer":dict(b),"supplier":dict(s)}

@app.post("/outreach")
def outreach(to:str,subject:str,body:str): return send(to,subject,body)

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return '''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DealFinder v2-EIS</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f7;margin:0;color:#111}.wrap{max-width:760px;margin:auto;padding:16px}
.head{display:flex;justify-content:space-between;align-items:center}.badge{background:#111;color:#fff;padding:6px 10px;border-radius:20px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.stat,.card{background:#fff;border-radius:16px;padding:14px;margin-top:10px;box-shadow:0 1px 4px #0001}
.stat b{display:block;font-size:24px}.card h3{margin:0 0 7px;font-size:17px}.money{font-size:21px;font-weight:700}.muted{color:#777;font-size:13px}
.btn{display:inline-block;margin-top:10px;background:#111;color:#fff;padding:10px 13px;border-radius:12px;text-decoration:none;border:0}
.refresh{cursor:pointer}@media(max-width:500px){.grid{grid-template-columns:1fr 1fr}.grid .stat:last-child{grid-column:span 2}}
</style><div class="wrap"><div class="head"><h1>DealFinder</h1><button class="badge refresh" onclick="refresh()">ОБНОВИТЬ</button></div>
<div class="grid"><div class="stat"><span class="muted">Найдено закупок</span><b id="buyers">—</b></div><div class="stat"><span class="muted">Источники</span><b id="suppliers">—</b></div><div class="stat"><span class="muted">Горячие</span><b id="hot">—</b></div></div>
<h2>Горячие закупки</h2><div id="list">Загрузка…</div></div>
<script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){let s=await fetch('/api/stats').then(r=>r.json());for(let k in s)document.getElementById(k).textContent=s[k];
let a=await fetch('/api/hot').then(r=>r.json());let el=document.getElementById('list');el.innerHTML=a.length?'':'<div class="card">Пока подходящих закупок нет.</div>';
a.forEach(x=>{el.innerHTML+=`<div class="card"><h3>${esc(x.title)}</h3><div class="muted">${esc(x.city)} · ${Number(x.budget_rub||0).toLocaleString('ru-RU')} ₽</div><p>${esc((x.description||'').slice(0,400))}</p>${x.url?`<a class="btn" href="${esc(x.url)}" target="_blank">Открыть закупку</a>`:''}</div>`})}
async function refresh(){const r=await fetch('/api/refresh',{method:'POST'});const x=await r.json();if(x.status!=='ok'){alert('Ошибка источника: '+(x.error||'неизвестная ошибка'))}else if(x.loaded===0){alert('Источник ответил, но 0 закупок прошло фильтры. RAW: '+(x.raw||0)+' | страницы: '+(x.pages||0)+' | сервер: '+(x.server||''))}else{alert('Загружено: '+x.loaded)}await load()}load();setInterval(load,60000)
</script></html>'''
