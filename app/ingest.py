import os, re, time
from datetime import datetime, timezone
import httpx
from urllib.parse import quote
import xml.etree.ElementTree as ET
from .db import connect

REGIONS=[x.strip().lower() for x in os.getenv("DEAL_REGIONS","Ростовская область,Ставропольский край,Республика Ингушетия,Кабардино-Балкарская Республика,Республика Северная Осетия — Алания,Краснодарский край,Москва,Московская область").split(",") if x.strip()]
KEYWORDS=[x.strip().lower() for x in os.getenv("DEAL_KEYWORDS","благоустройство,строитель,строительств,капитальн,ремонт,кровл,фасад,монтаж,озелен,площадк,тротуар,освещен,водопровод,канализац,теплоснабж,электромонтаж,общестро,стадион,спортив,маф,территор,уборк,клининг,содержан территор,зимн содержан,снег,снега,налед,сосул,очистк крыш,очистка кровл,механизированн уборк,ручн уборк").split(",") if x.strip()]
EXCLUDE_KEYWORDS=[x.strip().lower() for x in os.getenv("DEAL_EXCLUDE_KEYWORDS","автомобильных дорог,ремонт дорог,содержание дорог,медицинск газ,медицинских газ,газоснабж магистраль").split(",") if x.strip()]
MIN_RUB=float(os.getenv("DEAL_MIN_RUB","10000000")); MAX_RUB=float(os.getenv("DEAL_MAX_RUB","90000000"))
MIN_ADV=float(os.getenv("DEAL_MIN_ADVANCE_PCT","20")); MAX_BG=float(os.getenv("DEAL_BG_LIMIT_RUB","17000000"))
_RATE_LIMITED_UNTIL=0.0
_RATE_LIMITED_REASON=""

def _norm_key(k):
    return re.sub(r"[^a-zа-я0-9]","",str(k).lower())

def _num(v):
    if isinstance(v,(int,float)): return float(v)
    if v is None:return None
    s=str(v).replace("\xa0","").replace(" ","").replace(",",".")
    m=re.search(r"-?\d+(?:\.\d+)?",s)
    try:return float(m.group()) if m else None
    except:return None

def _text(v):
    if v is None:return ""
    if isinstance(v,dict):return " ".join(f"{k} {_text(x)}" for k,x in v.items())
    if isinstance(v,list):return " ".join(_text(x) for x in v)
    return str(v)

def _walk_values(obj):
    if isinstance(obj,dict):
        for k,v in obj.items():
            yield k,v
            yield from _walk_values(v)
    elif isinstance(obj,list):
        for v in obj: yield from _walk_values(v)

def _price(item):
    exact={"maxprice","initialprice","initialmaxprice","price","nmck","nmckamount","priceamount","startprice","contractprice","maxcontractprice"}
    candidates=[]
    for k,v in _walk_values(item):
        nk=_norm_key(k)
        n=_num(v)
        if n is None: continue
        if nk in exact or ("price" in nk and not any(x in nk for x in ("percent","pct","type"))):
            candidates.append(n)
        elif "nmck" in nk:
            candidates.append(n)
    for n in candidates:
        if MIN_RUB<=n<=MAX_RUB:return n
    return None

def _advance(item,blob,price):
    pct_keys=("advance","prepayment","avans","predoplata","предоплат","prepay")
    amount_keys=("advanceamount","prepaymentamount","avansamount","predoplataamount","предоплатасумма")
    for k,v in _walk_values(item):
        nk=_norm_key(k); n=_num(v)
        if n is None: continue
        if any(x in nk for x in pct_keys):
            if 0<n<=1:return n*100
            if 1<n<=100:return n
            if price and n>100:return n/price*100
        if any(x in nk for x in amount_keys) and price and n>0:return n/price*100
    pats=[
      r"(?:аванс|авансов(?:ый|ого|ая|ое)?|предоплат|предварительн(?:ой|ая|ую) оплат)[^%]{0,160}(\d{1,3}(?:[.,]\d+)?)\s*%",
      r"(\d{1,3}(?:[.,]\d+)?)\s*%[^.]{0,100}(?:аванс|предоплат)"
    ]
    for p in pats:
        m=re.search(p,blob,re.I)
        if m:
            n=_num(m.group(1))
            if n is not None:return n
    return None

