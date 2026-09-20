import os, re, json, time
from datetime import datetime, timezone
import httpx
from .db import connect

REGIONS=[x.strip().lower() for x in os.getenv("DEAL_REGIONS","Ростовская область,Ставропольский край,Республика Ингушетия,Кабардино-Балкарская Республика,Республика Северная Осетия — Алания,Краснодарский край,Москва,Московская область").split(",") if x.strip()]
KEYWORDS=[x.strip().lower() for x in os.getenv("DEAL_KEYWORDS","благоустройство,строитель,капитальн,ремонт,кровл,фасад,монтаж,озелен,площадк,тротуар,освещен,водопровод,канализац,теплоснабж,электромонтаж").split(",") if x.strip()]
EXCLUDE_KEYWORDS=[x.strip().lower() for x in os.getenv("DEAL_EXCLUDE_KEYWORDS","автомобильных дорог,ремонт дорог,содержание дорог,медицинск газ,медицинских газ,газоснабж магистраль").split(",") if x.strip()]
MIN_RUB=float(os.getenv("DEAL_MIN_RUB","10000000")); MAX_RUB=float(os.getenv("DEAL_MAX_RUB","90000000"))
MIN_ADV=float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")); MAX_BG=float(os.getenv("DEAL_BG_LIMIT_RUB","17000000"))

def _num(v):
    if isinstance(v,(int,float)): return float(v)
    if v is None:return None
    try:
        s=str(v).replace("\xa0","").replace(" ","").replace(",",".")
        return float(re.sub(r"[^0-9.]","",s))
    except:return None

def _text(v):
    if v is None:return ""
    if isinstance(v,dict):return " ".join(_text(x) for x in v.values())
    if isinstance(v,list):return " ".join(_text(x) for x in v)
    return str(v)

def _walk_values(obj):
    if isinstance(obj,dict):
        for k,v in obj.items():
            yield k,v; yield from _walk_values(v)
    elif isinstance(obj,list):
        for v in obj: yield from _walk_values(v)

def _find_number(item,keys):
    for k,v in _walk_values(item):
        if k.lower().replace("_","") in {x.replace("_","") for x in keys}:
            n=_num(v)
            if n is not None:return n
    return None

def _price(item):
    n=_find_number(item,{"max_price","maxPrice","initial_price","initialPrice","price","nmck","nmck_amount","nmckamount"})
    if n and MIN_RUB<=n<=MAX_RUB:return n
    return None

def _advance(item,blob,price):
    for k,v in _walk_values(item):
        kk=k.lower().replace("_","")
        if any(x in kk for x in ("advance","prepayment","avans","predoplata","предоплат")):
            n=_num(v)
            if n is not None:
                if 0<n<=1:return n*100
                if 1<n<=100:return n
                if price and n>100:return n/price*100
    pats=[
      r"аванс[^%]{0,120}(\d{1,3}(?:[.,]\d+)?)\s*%",
      r"авансов(?:ый|ого|ая|ое)?[^%]{0,120}(\d{1,3}(?:[.,]\d+)?)\s*%",
      r"предоплат[^%]{0,120}(\d{1,3}(?:[.,]\d+)?)\s*%",
      r"предварительн(?:ой|ая|ую)\s+оплат[^%]{0,120}(\d{1,3}(?:[.,]\d+)?)\s*%"
    ]
    for p in pats:
        m=re.search(p,blob,re.I)
        if m:return _num(m.group(1))
    return None

def _deadline(item,blob):
    for k,v in _walk_values(item):
        kk=k.lower().replace("_","")
        if kk in {"submissiondeadline","deadline","enddate","applicationdeadline","applicationenddate","dateend"}:
            s=str(v)
            m=re.search(r"(\d{4}-\d{2}-\d{2})",s)
            if m:return m.group(1)
            m=re.search(r"(\d{2}[.]\d{2}[.]\d{4})",s)
            if m:return m.group(1)
    return None

def _id(item):
    for k,v in _walk_values(item):
        if k.lower().replace("_","") in {"purchasenumber","regnumber","reestrnumber","id"}:
            s=str(v)
            if re.fullmatch(r"\d{10,}",s):return s
    return None

def _title(item):
    for wanted in ("title","name","purchase_name","purchaseName","object_info","objectInfo"):
        for k,v in _walk_values(item):
            if k.lower().replace("_","")==wanted.lower().replace("_","") and str(v).strip():
                return str(v).strip()
    return "Закупка"

def _url(item,ext):
    for k,v in _walk_values(item):
        if "url" in k.lower() and isinstance(v,str) and v.startswith("http"):return v
    return f"https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber={ext}"

def _type(item,blob):
    for k,v in _walk_values(item):
        if k.lower().replace("_","") in {"purchasetype","law","fz","procurementtype"}:return str(v)
    if "223-фз" in blob or "223 фз" in blob:return "223-ФЗ"
    return "44-ФЗ"

