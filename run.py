import os, json, urllib.request, urllib.error, datetime, sqlite3, re, time
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg=None

WORDSTAT_URL=os.getenv("YANDEX_WORDSTAT_URL","https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests")
FOLDER_ID=os.getenv("YANDEX_WORDSTAT_FOLDER_ID") or os.getenv("YANDEX_FOLDER_ID") or os.getenv("YC_FOLDER_ID") or ""
REGION_IDS=[x.strip() for x in os.getenv("YANDEX_WORDSTAT_REGIONS","225").split(",") if x.strip()]
DEVICES=[x.strip() for x in os.getenv("YANDEX_WORDSTAT_DEVICES","DEVICE_ALL").split(",") if x.strip()]
MAX_SEEDS=max(1,min(int(os.getenv("YANDEX_WORDSTAT_MAX_SEEDS","40") or 40),80))
HOURLY_BUDGET=max(1,min(int(os.getenv("YANDEX_WORDSTAT_HOURLY_BUDGET","80") or 80),95))
TOP_PER_SEED=max(1,min(int(os.getenv("YANDEX_WORDSTAT_TOP_PER_SEED","50") or 50),2000))

def using_sqlite():
    url=os.getenv("DATABASE_URL","")
    return (not url) or url.startswith("$"+"{{")

def db():
    url=os.getenv("DATABASE_URL","")
    if using_sqlite() and os.getenv("CPA_ALLOW_SQLITE","0").lower() not in {"1","true","yes"}:
        raise RuntimeError("DATABASE_URL is required in production; SQLite fallback is disabled")
    if using_sqlite():
        c=sqlite3.connect("/tmp/cpafactory.db")
        c.row_factory=sqlite3.Row
        return c
    if not psycopg:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(url,row_factory=dict_row)

def exec_sql(c,sql,params=()):
    return c.execute(sql.replace("%s","?") if using_sqlite() else sql,params)

def init_schema():
    with db() as c:
        if using_sqlite():
            exec_sql(c,"create table if not exists wordstat_runs(id integer primary key autoincrement,run_date text unique,status text,seed_count integer default 0,result_count integer default 0,error text,created_at text default current_timestamp)")
            exec_sql(c,"create table if not exists wordstat_queries(id integer primary key autoincrement,run_date text,seed_phrase text,phrase text,count real default 0,regions text,devices text,source text default 'yandex_wordstat',created_at text default current_timestamp,unique(run_date,phrase,regions,devices))")
        else:
            exec_sql(c,"create table if not exists wordstat_runs(id bigserial primary key,run_date date unique not null,status text,seed_count integer default 0,result_count integer default 0,error text,created_at timestamptz default now())")
            exec_sql(c,"create table if not exists wordstat_queries(id bigserial primary key,run_date date not null,seed_phrase text,phrase text not null,count double precision default 0,regions text,devices text,source text default 'yandex_wordstat',created_at timestamptz default now(),unique(run_date,phrase,regions,devices))")

def _clean_seed(v):
    s=re.sub("[^0-9A-Za-zА-Яа-яЁё -]+"," ",str(v or ""))
    s=" ".join(s.split()).strip()
    return s[:200] if len(s)>=2 else ""

def get_seeds():
    seeds=[]; seen=set()
    def add(v):
        s=_clean_seed(v)
        if s and s.lower() not in seen:
            seen.add(s.lower()); seeds.append(s)
    with db() as c:
        rows=exec_sql(c,"select name,category from offers where active=true order by coalesce(demand_count,0) desc,coalesce(epc,0) desc limit %s",(MAX_SEEDS*3,)).fetchall()
        for row in rows:
            add(row["name"]); add(row["category"])
    for value in os.getenv("YANDEX_WORDSTAT_EXTRA_SEEDS","").split("|"): add(value)
    for value in os.getenv("YANDEX_WORDSTAT_MARKET_SEEDS","стройка|ремонт|инструмент|строительная техника|дом|авто|электроника|смартфоны|компьютеры|товары для бизнеса|оборудование").split("|"): add(value)
    return seeds[:MAX_SEEDS]

def _http_error(e):
    body=""
    try: body=e.read(3000).decode("utf-8","replace")
    except Exception: pass
    return f"HTTP {getattr(e,'code','?')}: {body[:3000] or str(e)}"

def request_top(phrase):
    if not FOLDER_ID: raise RuntimeError("YANDEX_WORDSTAT_FOLDER_ID is not configured")
    token=os.getenv("YANDEX_WORDSTAT_API_KEY","").strip()
    if not token: raise RuntimeError("YANDEX_WORDSTAT_API_KEY is not configured")
    body={"folderId":FOLDER_ID,"phrase":phrase,"numPhrases":TOP_PER_SEED,"regions":REGION_IDS,"devices":DEVICES}
    req=urllib.request.Request(WORDSTAT_URL,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),headers={"Authorization":"Api-Key "+token,"Content-Type":"application/json","Accept":"application/json","User-Agent":"CPAFactory/4.0"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(_http_error(e))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e}")

