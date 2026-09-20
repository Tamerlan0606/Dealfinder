import os, re
from datetime import datetime, timezone
import httpx
from .db import connect

def review_unknown(db_path, limit=30):
    c=connect(db_path)
    rows=c.execute("SELECT * FROM buyers WHERE fit_status='ПРОВЕРИТЬ АВАНС' ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    results=[]
    minimum=float(os.getenv("DEAL_MIN_ADVANCE_PCT","20"))
    with httpx.Client(timeout=20,follow_redirects=True,headers={"User-Agent":"DealFinder/5.1"}) as client:
        for row in rows:
            d=dict(row); text_blob=""
            try:
                r=client.get(d.get("url") or "")
                if r.status_code < 400:
                    text_blob=re.sub(r"<[^>]+>"," ",r.text).lower()
            except Exception:
                pass
            adv=d.get("advance_pct")
            if adv is None:
                patterns=[
                    r"аванс[^%]{0,160}(\d{1,3}(?:[.,]\d+)?)\s*%",
                    r"предоплат[^%]{0,160}(\d{1,3}(?:[.,]\d+)?)\s*%",
                    r"(\d{1,3}(?:[.,]\d+)?)\s*%[^.]{0,100}аванс"
                ]
                for pattern in patterns:
                    m=re.search(pattern,text_blob,re.I)
                    if m:
                        try:
                            adv=float(m.group(1).replace(",","."))
                            break
                        except Exception:
                            pass
            deadline=d.get("deadline")
            if not deadline:
                dates=re.findall(r"\d{2}[.]\d{2}[.]\d{4}|\d{4}-\d{2}-\d{2}",text_blob)
                if dates:
                    deadline=dates[-1]
            if adv is not None and adv >= minimum:
                status="ЗАХОДИМ"; reason="аванс подтвержден доступной карточкой"
            elif adv is not None:
                status="ОТБОЙ"; reason=f"аванс ниже {minimum:.0f}%"
            else:
                status="ПРОВЕРИТЬ АВАНС"; reason="аванс не найден в доступной карточке"
            c.execute("UPDATE buyers SET advance_pct=?,advance_rub=?,deadline=?,fit_status=?,fit_reasons=?,review_status=?,reviewed_at=? WHERE id=?",
                      (adv,(d.get("budget_rub")*adv/100 if adv is not None else None),deadline,status,reason,"done",datetime.now(timezone.utc).isoformat(),d["id"]))
            d.update(advance_pct=adv,advance_rub=(d.get("budget_rub")*adv/100 if adv is not None else None),deadline=deadline,fit_status=status,fit_reasons=reason)
            results.append(d)
    c.commit(); c.close()
    return {"checked":len(results),"results":results}
