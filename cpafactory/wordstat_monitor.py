import os, json, urllib.request, datetime, sqlite3, re
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None

WORDSTAT_URL = os.getenv('YANDEX_WORDSTAT_URL', 'https://searchapi.api.cloud.yandex.net/v2/wordstat/top')
REGION_IDS = [x.strip() for x in os.getenv('YANDEX_WORDSTAT_REGIONS', '225').split(',') if x.strip()]
DEVICES = [x.strip() for x in os.getenv('YANDEX_WORDSTAT_DEVICES', 'DEVICE_ALL').split(',') if x.strip()]
MAX_SEEDS = max(1, min(int(os.getenv('YANDEX_WORDSTAT_MAX_SEEDS', '30') or 30), 100))

def db():
    url = os.getenv('DATABASE_URL', '')
    if url and not url.startswith('$') and psycopg:
        return psycopg.connect(url, row_factory=dict_row)
    conn = sqlite3.connect('/tmp/cpafactory.db')
    conn.row_factory = sqlite3.Row
    return conn

def exec_sql(c, sql, params=()):
    return c.execute(sql.replace('%s', '?'), params)

def init_schema():
    with db() as c:
        exec_sql(c, '''create table if not exists wordstat_runs(id integer primary key autoincrement, run_date text unique, status text, seed_count integer default 0, result_count integer default 0, error text, created_at text default current_timestamp)''')
        exec_sql(c, '''create table if not exists wordstat_queries(id integer primary key autoincrement, run_date text, seed_phrase text, phrase text, count real default 0, regions text, devices text, source text default 'yandex_wordstat', created_at text default current_timestamp, unique(run_date, phrase, regions, devices))''')

def get_seeds():
    seeds = set()
    with db() as c:
        try:
            rows = exec_sql(c, 'select name, category from offers where active=true order by coalesce(demand_count,0) desc, coalesce(epc,0) desc limit %s', (MAX_SEEDS * 2,)).fetchall()
        except Exception:
            rows = []
        for r in rows:
            for v in (r[0], r[1]):
                if v:
                    s = re.sub(r'[^0-9A-Za-zА-Яа-яЁё -]+', ' ', str(v))
                    s = re.sub(r'\s+', ' ', s).strip()
                    if len(s) >= 2: seeds.add(s[:200])
    for s in os.getenv('YANDEX_WORDSTAT_EXTRA_SEEDS', '').split('|'):
        s = re.sub(r'\s+', ' ', s).strip()
        if len(s) >= 2: seeds.add(s[:200])
    return list(seeds)[:MAX_SEEDS]

def request_top(phrase):
    body = {'phrase': phrase, 'regions': REGION_IDS, 'devices': DEVICES}
    req = urllib.request.Request(WORDSTAT_URL, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers={'Authorization':'Api-key '+os.environ['YANDEX_WORDSTAT_API_KEY'], 'Content-Type':'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read().decode('utf-8'))

def run():
    init_schema()
    if not os.getenv('YANDEX_WORDSTAT_API_KEY'): raise RuntimeError('YANDEX_WORDSTAT_API_KEY is not configured')
    run_date = datetime.datetime.utcnow().date().isoformat()
    seeds = get_seeds(); total = 0; errors = []
    with db() as c:
        exec_sql(c, "insert into wordstat_runs(run_date,status,seed_count,result_count) values(%s,'running',%s,0) on conflict(run_date) do update set status='running',seed_count=%s,error=null", (run_date,len(seeds),len(seeds)))
    for seed in seeds:
        try:
            data = request_top(seed)
            items = data.get('topRequests') or data.get('top_requests') or data.get('results') or []
            with db() as c:
                for item in items:
                    phrase = item.get('phrase') or item.get('query') or ''; count = item.get('count') or item.get('frequency') or 0
                    if not phrase: continue
                    exec_sql(c, "insert into wordstat_queries(run_date,seed_phrase,phrase,count,regions,devices) values(%s,%s,%s,%s,%s,%s) on conflict(run_date,phrase,regions,devices) do update set count=excluded.count", (run_date,seed,phrase,float(count or 0),','.join(REGION_IDS),','.join(DEVICES)))
                    total += 1
        except Exception as e: errors.append(f'{seed}: {type(e).__name__}: {e}')
    with db() as c: exec_sql(c, 'update wordstat_runs set status=%s,result_count=%s,error=%s where run_date=%s', ('ok' if not errors else 'partial',total,'\n'.join(errors)[:5000],run_date))
    print(json.dumps({'status':'ok' if not errors else 'partial','date':run_date,'seeds':len(seeds),'results':total,'errors':errors[:5]}, ensure_ascii=False))
    return 0 if not errors else 2

if __name__ == '__main__': raise SystemExit(run())