def _items(data):
    for key in ("results","topRequests","top_requests","phrases"):
        value=data.get(key)
        if isinstance(value,list): return value
    return []

def _phrase_count(item):
    phrase=item.get("phrase") or item.get("query") or item.get("text") or ""
    count=item.get("count")
    if count is None: count=item.get("frequency")
    if count is None: count=item.get("shows")
    try: count=float(count or 0)
    except Exception: count=0.0
    return str(phrase).strip(),count

def _update_offer_demand(seed,max_count):
    if max_count<=0: return
    with db() as c:
        exec_sql(c,"update offers set demand_count=%s,demand_checked_at=current_timestamp,yandex_promise=%s where active=true and (lower(name)=lower(%s) or lower(category)=lower(%s))",(max_count,max_count,seed,seed))

def _already_ok(run_date):
    with db() as c:
        row=exec_sql(c,"select status,result_count from wordstat_runs where run_date=%s",(run_date,)).fetchone()
    return bool(row and row["status"]=="ok")

def _try_run_lock():
    """Cross-process lock. PostgreSQL lock is session-scoped; SQLite uses best-effort only."""
    if using_sqlite():
        return None, True
    c=db()
    row=exec_sql(c,"select pg_try_advisory_lock(%s) as locked",(847261903,)).fetchone()
    if not row or not row["locked"]:
        c.close()
        return None, False
    return c, True

def _release_run_lock(c):
    if c is None: return
    try: exec_sql(c,"select pg_advisory_unlock(%s)",(847261903,))
    finally: c.close()

def run(force=False):
    init_schema()
    if not os.getenv("YANDEX_WORDSTAT_API_KEY"): raise RuntimeError("YANDEX_WORDSTAT_API_KEY is not configured")
    if not FOLDER_ID: raise RuntimeError("YANDEX_WORDSTAT_FOLDER_ID is not configured")
    run_date=datetime.datetime.utcnow().date().isoformat()
    if not force and _already_ok(run_date):
        print(json.dumps({"status":"skipped","reason":"already_ok","date":run_date},ensure_ascii=False),flush=True)
        return 0
    lock_conn, locked=_try_run_lock()
    if not locked:
        print(json.dumps({"status":"skipped","reason":"already_running","date":run_date},ensure_ascii=False),flush=True)
        return 0
    try:
        # Re-check after acquiring the cross-process lock.
        if not force and _already_ok(run_date):
            print(json.dumps({"status":"skipped","reason":"already_ok","date":run_date},ensure_ascii=False),flush=True)
            return 0
        seeds=get_seeds()[:HOURLY_BUDGET]; total=0; errors=[]; rate_limited=False
        with db() as c:
            exec_sql(c,"insert into wordstat_runs(run_date,status,seed_count,result_count) values(%s,'running',%s,0) on conflict(run_date) do update set status=case when wordstat_runs.status='ok' then 'ok' else 'running' end,seed_count=%s,error=case when wordstat_runs.status='ok' then wordstat_runs.error else null end",(run_date,len(seeds),len(seeds)))
        for seed in seeds:
            try:
                data=request_top(seed)
                items=_items(data); seed_max=0.0
                with db() as c:
                    for item in items:
                        phrase,count=_phrase_count(item)
                        if not phrase: continue
                        seed_max=max(seed_max,count)
                        exec_sql(c,"insert into wordstat_queries(run_date,seed_phrase,phrase,count,regions,devices) values(%s,%s,%s,%s,%s,%s) on conflict(run_date,phrase,regions,devices) do update set count=excluded.count,seed_phrase=excluded.seed_phrase",(run_date,seed,phrase,count,",".join(REGION_IDS),",".join(DEVICES)))
                        total+=1
                _update_offer_demand(seed,seed_max)
                # Stay comfortably below the provider's hourly quota. The daily
                # job never spends more than HOURLY_BUDGET requests.
                time.sleep(0.10)
            except Exception as e:
                errors.append(f"{seed}: {type(e).__name__}: {e}")
                if "HTTP 429" in str(e):
                    rate_limited=True
                    print("CPA_WORDSTAT_RATE_LIMITED; stopping remaining seeds",flush=True)
                    break
        status="ok" if not errors else ("rate_limited" if rate_limited else "partial")
        with db() as c:
            # Never destroy a previously successful daily result with a later failed/forced run.
            exec_sql(c,"update wordstat_runs set status=case when status='ok' and %s<>'ok' then status else %s end,result_count=case when status='ok' and %s<>'ok' then result_count else %s end,error=case when status='ok' and %s<>'ok' then error else %s end where run_date=%s",(status,status,status,total,status," ".join(errors)[:10000],run_date))
        result={"status":status,"date":run_date,"seeds":len(seeds),"results":total,"errors":errors[:10]}
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return 0 if not errors else 2
    finally:
        _release_run_lock(lock_conn)

if __name__=="__main__":
    raise SystemExit(run())