def _parse_date(s):
    s=str(s)
    for p in (r"(\d{4}-\d{2}-\d{2})",r"(\d{2}[.]\d{2}[.]\d{4})"):
        m=re.search(p,s)
        if m:
            raw=m.group(1)
            try:
                return datetime.strptime(raw,"%Y-%m-%d").strftime("%Y-%m-%d") if "-" in raw else datetime.strptime(raw,"%d.%m.%Y").strftime("%Y-%m-%d")
            except: pass
    return None

def _deadline(item,blob):
    keys={"submissiondeadline","deadline","enddate","applicationdeadline","applicationenddate","dateend","submissionenddate","bidenddate","dateendacceptance"}
    for k,v in _walk_values(item):
        nk=_norm_key(k)
        if nk in keys or any(x in nk for x in ("submissionend","applicationend","bidend")):
            d=_parse_date(v)
            if d:return d
    dates=re.findall(r"\d{2}[.]\d{2}[.]\d{4}|\d{4}-\d{2}-\d{2}",blob)
    for raw in dates:
        d=_parse_date(raw)
        if d:return d
    return None

def _id(item):
    preferred=("purchasenumber","regnumber","reestrnumber","purchaseid","noticeid","id")
    for wanted in preferred:
        for k,v in _walk_values(item):
            if _norm_key(k)==wanted:
                s=str(v).strip()
                if s and len(s)<=120:return s
    return None

def _title(item):
    wanted=("title","name","purchasename","objectinfo","objectname","object_info")
    for w in wanted:
        for k,v in _walk_values(item):
            if _norm_key(k)==_norm_key(w) and str(v).strip():
                return str(v).strip()
    return "Закупка"

def _url(item,ext):
    for k,v in _walk_values(item):
        if "url" in str(k).lower() and isinstance(v,str) and v.startswith("http"):return v
    return f"https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber={ext}"

def _city(item,blob):
    keys=("city","region","regionname","deliveryplace","deliveryaddress","location","place","delivery_places")
    for k,v in _walk_values(item):
        nk=_norm_key(k)
        if any(x in nk for x in keys):
            s=_text(v).strip()
            if s and len(s)<=300:return s
    for r in REGIONS:
        if r in blob:return r
    return ""

def _type(item,blob):
    for k,v in _walk_values(item):
        if _norm_key(k) in {"purchasetype","law","fz","procurementtype"}:return str(v)
    return "223-ФЗ" if "223-фз" in blob or "223 фз" in blob else "44-ФЗ"

def _sro(blob):
    if "сро" not in blob:return "не указано"
    return "требуется" if re.search(r"член(?:ство|ом)|требуется\s+сро|требован\S*\s+сро",blob) else "упоминается"

def _experience(blob):
    if not re.search(r"опыт|аналогич|исполненн.*контракт|контрактов|квалификац",blob):return "не указано"
    profile=("благоустрой","озелен","площадк","тротуар","ремонт здан","ремонт помещ","строительств здан","общестро","фасад","кровл","монтаж","спортивн","стадион","уборк","клининг","содержан территор","зимн","снег","налед","сосул","очистк крыш","очистка кровл")
    return "совместимо" if any(x in blob for x in profile) else "требует проверки"

def _security(item,blob,price):
    keys=("contractsecurity","performanceguarantee","obespechenieispolneniya","obespecheniekontrakta","securityamount","guaranteeamount")
    for k,v in _walk_values(item):
        nk=_norm_key(k); n=_num(v)
        if n is None:continue
        if any(x in nk for x in keys):
            if 0<n<=100 and price:return price*n/100
            return n
    m=re.search(r"обеспечени[ея]\s+(?:исполнения|контракта)[^%]{0,100}(\d{1,3}(?:[.,]\d+)?)\s*%",blob,re.I)
    return price*_num(m.group(1))/100 if m and price else None

