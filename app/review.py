import os, re, json
from datetime import datetime, timezone
import httpx
from .db import connect
from .documents import collect_documents
from .scoring import tender_economics

def _advance(text):
    patterns=[
        r"аванс[^%]{0,180}(\d{1,3}(?:[.,]\d+)?)\s*%",
        r"предоплат[^%]{0,180}(\d{1,3}(?:[.,]\d+)?)\s*%",
        r"(\d{1,3}(?:[.,]\d+)?)\s*%[^.]{0,120}(?:аванс|предоплат)",
    ]
    for p in patterns:
        m=re.search(p,text or "",re.I)
        if m:
            try:return float(m.group(1).replace(",","."))
            except Exception:pass
    return None

def _deadline(text):
    dates=re.findall(r"\d{2}[.]\d{2}[.]\d{4}|\d{4}-\d{2}-\d{2}",text or "")
    if not dates:return None
    for raw in reversed(dates):
        try:
            if "." in raw:return datetime.strptime(raw,"%d.%m.%Y").strftime("%Y-%m-%d")
            return datetime.strptime(raw,"%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:pass
    return None

def review_unknown(db_path, limit=30):
    c=connect(db_path)
    rows=c.execute("SELECT * FROM buyers WHERE fit_status='ПРОВЕРИТЬ АВАНС' OR document_text IS NULL ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    results=[]
    minimum=float(os.getenv("DEAL_MIN_ADVANCE_PCT","20"))
    with httpx.Client(timeout=35,follow_redirects=True,headers={"User-Agent":"DealFinder/6.0"}) as client:
        for row in rows:
            d=dict(row); card_text=""
            try:
                r=client.get(d.get("url") or "")
                if r.status_code < 400:
                    card_text=re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>"," ",r.text,flags=re.I|re.S).lower()
            except Exception:
                pass
            docs=collect_documents(d.get("url") or "")
            doc_text=docs.get("combined_text","")
            all_text=(card_text+"\n"+doc_text).lower()
            adv=d.get("advance_pct")
            if adv is None: adv=_advance(all_text)
            deadline=d.get("deadline") or _deadline(card_text)
            sec=d.get("security_rub")
            # A second-stage check catches explicit contract-security percentages/amounts.
            if sec is None and d.get("budget_rub"):
                m=re.search(r"обеспечени[ея]\s+(?:исполнения|контракта)[^%]{0,120}(\d{1,3}(?:[.,]\d+)?)\s*%",all_text,re.I)
                if m:
                    sec=d["budget_rub"]*float(m.group(1).replace(",","."))/100
            if adv is not None and adv >= minimum:
                status="ЗАХОДИМ"; reason="аванс подтвержден карточкой/документами"
            elif adv is not None:
                status="ОТБОЙ"; reason=f"аванс ниже {minimum:.0f}%"
            else:
                status="ПРОВЕРИТЬ АВАНС"; reason="аванс не найден в доступных материалах"
            e=tender_economics(d.get("budget_rub"),adv,security_rub=sec or 0,
                               description=(d.get("title") or "")+" "+(d.get("description") or ""),
                               document_text=doc_text)
            c.execute("""UPDATE buyers SET advance_pct=?,advance_rub=?,deadline=?,security_rub=?,
                         document_links=?,document_text=?,economics_json=?,fit_status=?,fit_reasons=?,
                         review_status=?,reviewed_at=? WHERE id=?""",
                      (adv,(d.get("budget_rub")*adv/100 if adv is not None else None),deadline,sec,
                       json.dumps(docs.get("links",[]),ensure_ascii=False),doc_text[:100000],
                       json.dumps(e,ensure_ascii=False) if e else None,status,reason,"done",
                       datetime.now(timezone.utc).isoformat(),d["id"]))
            d.update(advance_pct=adv,advance_rub=(d.get("budget_rub")*adv/100 if adv is not None else None),
                     deadline=deadline,security_rub=sec,document_links=docs.get("links",[]),
                     economics=e,fit_status=status,fit_reasons=reason)
            results.append(d)
    c.commit(); c.close()
    return {"checked":len(results),"results":results}
