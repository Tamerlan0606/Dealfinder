import os, re
from datetime import datetime
import httpx
from .db import connect

REGIONS = [x.strip().lower() for x in os.getenv("DEAL_REGIONS","Ростовская область,Ставропольский край,Республика Ингушетия,Кабардино-Балкарская Республика,Республика Северная Осетия — Алания,Краснодарский край,Москва,Московская область").split(",") if x.strip()]
KEYWORDS = [x.strip().lower() for x in os.getenv("DEAL_KEYWORDS","благоустройство,строитель,капитальн,ремонт,кровл,фасад,монтаж,дорог,озелен,площадк,тротуар,освещен,водопровод,канализац,теплоснабж,электромонтаж").split(",") if x.strip()]
MIN_RUB=float(os.getenv("DEAL_MIN_RUB","10000000"))
MAX_RUB=float(os.getenv("DEAL_MAX_RUB","90000000"))

def _num(v):
    if isinstance(v,(int,float)): return float(v)
    if v is None: return None
    try:
        s=str(v).replace("\xa0","").replace(" ","").replace(",",".")
        return float(re.sub(r"[^0-9.]","",s))
    except Exception:
        return None

def _text(v):
    if v is None: return ""
    if isinstance(v,(dict,list)): return " ".join(_text(x) for x in (v.values() if isinstance(v,dict) else v))
    return str(v)

def _walk_values(obj):
    if isinstance(obj,dict):
        for k,v in obj.items():
            yield k,v
            yield from _walk_values(v)
    elif isinstance(obj,list):
        for v in obj:
            yield from _walk_values(v)

def _price(item):
    preferred=("max_price","maxPrice","initial_price","initialPrice","price","nmck","nmck_amount")
    for key,v in _walk_values(item):
        if key in preferred:
            n=_num(v)
            if n and MIN_RUB <= n <= MAX_RUB: return n
    for key,v in _walk_values(item):
        if any(x in key.lower() for x in ("price","cost","sum","amount","nmck")):
            n=_num(v)
            if n and MIN_RUB <= n <= MAX_RUB: return n
    return None

def _id(item):
    for key,v in _walk_values(item):
        if key.lower() in ("purchase_number","purchaseNumber","reg_number","regNumber","reestr_number","reestrNumber","id"):
            s=str(v)
            if re.fullmatch(r"\d{10,}",s): return s
    return None

def _title(item):
    preferred=("title","name","purchase_name","purchaseName","object_info","objectInfo")
    for p in preferred:
        for key,v in _walk_values(item):
            if key==p and isinstance(v,(str,int,float)) and str(v).strip(): return str(v).strip()
    return "Закупка"

def _url(item, ext):
    for key,v in _walk_values(item):
        if "url" in key.lower() and isinstance(v,str) and v.startswith("http"):
            return v
    return f"https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber={ext}"

def refresh():
    db=connect(os.getenv("DB_PATH","deals.db"))
    api_key=os.getenv("GOSPLAN_API_KEY","").strip()
    base="https://v2.gosplan.info" if api_key else "https://v2test.gosplan.info"
    headers={"User-Agent":"DealFinder/2.1","Accept":"application/json"}
    if api_key: headers["X-API-Key"]=api_key
    try:
        loaded=0
        raw=0
        pages=0
        seen=set()
        for page in range(10):
            r=httpx.get(base+"/fz44/purchases",params={"limit":100,"skip":page*100},headers=headers,timeout=40,follow_redirects=True)
            r.raise_for_status()
            data=r.json()
            items=data if isinstance(data,list) else (data.get("items") or data.get("data") or data.get("results") or [])
            if not items: break
            pages += 1
            raw += len(items)
            for item in items:
                if not isinstance(item,dict): continue
                blob=_text(item).lower()
                ext=_id(item)
                if not ext or ext in seen: continue
                seen.add(ext)
                if REGIONS and not any(x in blob for x in REGIONS): continue
                if not any(x in blob for x in KEYWORDS): continue
                price=_price(item)
                if not price: continue
                title=_title(item)
                db.execute("INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,description=excluded.description,url=excluded.url,budget_rub=excluded.budget_rub,city=excluded.city",
                ("gosplan_v2",ext,title,blob[:4000],_url(item,ext),"",price,""))
                loaded+=1
            if len(items) < 100: break
        db.commit()
        return {"status":"ok","loaded":loaded,"raw":raw,"pages":pages,"source":"gosplan_v2","server":base,"updated_at":datetime.utcnow().isoformat()+"Z"}
    except Exception as e:
        return {"status":"error","error":str(e),"source":"gosplan_v2","server":base}
    finally:
        db.close()

def start_loop():
    return None