def _region_allowed(item, blob):
    # Do not reject a tender merely because the API omitted the region field.
    # If a structured delivery region exists, require an allowed region.
    region_parts=[]
    for k,v in _walk_values(item):
        nk=_norm_key(k)
        if any(x in nk for x in ("region","deliveryplace","deliveryaddress","location","place")):
            region_parts.append(_text(v).lower())
    structured=" ".join(region_parts)
    if structured:
        return any(x in structured for x in REGIONS)
    # For unstructured records, accept when an allowed region is explicit.
    # Unknown geography goes to document review instead of being silently discarded.
    return True

def _fit(item):
    blob=_text(item).lower()
    if not _region_allowed(item,blob):
        return False,"регион"
    if any(x in blob for x in EXCLUDE_KEYWORDS):
        return False,"вне профиля"
    if not any(x in blob for x in KEYWORDS):
        return False,"вне профиля"
    price=_price(item)
    if not price:
        return False,"НМЦК"
    if price < MIN_RUB or price > MAX_RUB:
        return False,"НМЦК"
    adv=_advance(item,blob,price)
    if adv is not None and adv < MIN_ADV:
        return False,f"аванс < {MIN_ADV:.0f}%"
    sec=_security(item,blob,price)
    if sec is not None and sec > MAX_BG:
        return False,"обеспечение выше лимита БГ"
    # Опыт не режем на ingestion — оставляем на review/ручную оценку
    deadline=_deadline(item,blob)
    if deadline:
        try:
            d=datetime.strptime(deadline,"%Y-%m-%d").replace(tzinfo=timezone.utc)
            if d < datetime.now(timezone.utc):
                return False,"срок подачи истек"
        except Exception:
            pass
    return True,("требует проверки аванса" if adv is None else "аванс; профиль; НМЦК; БГ")

def _request_page(client,url,headers,params):
    r=client.get(url,params=params)
    if r.status_code==422 and params:
        r=client.get(url)
    r.raise_for_status()
    return r

