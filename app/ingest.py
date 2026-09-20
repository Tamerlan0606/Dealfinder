import os, re, json
from datetime import datetime, timezone
import httpx
from .db import connect

REGIONS=[x.strip().lower() for x in os.getenv("DEAL_REGIONS","Ростовская область,Ставропольский край,Республика Ингушетия,Кабардино-Балкарская Республика,Республика Северная Осетия — Алания,Краснодарский край,Москва,Московская область").split(",") if x.strip()]
KEYWORDS=[x.strip().lower() for x in os.getenv("DEAL_KEYWORDS","благоустройство,строитель,ремонт,кровл,фасад,монтаж,озелен,площадк,тротуар,освещен,водопровод,канализац,теплоснабж,электромонтаж").split(",") if x.strip()]
EXCLUDE_KEYWORDS=[x.strip().lower() for x in os.getenv("DEAL_EXCLUDE_KEYWORDS","автомобильных дорог,ремонт дорог,содержание дорог,медицинск газ,медицинских газ,газоснабж магистраль").split(",") if x.strip()]
MIN_RUB=float(os.getenv("DEAL_MIN_RUB","10000000"))
MAX_RUB=float(os.getenv("DEAL_MAX_RUB","90000000"))
MIN_ADV=float(os.getenv("DEAL_MIN_ADVANCE_PCT","20"))
MAX_BG=float(os.getenv("DEAL_BG_LIMIT_RUB","17000000"))

def _num(v):
    if isinstance(v,(int,float)): return float(v)
    if v is None: return None
    try:
        s=str(v).replace("\xa0","").replace(" ","").replace(",",".")
        return float(re.sub(r"[^0-9.]","",s))
    except Exception: return None

def _text(v):
    if v is None:return ""
    if isinstance(v,(dict,list)): return " ".join(_text(x) for x in (v.values() if isinstance(v,dict) else v))
    return str(v)

def _walk_values(obj):
    if isinstance(obj,dict):
        for k,v in obj.items():
            yield k,v
            yield from _walk_values(v)
    elif isinstance(obj,list):
        for v in obj: yield from _walk_values(v)

def _find_number(item, keys):
    for key,v in _walk_values(item):
        if key.lower() in keys:
            n=_num(v)
            if n is not None:return n
    return None

def _price(item):
    n=_find_number(item,{"max_price","maxprice","initial_price","initialprice","price","nmck","nmck_amount","nmckamount"})
    if n and MIN_RUB<=n<=MAX_RUB:return n
    for key,v in _walk_values(item):
        if any(x in key.lower() for x in ("price","cost","sum","amount","nmck")):
            n=_num(v)
            if n and MIN_RUB<=n<=MAX_RUB:return n
    return None

def _advance(item,blob,price):
    # First use structured fields.
    for key,v in _walk_values(item):
        k=key.lower().replace("_","")
        if any(x in k for x in ("advance","prepayment","avans")):
            n=_num(v)
            if n is not None:
                if 0<n<=1: return n*100
                if 1<n<=100:return n
                if price and 100<n<=price:return n/price*100
    # Then parse explicit Russian text.
    patterns=[
        r"аванс[^%]{0,100}(\d{1,3}(?:[.,]\d+)?)\s*%",
        r"авансов(?:ый|ого|ая|ое)?[^%]{0,100}(\d{1,3}(?:[.,]\d+)?)\s*%",
        r"предоплат[^%]{0,100}(\d{1,3}(?:[.,]\d+)?)\s*%",
        r"предварительн(?:ой|ая|ую)\s+оплат[^%]{0,100}(\d{1,3}(?:[.,]\d+)?)\s*%"
    ]
    for p in patterns:
        m=re.search(p,blob,re.I)
        if m:
            n=_num(m.group(1))
            if n is not None:return n
    return None

def _deadline(item,blob):
    keys={"submissiondeadline","deadline","enddate","end_date","applicationdeadline","application_end_date","date_end","dateend"}
    for key,v in _walk_values(item):
        if key.lower().replace("_","") in keys and isinstance(v,(str,int,float)):
            s=str(v)
            if re.search(r"\d{4}-\d{2}-\d{2}",s): return s[:10]
            if re.search(r"\d{2}[.]\d{2}[.]\d{4}",s): return re.search(r"\d{2}[.]\d{2}[.]\d{4}",s).group(0)
    return None

def _id(item):
    for key,v in _walk_values(item):
        if key.lower() in ("purchase_number","purchasenumber","reg_number","regnumber","reestr_number","reestrnumber","id"):
            s=str(v)
            if re.fullmatch(r"\d{10,}",s):return s
    return None

