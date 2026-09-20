import os, re, time, threading
from datetime import datetime
import httpx
from .db import connect

REGIONS = [x.strip().lower() for x in os.getenv("DEAL_REGIONS","Ростовская область,Ставропольский край,Республика Ингушетия,Кабардино-Балкарская Республика,Республика Северная Осетия — Алания,Краснодарский край,Москва,Московская область").split(",") if x.strip()]
KEYWORDS = [x.strip().lower() for x in os.getenv("DEAL_KEYWORDS","благоустройство,строитель,капитальн,ремонт,кровл,фасад,монтаж,дорог,озелен,площадк,тротуар,освещен,водопровод,канализац,теплоснабж,электромонтаж").split(",") if x.strip()]
MIN_RUB=float(os.getenv("DEAL_MIN_RUB","10000000"))
MAX_RUB=float(os.getenv("DEAL_MAX_RUB","90000000"))

def _num(v):
    if isinstance(v,(int,float)): return float(v)
    try: return float(re.sub(r"[^0-9.]","",str(v).replace("\xa0","").replace(" ","").replace(",", ".")))
    except: return None

def refresh():
    db=connect(os.getenv("DB_PATH","deals.db"))
    loaded=0; raw=0; pages=0
    headers={"User-Agent":"Mozilla/5.0 (compatible; DealFinder/2.0)"}
    try:
        for kw in KEYWORDS[:10]:
            url="https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString="+__import__("urllib.parse").parse.quote(kw)
            try:
                r=httpx.get(url,headers=headers,timeout=25,follow_redirects=True)
                if r.status_code!=200: continue
                pages+=1
                html=r.text
                links=re.findall(r"""href=["']([^"']*common-info[^"']*)["']""",html,re.I)
                raw+=len(links)
                for link in links[:100]:
                    if link.startswith("/"): link="https://zakupki.gov.ru"+link
                    m=re.search(r"regNumber[=/]([0-9]{10,})",link)
                    if not m: continue
                    ext=m.group(1)
                    pos=html.find(link)
                    chunk=re.sub(r"<[^>]+>"," ",html[max(0,pos-2500):pos+2500])
                    chunk=re.sub(r"\s+"," ",chunk).strip()
                    low=chunk.lower()
                    if REGIONS and not any(x in low for x in REGIONS): continue
                    if not any(x in low for x in KEYWORDS): continue
                    price=None
                    for n in re.findall(r"(?<![0-9])([0-9]{7,12}(?:[.,][0-9]{1,2})?)(?![0-9])",chunk.replace(" ","")):
                        v=_num(n)
                        if v and MIN_RUB<=v<=MAX_RUB: price=v; break
                    if not price: continue
                    title=chunk[:500] or kw
                    db.execute("""INSERT INTO buyers(source,external_id,title,description,url,contact,budget_rub,city)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,description=excluded.description,url=excluded.url,budget_rub=excluded.budget_rub,city=excluded.city""",
                    ("eis_public",ext,title,chunk[:1500],link,"",price,""))
                    loaded+=1
            except Exception:
                continue
        db.commit()
        return {"status":"ok","loaded":loaded,"raw":raw,"pages":pages,"source":"eis_public","updated_at":datetime.utcnow().isoformat()+"Z"}
    except Exception as e:
        return {"status":"error","error":str(e),"source":"eis_public"}
    finally:
        db.close()

def start_loop():
    def loop():
        while True:
            try: refresh()
            except Exception: pass
            time.sleep(int(os.getenv("REFRESH_SECONDS","3600")))
    threading.Thread(target=loop,daemon=True).start()
