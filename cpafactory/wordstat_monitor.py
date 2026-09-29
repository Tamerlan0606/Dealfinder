import os, json, urllib.request, datetime, sqlite3, re, time
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None

# Current Yandex Wordstat API is exposed through Yandex Search API.
WORDSTAT_URL = os.getenv("YANDEX_WORDSTAT_URL", "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests")
FOLDER_ID = os.getenv("YANDEX_WORDSTAT_FOLDER_ID") or os.getenv("YANDEX_FOLDER_ID") or ""
REGION_IDS = [x.strip() for x in os.getenv("YANDEX_WORDSTAT_REGIONS", "225").split(",") if x.strip()]
DEVICES = [x.strip() for x in os.getenv("YANDEX_WORDSTAT_DEVICES", "DEVICE_ALL").split(",") if x.strip()]
MAX_SEEDS = max(1, min(int(os.getenv("YANDEX_WORDSTAT_MAX_SEEDS", "30") or 30), 100))
TOP_PER_SEED = max(1, min(int(os.getenv("YANDEX_WORDSTAT_TOP_PER_SEED", "50") or 50), 2000))

def db():
    url = os.getenv("DATABASE_URL", "")
    if url and not url.startswith("$") and psycopg:
        return psycopg.connect(url, row_factory=dict_row)
    conn = sqlite3.connect("/tmp/cpafactory.db")
    conn.row_factory = sqlite3.Row
    return conn

def exec_sql(c, sql, params=()):
    return c.execute(sql.replace("%s", "?"), params)

def init_schema():
    with db() as c:
        exec_sql(c, """create table if not exists wordstat_runs(
          id integer primary key autoincrement, run_date text unique, status text,
          seed_count integer default 0, result_count integer default 0, error text,
          created_at text default current_timestamp)""")
        exec_sql(c, """create table if not exists wordstat_queries(
          id integer primary key autoincrement, run_date text, seed_phrase text,
          phrase text, count real default 0, regions text, devices text,
          source text default "yandex_wordstat", created_at text default current_timestamp,
          unique(run_date, phrase, regions, devices))""")

def get_seeds():
    seeds = set()
    with db() as c:
        try:
            rows = exec_sql(c, "select name, category from offers where active=true order by coalesce(demand_count,0) desc, coalesce(epc,0) desc limit %s", (MAX_SEEDS * 2,)).fetchall()
        except Exception:
            rows = []
        for r in rows:
            for v in (r[0], r[1]):
                if v:
                    s = re.sub(r"[^0-9A-Za-zА-Яа-яЁё -]+", " ", str(v))
                    s = re.sub(r"\\s+", " ", s).strip()
                    if len(s) >= 2:
                        seeds.add(s[:200])
    for s in os.getenv("YANDEX_WORDSTAT_EXTRA_SEEDS", "").split("|"):
        s = re.sub(r"\\s+", " ", s).strip()
        if len(s) >= 2:
            seeds.add(s[:200])
    return list(seeds)[:MAX_SEEDS]

def request_top(phrase):
    if not FOLDER_ID:
        raise RuntimeError("YANDEX_WORDSTAT_FOLDER_ID is not configured")
    body = {
        "folderId": FOLDER_ID,
        "phrase": phrase,
        "numPhrases": TOP_PER_SEED,
        "regions": REGION_IDS,
        "devices": DEVICES,
    }
    req = urllib.request.Request(
        WORDSTAT_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Api-Key " + os.environ["YANDEX_WORDSTAT_API_KEY"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CPAFactory/3.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def _items(data):
    # Keep compatibility with minor response-shape changes.
    for key in ("topRequests", "top_requests", "phrases", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []

def _phrase_count(item):
    phrase = item.get("phrase") or item.get("query") or item.get("text") or ""
    count = item.get("count")
    if count is None:
        count = item.get("frequency")
    if count is None:
        count = item.get("shows")
    try:
        count = float(count or 0)
    except Exception:
        count = 0.0
    return str(phrase).strip(), count

def _update_offer_demand(seed, max_count):
    if max_count <= 0:
        return
    with db() as c:
        # Match the Wordstat seed to the active offer name/category.
        exec_sql(c, """update offers set demand_count=%s, demand_checked_at=current_timestamp,
          yandex_promise=%s
          where active=true and (lower(name)=lower(%s) or lower(category)=lower(%s))""",
                 (max_count, max_count, seed, seed))

def run():
    init_schema()
    if not os.getenv("YANDEX_WORDSTAT_API_KEY"):
        raise RuntimeError("YANDEX_WORDSTAT_API_KEY is not configured")
    if not FOLDER_ID:
        raise RuntimeError("YANDEX_WORDSTAT_FOLDER_ID is not configured")

    run_date = datetime.datetime.utcnow().date().isoformat()
    seeds = get_seeds()
    total = 0
    errors = []

    with db() as c:
        exec_sql(c, """insert into wordstat_runs(run_date,status,seed_count,result_count)
          values(%s,'running',%s,0)
          on conflict(run_date) do update set status='running',seed_count=%s,error=null""",
                 (run_date, len(seeds), len(seeds)))

    for seed in seeds:
        try:
            data = request_top(seed)
            items = _items(data)
            seed_max = 0.0
            with db() as c:
                for item in items:
                    phrase, count = _phrase_count(item)
                    if not phrase:
                        continue
                    seed_max = max(seed_max, count)
                    exec_sql(c, """insert into wordstat_queries(
                      run_date,seed_phrase,phrase,count,regions,devices)
                      values(%s,%s,%s,%s,%s,%s)
                      on conflict(run_date,phrase,regions,devices)
                      do update set count=excluded.count,seed_phrase=excluded.seed_phrase""",
                             (run_date, seed, phrase, count, ",".join(REGION_IDS), ",".join(DEVICES)))
                    total += 1
            _update_offer_demand(seed, seed_max)
            time.sleep(0.05)
        except Exception as e:
            errors.append(f"{seed}: {type(e).__name__}: {e}")

    with db() as c:
        exec_sql(c, "update wordstat_runs set status=%s,result_count=%s,error=%s where run_date=%s",
                 ("ok" if not errors else "partial", total, "\n".join(errors)[:5000], run_date))

    result = {"status": "ok" if not errors else "partial", "date": run_date,
              "seeds": len(seeds), "results": total, "errors": errors[:5]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 2

if __name__ == "__main__":
    raise SystemExit(run())
