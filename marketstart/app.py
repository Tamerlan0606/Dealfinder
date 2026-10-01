import os, html, urllib.parse, io
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
from PIL import Image, ImageDraw, ImageFont

app = FastAPI(title="MarketStart AI", docs_url=None, redoc_url=None)
SITE_URL = os.getenv("SITE_URL", "https://marketstart-production.onrender.com").rstrip("/")
CPA_OUT = os.getenv("CPA_OUT", "https://cpafactory-web.onrender.com/go/1")

TOPICS = [
("nisha","Как выбрать нишу для старта на маркетплейсе"),
("unit","Юнит-экономика товара до первой поставки"),
("margin","Как считать маржу с комиссиями и логистикой"),
("card","Карточка товара: что влияет на конверсию"),
("photo","Фотографии товара без дорогой студии"),
("price","Стартовая цена и тестирование спроса"),
("supply","Первая поставка: как не заморозить деньги"),
("fbs","FBS: когда схема подходит начинающему"),
("fby","FBO/FBY: когда хранение выгоднее"),
("seo","Поисковые запросы в названии и описании"),
("reviews","Как получать отзывы без запрещенных схем"),
("returns","Возвраты: как заложить их в экономику"),
("ads","Реклама: когда ее имеет смысл включать"),
("budget","Стартовый бюджет: обязательные расходы"),
("docs","Документы и данные для регистрации продавца"),
("assort","Как расширять ассортимент по данным"),
("stock","Контроль остатков без кассовых разрывов"),
("season","Сезонность: как не закупиться на пике"),
("supplier","Проверка поставщика перед закупкой"),
("china","Импортный товар: риски до заказа партии"),
("brand","Свой бренд или перепродажа: экономика"),
("content","Контент-план для продвижения товара"),
("conversion","Как диагностировать низкую конверсию"),
("ctr","CTR карточки: что тестировать первым"),
("delivery","Логистика и стоимость доставки"),
("tax","Налоги: что учитывать в финансовой модели"),
("cashflow","Денежный поток продавца по неделям"),
("scale","Когда масштабировать успешный товар"),
("mistakes","10 ошибок начинающего продавца"),
("launch","План запуска магазина за 7 дней"),
]
FORMATS = {
"guide": ("Разбор", "Пошаговая схема с контрольными точками."),
"checklist": ("Чек-лист", "Короткий список того, что нужно проверить перед действием."),
"mistakes": ("Ошибки", "Типовые ошибки и способ снизить риск потерь."),
}

