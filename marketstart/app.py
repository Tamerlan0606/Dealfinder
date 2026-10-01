import os, html, urllib.parse
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response

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