def _title(item):
    for p in ("title","name","purchase_name","purchasename","object_info","objectinfo"):
        for key,v in _walk_values(item):
            if key.lower().replace("_","")==p.replace("_","").lower() and isinstance(v,(str,int,float)) and str(v).strip():
                return str(v).strip()
    return "Закупка"

def _url(item,ext):
    for key,v in _walk_values(item):
        if "url" in key.lower() and isinstance(v,str) and v.startswith("http"):return v
    return f"https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber={ext}"

def _type(item,blob):
    for key,v in _walk_values(item):
        k=key.lower()
        if k in ("purchase_type","purchasetype","law","fz","procurement_type","procurementtype"):
            return str(v)
    if "223-фз" in blob or "223 фз" in blob:return "223-ФЗ"
    return "44-ФЗ"

def _sro(blob):
    if "сро" not in blob:return "не указано"
    if any(x in blob for x in ("членство в сро","требуется сро","требовани.*сро","членом сро")):return "требуется"
    return "упоминается"

def _experience(blob):
    if not any(x in blob for x in ("опыт","аналогичн","исполненн.*контракт","контрактов")):return "не указано"
    # TEKHSTROY profile: landscaping/general construction/repair/building systems.
    if any(x in blob for x in ("благоустрой","озелен","площадк","тротуар","ремонт здан","ремонт помещ","строительств здан","общестро","фасад","кровл","монтаж","спортивн","стадион")):
        return "совместимо"
    return "требует проверки"

def _fit(item):
    blob=_text(item).lower()
    reasons=[]
    if REGIONS and not any(x in blob for x in REGIONS):return False,"регион не подходит"
    if any(x in blob for x in EXCLUDE_KEYWORDS):return False,"предмет вне профиля ТЕХСТРОЙ"
    if not any(x in blob for x in KEYWORDS):return False,"предмет вне профиля"
    price=_price(item)
    if not price:return False,"нет НМЦК"
    adv=_advance(item,blob,price)
    if adv is None or adv<MIN_ADV:return False,f"аванс ниже {MIN_ADV:.0f}% или не подтвержден"
    exp=_experience(blob)
    if exp=="требует проверки":return False,"опыт требует проверки"
    if exp=="совместимо":reasons.append("опыт")
    sro=_sro(blob)
    reasons.append("аванс")
    reasons.append("профиль")
    reasons.append("НМЦК")
    return True,"; ".join(reasons)

def refresh():
    db=connect(os.getenv("DB_PATH","deals.db"))
    api_key=os.getenv("GOSPLAN_API_KEY","").strip()
    base="https://v2.gosplan.info" if api_key else "https://v2test.gosplan.info"
    headers={"User-Agent":"DealFinder/4.0","Accept":"application/json"}
    if api_key:headers["X-API-Key"]=api_key
    try:
        loaded=raw=pages=0;seen=set()
        for page in range(10):
            r=httpx.get(base+"/fz44/purchases",params={"limit":100,"skip":page*100},headers=headers,timeout=40,follow_redirects=True)
            r.raise_for_status();data=r.json()
            items=data if isinstance(data,list) else (data.get("items") or data.get("data") or data.get("results") or [])
            if not items:break
            pages+=1;raw+=len(items)
            for item in items:
                if not isinstance(item,dict):continue
                ext=_id(item)
                if not ext or ext in seen:continue
                seen.add(ext)
                ok,reason=_fit(item)
                if not ok:continue
                blob=_text(item).lower();price=_price(item);adv=_advance(item,blob,price)
                deadline=_deadline(item,blob)
                adv_rub=price*adv/100 if adv is not None else None
                title=_title(item);url=_url(item,ext)
                db.execute("""INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city,advance_pct,advance_rub,deadline,procurement_type,sro_required,experience_required,fit_status,fit_reasons)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,description=excluded.description,url=excluded.url,budget_rub=excluded.budget_rub,advance_pct=excluded.advance_pct,advance_rub=excluded.advance_rub,deadline=excluded.deadline,procurement_type=excluded.procurement_type,sro_required=excluded.sro_required,experience_required=excluded.experience_required,fit_status=excluded.fit_status,fit_reasons=excluded.fit_reasons""",
                ("gosplan_v2",ext,title,blob[:6000],url,"",price,"",adv,adv_rub,deadline,_type(item,blob),_sro(blob),_experience(blob),"ЗАХОДИМ",reason))
                loaded+=1
            if len(items)<100:break
        db.commit()
        return {"status":"ok","loaded":loaded,"raw":raw,"pages":pages,"source":"gosplan_v2","server":base,"advance_min_pct":MIN_ADV,"bg_limit_rub":MAX_BG,"pricing":"5% bid discount + 7% tax","updated_at":datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"status":"error","error":str(e),"source":"gosplan_v2","server":base}
    finally:db.close()

def start_loop():return None
