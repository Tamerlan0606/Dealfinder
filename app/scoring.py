import os

def calc(budget,buy,logistics=0):
    if not budget or not buy:return None
    cost=buy+logistics
    margin=budget-cost
    return {'cost':cost,'margin_rub':margin,'margin_pct':margin/budget*100}

def tender_economics(nmck, advance_pct=None, cost_pct=None, bid_discount_pct=None, tax_pct=None, security_rub=0, logistics_rub=0):
    if not nmck:return None
    discount=float(os.getenv("DEAL_BID_DISCOUNT_PCT","5")) if bid_discount_pct is None else float(bid_discount_pct)
    tax=float(os.getenv("DEAL_TAX_PCT","7")) if tax_pct is None else float(tax_pct)
    base_cost_pct=float(os.getenv("DEAL_COST_PCT","75")) if cost_pct is None else float(cost_pct)
    contract=nmck*(1-discount/100)
    tax_rub=contract*tax/100
    execution_cost=contract*base_cost_pct/100
    margin=contract-tax_rub-execution_cost-logistics_rub
    advance_rub=contract*(float(advance_pct)/100) if advance_pct is not None else None
    own_cash=max(0, execution_cost+tax_rub+logistics_rub-(advance_rub or 0))
    return {
        "nmck":nmck,
        "bid_discount_pct":discount,
        "contract_price":contract,
        "tax_pct":tax,
        "tax_rub":tax_rub,
        "execution_cost_pct":base_cost_pct,
        "execution_cost_rub":execution_cost,
        "logistics_rub":logistics_rub,
        "advance_pct":advance_pct,
        "advance_rub":advance_rub,
        "security_rub":security_rub,
        "own_cash_needed_rub":own_cash,
        "margin_rub":margin,
        "margin_pct":margin/contract*100 if contract else 0,
        "pricing_model":"НМЦК - 5%; налог 7%; затраты по умолчанию 75%"
    }