def page(title, body, canonical="/"):
    title_e = html.escape(title)
    canonical_url = SITE_URL + canonical
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_e} — MarketStart AI</title><meta name="description" content="Практический материал для запуска и развития продаж на маркетплейсе.">
<link rel="canonical" href="{canonical_url}"><style>
:root{{--bg:#07111f;--card:#101d2e;--text:#eef5ff;--muted:#9db0c7;--a:#67e8f9;--b:#22c55e}}*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(145deg,#07111f,#0b1830);color:var(--text);font:16px/1.6 system-ui,-apple-system,sans-serif}}
main{{max-width:960px;margin:auto;padding:28px 18px 70px}}nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:42px}}
.logo{{font-weight:900;font-size:20px}}a{{color:var(--a);text-decoration:none}}h1{{font-size:clamp(34px,7vw,68px);line-height:1.03;margin:10px 0 20px}}
h2{{font-size:28px;margin-top:38px}}.lead{{font-size:20px;color:#c7d7e9;max-width:760px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}}
.card{{background:rgba(16,29,46,.9);border:1px solid #223a58;border-radius:18px;padding:20px}}.cta{{display:inline-block;background:var(--b);color:#04120a;font-weight:800;padding:14px 20px;border-radius:12px;margin:14px 0}}
small,.muted{{color:var(--muted)}}ul{{padding-left:22px}}footer{{margin-top:55px;color:var(--muted);font-size:13px;border-top:1px solid #20344d;padding-top:20px}}
</style></head><body><main><nav><a class="logo" href="/">MARKETSTART AI</a><a href="/#library">База знаний</a></nav>{body}
<footer>Независимый образовательный проект. Не является официальным сервисом маркетплейса. Материалы носят информационный характер; условия площадок и партнерских программ могут меняться.</footer></main></body></html>"""

@app.get("/", response_class=HTMLResponse)
def home():
    cards = "".join(f'<a class="card" href="/guide/{slug}/guide"><b>{html.escape(title)}</b><br><small>Разбор →</small></a>' for slug,title in TOPICS[:12])
    body = f"""<p class="muted">Практикум для будущего продавца</p><h1>Запустите магазин системно, а не методом проб и ошибок</h1>
<p class="lead">7-дневный маршрут: ниша → экономика → карточка → логистика → запуск. Плюс 90 материалов по ключевым вопросам продавца.</p>
<a class="cta" href="/guide/launch/checklist">Начать с чек-листа запуска</a>
<h2>Маршрут на 7 дней</h2><div class="grid">
<div class="card"><b>День 1</b><br>Ниша, спрос, конкуренты</div><div class="card"><b>День 2</b><br>Юнит-экономика и бюджет</div>
<div class="card"><b>День 3</b><br>Регистрация и модель работы</div><div class="card"><b>День 4</b><br>Карточка и контент</div>
<div class="card"><b>День 5</b><br>Поставка и остатки</div><div class="card"><b>День 6–7</b><br>Запуск, аналитика, масштабирование</div></div>
<h2 id="library">База знаний</h2><div class="grid">{cards}</div>
<p><a href="/library">Открыть все 90 материалов →</a></p>
<h2>Готовы перейти к регистрации?</h2><p>Сначала проверьте экономику товара и документы. После этого переходите к регистрации продавца.</p>
<a class="cta" href="/go?src=home">Перейти к регистрации</a><p><small>Партнёрское раскрытие: переход может быть партнёрским; владелец проекта может получить вознаграждение, если приглашённый продавец выполнит условия программы.</small></p>"""
    return page("Запуск продавца на маркетплейсе", body)

@app.get("/library", response_class=HTMLResponse)
def library():
    cards=[]
    for slug,title in TOPICS:
        for fmt,(label,_) in FORMATS.items():
            cards.append(f'<a class="card" href="/guide/{slug}/{fmt}"><b>{html.escape(title)}</b><br><small>{label}</small></a>')
    return page("90 материалов для продавца", '<h1>База знаний</h1><p class="lead">30 тем × 3 практических формата.</p><div class="grid">'+"".join(cards)+"</div>", "/library")

@app.get("/guide/{slug}/{fmt}", response_class=HTMLResponse)
def guide(slug: str, fmt: str):
    topic = next(((s,t) for s,t in TOPICS if s==slug), None)
    if not topic or fmt not in FORMATS:
        return HTMLResponse(page("Материал не найден","<h1>Материал не найден</h1><a href='/library'>Вернуться в базу</a>"),status_code=404)
    _, title = topic
    label, desc = FORMATS[fmt]
    if fmt=="checklist":
        points=["Зафиксируйте исходные цифры и ограничения.","Посчитайте сценарий без оптимистичных допущений.","Проверьте комиссии, логистику и возвраты.","Определите метрику, по которой примете решение.","Запускайте небольшой тест и сравнивайте факт с планом."]
    elif fmt=="mistakes":
        points=["Решение без расчета юнит-экономики.","Слишком большая первая закупка.","Оценка спроса только по одному сигналу.","Игнорирование возвратов и логистики.","Масштабирование до получения устойчивой статистики."]
    else:
        points=["Сформулируйте гипотезу и целевой показатель.","Соберите исходные данные до расходования бюджета.","Рассчитайте базовый, плохой и хороший сценарии.","Проведите минимальный тест.","Масштабируйте только подтвержденный результат."]
    lis="".join(f"<li>{p}</li>" for p in points)
    body=f"""<p class="muted">{label}</p><h1>{html.escape(title)}</h1><p class="lead">{desc}</p>
<div class="card"><h2>Практический алгоритм</h2><ul>{lis}</ul></div>
<h2>Следующий шаг</h2><p>Если расчеты сходятся, переходите к созданию кабинета продавца и проверяйте актуальные условия площадки перед регистрацией.</p>
<a class="cta" href="/go?src={urllib.parse.quote(slug+'-'+fmt)}">Перейти к регистрации</a><p><small>Партнёрское раскрытие: переход может быть партнёрским; владелец проекта может получить вознаграждение при выполнении условий программы.</small></p>
<p><a href="/library">← Все материалы</a></p>"""
    return page(title, body, f"/guide/{slug}/{fmt}")

@app.get("/go")
def go(request: Request, src: str="site"):
    q = dict(request.query_params)
    q["source"] = q.get("source","marketstart")
    q["channel"] = q.get("channel",src)
    sep = "&" if "?" in CPA_OUT else "?"
    return RedirectResponse(CPA_OUT + sep + urllib.parse.urlencode(q), status_code=302)

@app.get("/health")
def health():
    return {"ok":True,"service":"marketstart-ai","topics":len(TOPICS),"pages":len(TOPICS)*len(FORMATS),"time":datetime.now(timezone.utc).isoformat()}

@app.get("/robots.txt")
def robots():
    return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")

@app.get("/sitemap.xml")
def sitemap():
    urls=[SITE_URL+"/",SITE_URL+"/library"]+[f"{SITE_URL}/guide/{s}/{f}" for s,_ in TOPICS for f in FORMATS]
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)+"</urlset>"
    return Response(xml,media_type="application/xml")

@app.get("/rss.xml")
def rss():
    items=[]
    for s,t in TOPICS[:20]:
        link=f"{SITE_URL}/guide/{s}/guide"
        items.append(f"<item><title>{html.escape(t)}</title><link>{link}</link><description>Практический разбор для продавца</description></item>")
    xml='<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>MarketStart AI</title><link>'+SITE_URL+'</link><description>База знаний продавца</description>'+''.join(items)+'</channel></rss>'
    return Response(xml,media_type="application/rss+xml")


GLOBAL_POSTS = {
    "margin": {"hook":"Revenue is not profit.","body":"Before you launch a product, model fees, fulfillment, returns, ads and taxes. A product that looks profitable at the selling price can lose money after variable costs.","cta":"Use the free marketplace launch framework at MarketStart AI."},
    "inventory": {"hook":"Your first order should be a test, not a bet.","body":"Start with the smallest inventory batch that can validate demand. Measure conversion, returns and contribution margin before you scale stock.","cta":"Build the numbers before you buy inventory."},
    "launch": {"hook":"A marketplace launch is a sequence, not a guess.","body":"Validate demand, calculate unit economics, prepare the listing, choose fulfillment, launch a small test and scale only after the data confirms the thesis.","cta":"Follow the launch framework at MarketStart AI."},
    "returns": {"hook":"Returns belong in your margin model.","body":"A 30% gross margin can disappear when return shipping, damaged inventory and marketplace fees are ignored. Model the expected return rate before setting your price.","cta":"Price for the real transaction, not the perfect one."},
    "conversion": {"hook":"Traffic cannot rescue a weak listing.","body":"Before buying more clicks, improve the first image, title, offer clarity, reviews and delivery promise. Conversion work usually comes before traffic scaling.","cta":"Fix conversion before increasing ad spend."},
    "pricing": {"hook":"The cheapest seller does not always win.","body":"Price is one variable. Delivery speed, reviews, listing quality, trust and stock availability also affect conversion. Compete on the whole offer.","cta":"Optimize the offer, not only the price."},
    "stock": {"hook":"Out of stock is a growth tax.","body":"Stockouts break ranking momentum and waste acquisition work. Track sell-through rate and reorder lead time so replenishment starts before inventory becomes critical.","cta":"Treat inventory planning as part of marketing."},
    "ads": {"hook":"Ads amplify economics. They do not fix them.","body":"If contribution margin is negative before advertising, more traffic usually scales the loss. Know your break-even acquisition cost before launching campaigns.","cta":"Calculate break-even CAC before buying traffic."},
    "supplier": {"hook":"Your supplier quote is not your landed cost.","body":"Include freight, duties, inspection, packaging, payment fees and defect allowance. Compare suppliers on landed cost and reliability, not unit price alone.","cta":"Model landed cost before choosing a supplier."},
    "reviews": {"hook":"Reviews are a conversion asset.","body":"Customers use recent reviews to reduce purchase risk. Improve product quality, instructions, packaging and support so review growth comes from a better customer experience.","cta":"Engineer the experience that earns better reviews."},
    "cashflow": {"hook":"Profit can grow while cash disappears.","body":"Inventory businesses pay for stock before many sales are collected. Forecast purchase timing, marketplace payout delays and taxes so growth does not create a cash gap.","cta":"Scale with a cash-flow plan, not only a P&L."},
    "testing": {"hook":"One test should answer one question.","body":"Change one major variable at a time: price, hero image, title or promotion. Clean tests make it easier to identify what actually moved conversion.","cta":"Make every experiment produce a decision."}
}

@app.get("/global", response_class=HTMLResponse)
def global_home():
    cards = "".join(
        f'<div class="card"><b>{html.escape(v["hook"])}</b><br><small>{html.escape(v["body"])}</small></div>'
        for v in GLOBAL_POSTS.values()
    )
    body = f"""<p class="muted">Marketplace launch framework</p>
<h1>Build the economics before you scale the product</h1>
<p class="lead">A practical framework for international marketplace sellers: demand validation, unit economics, inventory testing, listing conversion and controlled scaling.</p>
<div class="grid">{cards}</div>
<h2>Operating rule</h2><p>Test small, measure contribution margin, and scale only what the data validates.</p>
<p><small>This page is educational. Marketplace fees, tax rules and program availability vary by country and platform.</small></p>"""
    return page("Marketplace Launch Framework", body, "/global")

@app.get("/api/social/tiktok")
def tiktok_content():
    return {
        "audience": "international",
        "language": "en",
        "landing": SITE_URL + "/global",
        "posts": [
            {
                "slug": slug,
                "text": f'{data["hook"]}\n\n{data["body"]}\n\n{data["cta"]}\n\n#ecommerce #marketplace #onlinebusiness #sellertips',
                "media": SITE_URL + f"/media/tiktok/{slug}.png"
            }
            for slug, data in GLOBAL_POSTS.items()
        ]
    }

@app.get("/media/tiktok/{slug}.png")
def tiktok_media(slug: str):
    data = GLOBAL_POSTS.get(slug)
    if not data:
        return Response(status_code=404)
    img = Image.new("RGB", (1080, 1350), (7, 17, 31))
    draw = ImageDraw.Draw(img)
    try:
        bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        regular = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 42)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    except Exception:
        bold = regular = small = ImageFont.load_default()
    draw.text((72, 70), "MARKETSTART AI", font=small, fill=(103, 232, 249))
    def wrap(text, font, max_width):
        words=text.split(); lines=[]; line=""
        for word in words:
            test=(line+" "+word).strip()
            if draw.textbbox((0,0), test, font=font)[2] <= max_width:
                line=test
            else:
                if line: lines.append(line)
                line=word
        if line: lines.append(line)
        return lines
    y=230
    for line in wrap(data["hook"], bold, 930):
        draw.text((72,y), line, font=bold, fill=(238,245,255)); y += 92
    y += 55
    for line in wrap(data["body"], regular, 930):
        draw.text((72,y), line, font=regular, fill=(199,215,233)); y += 58
    draw.rounded_rectangle((72,1120,1008,1260), radius=28, fill=(34,197,94))
    draw.text((110,1165), "marketstart-production.onrender.com/global", font=small, fill=(4,18,10))
    out=io.BytesIO(); img.save(out, format="PNG", optimize=True); out.seek(0)
    return Response(out.getvalue(), media_type="image/png", headers={"Cache-Control":"public, max-age=86400"})
