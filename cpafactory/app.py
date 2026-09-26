import os, re, sqlite3
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from psycopg.rows import dict_row

app = FastAPI(title="CPA Factory")

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

@app.on_event("startup")
def startup():
    init()

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

@app.post("/api/offers")
async def add_offer(request: Request):
    x=await request.json()
    if not x.get("name"): raise HTTPException(400, "name обязателен")
    with db() as c:
        return c.execute("""insert into offers(name,merchant,price,commission,tracking_url,traffic_rules)
          values(%s,%s,%s,%s,%s,%s) returning *""",
          (x.get("name"),x.get("merchant"),x.get("price") or 0,x.get("commission") or 0,
           x.get("tracking_url"),x.get("traffic_rules"))).fetchone()

@app.post("/api/offers/import")
async def import_offers(request: Request):
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

@app.get("/api/content")
def content():
    with db() as c:
        return c.execute("""select content.*, offers.name offer_name
          from content left join offers on offers.id=content.offer_id order by content.id desc""").fetchall()

@app.post("/api/content")
async def add_content(request: Request):
    x=await request.json()
    with db() as c:
        return c.execute("""insert into content(offer_id,title,script,platform,status)
          values(%s,%s,%s,%s,%s) returning *""",
          (x.get("offer_id"),x.get("title"),x.get("script"),x.get("platform","rutube"),x.get("status","draft"))).fetchone()

@app.post("/api/content/generate")
async def generate_content(request: Request):
    x=await request.json()
    offer_id=int(x["offer_id"])
    with db() as c:
        o=c.execute("select * from offers where id=%s", (offer_id,)).fetchone()
        if not o: raise HTTPException(404, "Оффер не найден")
        name=o["name"]; price=o["price"] or 0; commission=o["commission"] or 0
        title=f"{name}: стоит ли покупать? Цена {price:g} ₽"
        script=(f"Сегодня разбираем товар «{name}». Цена — {price:g} ₽. "
                f"Смотрим характеристики, кому он подходит и на что обратить внимание перед покупкой. "
                f"Ссылка на актуальную цену — в описании. Переход по ссылке помогает отследить предложение. "
                f"Потенциальная комиссия партнёра: до {commission:g} ₽.")
        return c.execute("""insert into content(offer_id,title,script,platform,status)
          values(%s,%s,%s,%s,'draft') returning *""",
          (offer_id,title,script,x.get("platform","rutube"))).fetchone()

@app.post("/api/content/{content_id}/publish-ready")
def publish_ready(content_id:int):
    with db() as c:
        row=c.execute("update content set status='ready' where id=%s returning *",(content_id,)).fetchone()
        if not row: raise HTTPException(404,"Материал не найден")
        return row

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
              (select count(*) from click_events where created_at > datetime('now','-24 hours')) clicks24""").fetchone()
        return c.execute("""select
          (select count(*) from offers where active) offers,
          (select count(*) from content) content,
          (select coalesce(sum(clicks),0) from content) clicks,
          (select coalesce(sum(conversions),0) from content) conversions,
          (select coalesce(sum(approved_commission),0) from content) commission,
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
<div class="card"><h1>CPA Factory</h1><div class="muted">Оффер → трекинг → контент → очередь публикации → аналитика</div></div>
<div class="grid"><div class="card"><div class="muted">Активные офферы</div><div id="m1" class="metric">0</div></div>
<div class="card"><div class="muted">Материалы</div><div id="m2" class="metric">0</div></div>
<div class="card"><div class="muted">Переходы</div><div id="m3" class="metric">0</div></div>
<div class="card"><div class="muted">Комиссия</div><div id="m4" class="metric">0 ₽</div></div></div>
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
</main><script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){
 let o=await (await fetch('/api/offers')).json(), c=await (await fetch('/api/content')).json(), s=await (await fetch('/api/stats')).json();
 m1.textContent=s.offers;m2.textContent=s.content;m3.textContent=s.clicks;m4.textContent=Number(s.commission||0).toLocaleString('ru-RU')+' ₽';
 offerSelect.innerHTML=o.map(x=>'<option value="'+x.id+'">'+esc(x.name)+'</option>').join('');
 offers.innerHTML=o.length?'<table><tr><th>Товар</th><th>Сеть</th><th>Цена</th><th>Комиссия</th><th>Переходы</th></tr>'+
 o.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.merchant)+'</td><td>'+Number(x.price||0).toLocaleString('ru-RU')+'</td><td>'+Number(x.commission||0).toLocaleString('ru-RU')+' ₽</td><td>'+x.clicks+'</td></tr>').join('')+'</table>':'Пока нет офферов';
 content.innerHTML=c.length?'<table><tr><th>Оффер</th><th>Площадка</th><th>Статус</th><th>Переходы</th><th>Ссылка</th></tr>'+
 c.map(x=>'<tr><td>'+esc(x.offer_name)+'</td><td>'+esc(x.platform)+'</td><td>'+esc(x.status)+'</td><td>'+x.clicks+'</td><td><a href="/go/'+x.offer_id+'?content_id='+x.id+'" target="_blank">тест</a></td></tr>').join('')+'</table>':'Пока нет материалов';
}
async function addOffer(){
 await fetch('/api/offers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value,merchant:merchant.value,price:price.value,commission:commission.value,tracking_url:url.value,traffic_rules:rules.value})});
 ['name','merchant','price','commission','url','rules'].forEach(x=>document.getElementById(x).value='');load();
}
async function generate(){
 let r=await fetch('/api/content/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({offer_id:offerSelect.value,platform:platform.value})});
 let x=await r.json(); generated.innerHTML='<p><b>'+esc(x.title)+'</b></p><textarea rows="6" readonly>'+esc(x.script)+'</textarea><div class="ok">Материал создан со статусом draft.</div>';load();
}
load();
</script></body></html>"""
