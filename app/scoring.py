import os, re

CATEGORY_COSTS={
    "уборк":65,"клининг":62,"снег":60,"зимн":60,"налед":58,"сосул":58,
    "очистк крыш":58,"кровл":70,"крыш":70,"озелен":72,"благоустрой":72,
    "тротуар":74,"площадк":73,"спортив":75,"стадион":76,"фасад":72,
    "ремонт":76,"капитальн":77,"строительств":78,"общестро":78,"монтаж":78,
}
CATEGORY_STARTUP={
    "уборк":0.25,"клининг":0.25,"снег":0.30,"зимн":0.30,"налед":0.30,
    "сосул":0.30,"очистк крыш":0.30,"кровл":0.38,"крыш":0.38,
    "озелен":0.38,"благоустрой":0.40,"тротуар":0.42,"площадк":0.42,
    "спортив":0.42,"стадион":0.45,"фасад":0.40,"ремонт":0.42,
    "капитальн":0.45,"строительств":0.48,"общестро":0.48,"монтаж":0.45,
}

def calc(budget,buy,logistics=0):
    if not budget or not buy:return None
    cost=buy+logistics
    margin=budget-cost
    return {"cost":cost,"margin_rub":margin,"margin_pct":margin/budget*100}

def _matches(text, table):
    t=(text or "").lower()
    return [(k,p) for k,p in table.items() if k in t]

def analyze_scope(text):
    matches=_matches(text,CATEGORY_COSTS)
    if not matches:
        return {"cost_pct":float(os.getenv("DEAL_COST_PCT","75")),"startup_pct":0.42,
                "categories":["общестроительный базовый профиль"],"confidence":"низкая"}
    # Weight longer/more specific terms first, while keeping mixed scopes conservative.
    weighted=[]
    for k,p in matches:
        occurrences=max(1,(text.lower().count(k)))
        weighted.append((p,occurrences,k))
    total=sum(w for _,w,_ in weighted)
    cost=sum(p*w for p,w,_ in weighted)/total
    startup_matches=[(CATEGORY_STARTUP.get(k,0.42),w) for _,w,k in weighted]
    startup=sum(p*w for p,w in startup_matches)/sum(w for _,w in startup_matches)
    return {"cost_pct":round(cost,2),"startup_pct":round(startup,3),
            "categories":[k for _,_,k in weighted],"confidence":"средняя"}

def detect_cost_pct(text):
    a=analyze_scope(text)
    return a["cost_pct"], ",".join(a["categories"])

def _num_from_text(s):
    if s is None:return None
    s=str(s).replace("\xa0","").replace(" ","").replace(",",".")
    m=re.search(r"\d+(?:\.\d+)?",s)
    return float(m.group()) if m else None

def estimate_from_documents(text):
    # Estimate sheets often contain: item + quantity + unit price + total.
    # We do not pretend every number is a cost; only repeated ruble-like totals are used.
    vals=[]
    for line in (text or "").splitlines():
        if not re.search(r"руб|₽|стоим|цена|сумм|итого|всего|total",line,re.I):
            continue
        nums=re.findall(r"\d[\d\s]*(?:[.,]\d+)?",line)
        for raw in nums:
            n=_num_from_text(raw)
            if n and n>=1000: vals.append(n)
    if len(vals)<3:return {"available":False,"confidence":"нет данных","document_total_rub":None}
    vals=sorted(vals)
    # The largest repeated figure is often a total; use a robust candidate only as a signal.
    candidate=vals[-1]
    return {"available":True,"confidence":"низкая","document_total_rub":candidate,
            "sample_values":vals[-20:]}

def tender_economics(nmck, advance_pct=None, cost_pct=None, bid_discount_pct=None,
                     tax_pct=None, security_rub=0, logistics_rub=0, description="",
                     document_text="", advance_delay_days=0):
    if not nmck:return None
    discount=float(os.getenv("DEAL_BID_DISCOUNT_PCT","5")) if bid_discount_pct is None else float(bid_discount_pct)
    tax=float(os.getenv("DEAL_TAX_PCT","7")) if tax_pct is None else float(tax_pct)
    scope=analyze_scope((description or "")+" "+(document_text or ""))
    base_cost_pct=scope["cost_pct"] if cost_pct is None else float(cost_pct)
    contract=nmck*(1-discount/100)
    tax_rub=contract*tax/100
    execution_cost=contract*base_cost_pct/100
    advance_rub=contract*(float(advance_pct)/100) if advance_pct is not None else None
    startup_pct=scope["startup_pct"]
    startup_cash=execution_cost*startup_pct
    tax_cash=tax_rub*0.35
    bg_fee_pct=float(os.getenv("DEAL_BG_FEE_PCT","1.5"))
    bg_fee=security_rub*bg_fee_pct/100
    delay_buffer=contract*(0.01/100)*max(0,float(advance_delay_days))
    own_cash=max(0,startup_cash+tax_cash+logistics_rub+bg_fee+delay_buffer-(advance_rub or 0))
    reserve_pct=float(os.getenv("DEAL_RISK_RESERVE_PCT","3"))
    reserve=contract*reserve_pct/100
    margin=contract-tax_rub-execution_cost-logistics_rub-reserve
    margin_pct=margin/contract*100 if contract else 0
    return {
        "nmck":nmck,"bid_discount_pct":discount,"contract_price":contract,
        "tax_pct":tax,"tax_rub":tax_rub,"execution_cost_pct":base_cost_pct,
        "execution_cost_rub":execution_cost,"logistics_rub":logistics_rub,
        "advance_pct":advance_pct,"advance_rub":advance_rub,"security_rub":security_rub,
        "bg_fee_pct":bg_fee_pct,"bg_fee_rub":bg_fee,
        "startup_cost_pct":startup_pct,"startup_cash_rub":startup_cash,
        "own_cash_needed_rub":own_cash,"risk_reserve_pct":reserve_pct,"risk_reserve_rub":reserve,
        "margin_rub":margin,"margin_pct":margin_pct,
        "cost_category":scope["categories"],"model_confidence":scope["confidence"],
        "document_estimate":estimate_from_documents(document_text),
        "pricing_model":"НМЦК - 5%; налог 7%; состав работ; резерв 3%; стартовый cash-gap",
    }
