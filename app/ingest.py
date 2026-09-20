import os, re, time, threading
from datetime import datetime
import httpx
from .db import connect

API = os.getenv("GOSPLAN_API_URL", "https://v2test.gosplan.info/fz44/purchases")
REGIONS = [x.strip().lower() for x in os.getenv(
    "DEAL_REGIONS",
    "Ростовская область,Ставропольский край,Республика Ингушетия,Кабардино-Балкарская Республика,Республика Северная Осетия — Алания,Краснодарский край,Москва,Московская область"
).split(",") if x.strip()]
KEYWORDS = [x.strip().lower() for x in os.getenv(
    "DEAL_KEYWORDS",
    "благоустройство,строитель,капитальн,ремонт,кровл,фасад,монтаж,дорог,озелен,площадк,тротуар,освещен,водопровод,канализац,теплоснабж,электромонтаж"
).split(",") if x.strip()]
MIN_RUB = float(os.getenv("DEAL_MIN_RUB", "10000000"))
MAX_RUB = float(os.getenv("DEAL_MAX_RUB", "90000000"))

def _pick(obj, keys):
    wanted = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in wanted and v not in (None, ""):
                return v
        for v in obj.values():
            r = _pick(v, keys)
            if r not in (None, ""):
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _pick(v, keys)
            if r not in (None, ""):
                return r
    return None

def _text(obj):
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(_text(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_text(v) for v in obj)
    return str(obj or "")

def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if not v:
        return None
    s = re.sub(r"[^0-9,.-]", "", str(v).replace("\xa0", ""))
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "results", "purchases", "data", "result", "content"):
            v = data.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, (dict, list)):
                found = _items(v)
                if found:
                    return found
        for v in data.values():
            if isinstance(v, (dict, list)):
                found = _items(v)
                if found:
                    return found
    return []

def _eis_fallback():
    import urllib.parse, re
    headers={"User-Agent":"Mozilla/5.0 (compatible; DealFinder/1.0)"}
    out=[]
    seen=set()
    for kw in KEYWORDS[:8]:
        q=urllib.parse.quote(kw)
        url="https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString="+q
        try:
            rr=httpx.get(url,headers=headers,timeout=20,follow_redirects=True)
            if rr.status_code != 200:
                continue
            for m in re.finditer(r'href=["\\']([^"\\']*common-info[^"\\']*)["\\']',rr.text,re.I):
                link=m.group(1)
                if link.startswith("/"):
                    link="https://zakupki.gov.ru"+link
                n=re.search(r"regNumber[=/]([0-9]{10,})",link)
                if n and n.group(1) not in seen:
                    seen.add(n.group(1))
                    out.append((n.group(1),kw,link))
        except Exception:
            pass
    return out

def refresh():
    db = connect(os.getenv("DB_PATH", "deals.db"))
    try:
        r = httpx.get(API, params={"limit": 10, "skip": 0, "sort": "published_date_desc"}, timeout=30, follow_redirects=True, headers={"User-Agent":"DealFinder/1.0"})
        r.raise_for_status()
        data = r.json()
        items = _items(data)
        count = 0
        stats = {"raw": len(items), "price_ok": 0, "keyword_ok": 0, "region_ok": 0}
        for item in items:
            blob = _text(item)
            title = _pick(item, ["title","name","subject","purchase_name","short_description","description"])
            title = str(title or "").strip()
            price = _num(_pick(item, ["max_price","initial_max_price","nmck","nmc","price","maximum_price"]))
            ext = _pick(item, ["purchase_number","registry_number","number","id"])
            url = _pick(item, ["url","href","notice_url","purchase_url"])
            region = str(_pick(item, ["region","region_name","customer_region","location","subject"]) or "").strip()
            if not title or not ext or not price or price < MIN_RUB or price > MAX_RUB:
                continue
            stats["price_ok"] += 1
            low = (title + " " + blob).lower()
            if not any(k in low for k in KEYWORDS):
                continue
            stats["keyword_ok"] += 1
            if REGIONS and region and not any(rg in (region + " " + blob).lower() for rg in REGIONS):
                continue
            stats["region_ok"] += 1
            if not url:
                url = f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={ext}"
            db.execute(
                """INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(source,external_id) DO UPDATE SET
                   title=excluded.title,description=excluded.description,url=excluded.url,
                   budget_rub=excluded.budget_rub,city=excluded.city""",
                ("gosplan44", str(ext), title, blob[:1500], str(url), "", price, region)
            )
            count += 1
        db.commit()
        return {"status":"ok","loaded":count,"stats":stats,"source":API,"updated_at":datetime.utcnow().isoformat()+"Z"}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            items = _eis_fallback()
            db2 = connect(os.getenv("DB_PATH", "deals.db"))
            loaded = 0
            try:
                for ext,kw,url in items:
                    db2.execute("INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,url=excluded.url",("eis_web",ext,kw,url,"", "",0,""))
                    loaded += 1
                db2.commit()
            finally:
                db2.close()
            return {"status":"ok","loaded":loaded,"source":"eis_web_fallback","api_error":"429"}
        return {"status":"error","error":f"HTTP {e.response.status_code}: {e.response.text[:500]}","source":API}
    except Exception as e:
        return {"status":"error","error":str(e),"source":API}
    finally:
        db.close()

def start_loop():
    def loop():
        while True:
            refresh()
            time.sleep(int(os.getenv("REFRESH_SECONDS", "900")))
    threading.Thread(target=loop, daemon=True).start()
