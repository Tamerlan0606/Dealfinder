def calc(budget,buy,logistics=0):
 if not budget or not buy:return None
 cost=buy+logistics; m=budget-cost
 return {'cost':cost,'margin_rub':m,'margin_pct':m/budget*100}