def _sro(blob):
    if "сро" not in blob:return "не указано"
    if re.search(r"член(?:ство|ом)|требуется\s+сро|требован\S*\s+сро",blob):return "требуется"
    return "упоминается"

def _experience(blob):
    if not re.search(r"опыт|аналогич|исполненн.*контракт|контрактов|квалификац",blob):return "не указано"
    profile=("благоустрой","озелен","площадк","тротуар","ремонт здан","ремонт помещ","строительств здан","общестро","фасад","кровл","монтаж","спортивн","стадион")
    return "совместимо" if any(x in blob for x in profile) else "требует проверки"

def _security(item,blob,price):
    for k,v in _walk_values(item):
        kk=k.lower().replace("_","")
        if any(x in kk for x in ("contractsecurity","performanceguarantee","obespechenieispolneniya","obespecheniekontrakta")):
            n=_num(v)
            if n is not None:
                if 0<n<=100 and price:return price*n/100
                return n
    m=re.search(r"обеспечени[ея]\s+(?:исполнения|контракта)[^%]{0,100}(\d{1,3}(?:[.,]\d+)?)\s*%",blob,re.I)
    return price*_num(m.group(1))/100 if m and price else None

def _fit(item):
    blob=_text(item).lower()
    if REGIONS and not any(x in blob for x in REGIONS):return False,"регион"
    if any(x in blob for x in EXCLUDE_KEYWORDS):return False,"вне профиля"
    if not any(x in blob for x in KEYWORDS):return False,"вне профиля"
    price=_price(item)
    if not price:return False,"НМЦК"
    adv=_advance(item,blob,price)
    if adv is None or adv<MIN_ADV:return False,f"аванс < {MIN_ADV:.0f}%/не подтвержден"
    sec=_security(item,blob,price)
    if sec is not None and sec>MAX_BG:return False,"обеспечение выше лимита БГ"
    exp=_experience(blob)
    if exp=="требует проверки":return False,"опыт не подтвержден профилем"
    deadline=_deadline(item,blob)
    if deadline:
        try:
            d=datetime.strptime(deadline,"%Y-%m-%d").replace(tzinfo=timezone.utc)
            if d<datetime.now(timezone.utc):return False,"срок подачи истек"
        except:pass
    return True,"аванс; профиль; НМЦК; БГ"

def refresh():
    db=connect(os.getenv("DB_PATH","deals.db")); api_key=os.getenv("GOSPLAN_API_KEY","").strip()
    base="https://v2.gosplan.info" if api_key else "https://v2test.gosplan.info"
    headers={"User-Agent":"DealFinder/5.0","Accept":"application/json"}
    if api_key:headers["X-API-Key"]=api_key
    loaded=raw=pages=0;seen=set()
    max_pages=int(os.getenv("GOSPLAN_MAX_PAGES","8"))
    test_interval=float(os.getenv("GOSPLAN_TEST_INTERVAL","7.0"))
    try:
        with httpx.Client(timeout=40,follow_redirects=True,headers=headers) as client:
            for page in range(max_pages):
                if page and not api_key:
                    time.sleep(test_interval)
                params={"limit":100,"skip":page*100,"sort":"published_desc"}
                for attempt in range(3):
                    r=client.get(base+"/fz44/purchases",params=params)
                    if r.status_code != 429:
                        r.raise_for_status()
                        break
                    retry_after=r.headers.get("Retry-After")
                    try:
                        wait=max(7.0,float(retry_after)) if retry_after else 7.0
                    except:
                        wait=7.0
                    if attempt==2:
                        raise RuntimeError(f"GosPlan 429: лимит тестового API. Повторите обновление позже (ожидание {wait:.0f} сек).")
                    time.sleep(wait)
                data=r.json()
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
                    db.execute("""INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city,advance_pct,advance_rub,deadline,procurement_type,sro_required,experience_required,fit_status,fit_reasons)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,description=excluded.description,url=excluded.url,budget_rub=excluded.budget_rub,advance_pct=excluded.advance_pct,advance_rub=excluded.advance_rub,deadline=excluded.deadline,procurement_type=excluded.procurement_type,sro_required=excluded.sro_required,experience_required=excluded.experience_required,fit_status=excluded.fit_status,fit_reasons=excluded.fit_reasons""",
                    ("gosplan_v2",ext,_title(item),blob[:6000],_url(item,ext),"",price,"",adv,price*adv/100,deadline,_type(item,blob),_sro(blob),_experience(blob),"ЗАХОДИМ",reason)); loaded+=1
                if len(items)<100:break
        db.commit()
        return {"status":"ok","loaded":loaded,"raw":raw,"pages":pages,"source":"gosplan_v2","server":base,"advance_min_pct":MIN_ADV,"bg_limit_rub":MAX_BG,"pricing":"5% ниже НМЦК; налог 7%","updated_at":datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        return {"status":"error","loaded":loaded,"raw":raw,"pages":pages,"error":str(e),"source":"gosplan_v2","server":base}
    finally:db.close()

def start_loop():return None