def refresh():
    global _RATE_LIMITED_UNTIL, _RATE_LIMITED_REASON
    now=time.time()
    if now < _RATE_LIMITED_UNTIL:
        left=max(1,int(_RATE_LIMITED_UNTIL-now))
        db=connect(os.getenv("DB_PATH") or ("/data/deals.db" if os.path.isdir("/data") else "deals.db"))
        try:
            fb=_rss_fallback(db)
            if fb.get("loaded",0):
                return {"status":"fallback","loaded":fb["loaded"],"raw":fb.get("raw",0),"pages":0,"source":"eis_rss_fallback","server":"zakupki.gov.ru","api_mode":"public_rss","retry_after":left,"warning":_RATE_LIMITED_REASON}
        finally:
            db.close()
        return {"status":"rate_limited","loaded":0,"raw":0,"pages":0,"source":"gosplan_v2","server":"https://v2test.gosplan.info","api_mode":"test","retry_after":left,"error":_RATE_LIMITED_REASON or "GosPlan API rate limit; ожидаем cooldown"}
    db=connect(os.getenv("DB_PATH") or ("/data/deals.db" if os.path.isdir("/data") else "deals.db")); api_key=os.getenv("GOSPLAN_API_KEY","").strip()
    # Без production-ключа используем бесплатный тестовый ГосПлан API.
    # Документация ГосПлана подтверждает /fz44/purchases?limit=10&skip=0 без ключа.
    # Тестовый сервер ограничен по частоте запросов.
    if not api_key and os.getenv("USE_GOSPLAN_TEST","true").lower() == "true":
        base="https://v2test.gosplan.info"
    base=os.getenv("GOSPLAN_BASE_URL","https://v2.gosplan.info" if api_key else "https://v2test.gosplan.info").rstrip("/")
    endpoints=[x.strip() for x in os.getenv("GOSPLAN_ENDPOINTS","/fz44/purchases,/fz223/purchases").split(",") if x.strip()]
    headers={"User-Agent":"DealFinder/5.1","Accept":"application/json"}
    if api_key:headers["X-API-Key"]=api_key
    loaded=raw=pages=0;seen=set();page_signatures=set()
    diag={"region":0,"exclude":0,"price":0,"advance":0,"security":0,"experience":0,"deadline":0,"accepted":0}
    max_pages=max(1,int(os.getenv("GOSPLAN_MAX_PAGES","3"))); test_interval=max(5.0,float(os.getenv("GOSPLAN_TEST_INTERVAL","10"))); cooldown=int(os.getenv("GOSPLAN_RATE_LIMIT_COOLDOWN","300"))
    try:
        with httpx.Client(timeout=15,follow_redirects=True,headers=headers) as client:
            for endpoint in endpoints:
                for page in range(max_pages):
                    if (page or endpoint != endpoints[0]) and not api_key: time.sleep(test_interval)
                    params={"limit":10,"skip":page*10}
                    r=client.get(base+endpoint,params=params)
                    if r.status_code==429:
                        raw_retry=r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Retry-After-Seconds")
                        try:
                            retry=max(30,min(3600,int(float(raw_retry)))) if raw_retry else cooldown
                        except Exception:
                            retry=cooldown
                        _RATE_LIMITED_UNTIL=time.time()+retry
                        _RATE_LIMITED_REASON=f"GosPlan HTTP 429: rate limit; следующая попытка через {retry} сек."
                        # GosPlan временно ограничил API. Не блокируем ручное обновление:
                        # сразу переключаемся на публичный RSS ЕИС.
                        db.rollback()
                        fb=_rss_fallback(db)
                        if fb.get("loaded",0):
                            return {"status":"fallback","loaded":fb["loaded"],"raw":raw+fb.get("raw",0),"pages":pages,"source":"eis_rss_fallback","server":"zakupki.gov.ru","api_mode":"public_rss","http_status":429,"retry_after":retry,"warning":_RATE_LIMITED_REASON,"diagnostics":diag}
                        return {"status":"rate_limited","loaded":0,"raw":raw,"pages":pages,"source":"gosplan_v2","server":base,"api_mode":"test" if not api_key else "production","http_status":429,"retry_after":retry,"error":_RATE_LIMITED_REASON,"diagnostics":diag}
                    if r.status_code==422 and page>0:
                        break
                    r.raise_for_status()
                    _RATE_LIMITED_UNTIL=0.0
                    _RATE_LIMITED_REASON=""
                    data=r.json()
                    items=data if isinstance(data,list) else (data.get("items") or data.get("data") or data.get("results") or [])
                    if not isinstance(items,list) or not items:break
                    signature=tuple(_id(x) for x in items if isinstance(x,dict))
                    if signature and signature in page_signatures: break
                    page_signatures.add(signature)
                    pages+=1;raw+=len(items)
                    for item in items:
                        if not isinstance(item,dict):continue
                        ext=_id(item)
                        key=(endpoint,ext)
                        if not ext or key in seen:continue
                        seen.add(key)
                        ok,reason=_fit(item)
                        if not ok:
                            diag[{"регион":"region","вне профиля":"exclude","НМЦК":"price","обеспечение выше лимита БГ":"security","опыт не подтвержден профилем":"experience","срок подачи истек":"deadline"}.get(reason,"advance" if reason.startswith("аванс") else "exclude")]+=1
                            continue
                        blob=_text(item).lower();price=_price(item);adv=_advance(item,blob,price);sec=_security(item,blob,price);status="ЗАХОДИМ" if adv is not None and adv>=MIN_ADV else "ПРОВЕРИТЬ АВАНС"
                        if status=="ЗАХОДИМ":diag["accepted"]+=1
                        deadline=_deadline(item,blob)
                        db.execute("""INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city,advance_pct,advance_rub,deadline,procurement_type,sro_required,experience_required,security_rub,fit_status,fit_reasons)
VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,description=excluded.description,url=excluded.url,budget_rub=excluded.budget_rub,advance_pct=excluded.advance_pct,advance_rub=excluded.advance_rub,deadline=excluded.deadline,procurement_type=excluded.procurement_type,sro_required=excluded.sro_required,experience_required=excluded.experience_required,security_rub=excluded.security_rub,fit_status=excluded.fit_status,fit_reasons=excluded.fit_reasons""",
                            ("gosplan_v2"+endpoint,ext,_title(item),_text(item)[:6000],_url(item,ext),"",price,_city(item,blob),adv,(price*adv/100 if adv is not None else None),deadline,_type(item,blob),_sro(blob),_experience(blob),sec,status,reason));loaded+=1
                    if len(items)<10:break
        db.commit()
        if loaded==0:
            fb=_rss_fallback(db); loaded += fb['loaded']; raw += fb['raw']
        return {"status":"ok","loaded":loaded,"raw":raw,"pages":pages,"source":"gosplan_v2","server":base,"advance_min_pct":MIN_ADV,"bg_limit_rub":MAX_BG,"pricing":"5% ниже НМЦК; налог 7%","api_mode":"production" if api_key else "test","diagnostics":diag,"updated_at":datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        db.rollback()
        fb=_rss_fallback(db)
        return {'status':'ok' if fb['loaded'] else 'error','loaded':fb['loaded'],'raw':raw+fb['raw'],'pages':pages,'error':str(e) if not fb['loaded'] else None,'source':'eis_rss_fallback','server':'zakupki.gov.ru','api_mode':'public_rss','diagnostics':diag}
    finally:db.close()

def _price_from_rss(blob):
    nums=[]
    for x in re.findall(r'\d[\d\s]*(?:[.,]\d+)?',blob):
        n=_num(x)
        if n and MIN_RUB<=n<=MAX_RUB: nums.append(n)
    return max(nums) if nums else None

def _rss_fallback(db):
    loaded=raw=0; seen=set()
    keywords=['благоустройство','уборка территорий','клининг','снег','очистка крыш','ремонт кровли','озеленение','ремонт зданий','строительство']
    base='https://zakupki.gov.ru/epz/order/extendedsearch/rss.html'
    try:
        with httpx.Client(timeout=8,follow_redirects=True,headers={'User-Agent':'DealFinder/6.1'}) as client:
            for kw in keywords:
                r=client.get(base+'?searchString='+quote(kw)+'&morphology=on&pageNumber=1')
                if r.status_code>=400: continue
                root=ET.fromstring(r.text)
                entries=root.findall('.//item')
                for entry in entries[:100]:
                    raw+=1; title=(entry.findtext('title') or '').strip(); desc=(entry.findtext('description') or '').strip(); link_url=(entry.findtext('link') or '').strip()
                    blob=(title+' '+desc).lower(); m=re.search(r'(\d{19,25})',blob); ext=m.group(1) if m else link_url
                    if not ext or ext in seen: continue
                    seen.add(ext); price=_price_from_rss(blob)
                    if not price or any(x in blob for x in EXCLUDE_KEYWORDS) or not any(x in blob for x in KEYWORDS): continue
                    db.execute('INSERT OR IGNORE INTO buyers(source,external_id,title,description,url,contact,budget_rub,city,advance_pct,fit_status,fit_reasons) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('eis_rss',ext,title,desc,link_url,'',price,'',None,'ПРОВЕРИТЬ АВАНС','RSS; требуется проверка карточки')); loaded+=1
        db.commit()
    except Exception as e:
        return {'loaded':loaded,'raw':raw,'error':str(e)}
    return {'loaded':loaded,'raw':raw}
def start_loop():return None
