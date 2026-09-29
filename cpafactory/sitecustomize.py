"""CPA Factory boot hooks."""
import threading
try:
    from fastapi import FastAPI
    _original_api_route = FastAPI.api_route
    def _api_route_with_head(self, path, *args, **kwargs):
        methods = kwargs.get("methods")
        if path == "/" and methods and "GET" in methods and "HEAD" not in methods:
            kwargs["methods"] = list(methods) + ["HEAD"]
        return _original_api_route(self, path, *args, **kwargs)
    FastAPI.api_route = _api_route_with_head
except Exception:
    pass

try:
    import app
    import enhancements
    print("CPA_ENHANCEMENTS_BOOT_OK", flush=True)
except Exception as e:
    print("CPA_ENHANCEMENTS_BOOT_ERROR", type(e).__name__, str(e), flush=True)

def _wordstat_once_daily():
    try:
        import wordstat_monitor
        wordstat_monitor.run()
    except Exception as e:
        print("CPA_WORDSTAT_ERROR", type(e).__name__, str(e), flush=True)

try:
    if hasattr(app, "app"):
        @app.app.get("/api/wordstat/status")
        def wordstat_status():
            import wordstat_monitor
            wordstat_monitor.init_schema()
            with wordstat_monitor.db() as c:
                run = wordstat_monitor.exec_sql(c, "select * from wordstat_runs order by id desc limit 1").fetchone()
                top = wordstat_monitor.exec_sql(c, "select phrase,count,seed_phrase from wordstat_queries order by run_date desc,count desc limit 20").fetchall()
            return {"configured": bool(__import__("os").getenv("YANDEX_WORDSTAT_API_KEY")), "last_run": dict(run) if run else None, "top": [dict(x) for x in top]}
except Exception as e:
    print("CPA_WORDSTAT_ROUTE_ERROR", type(e).__name__, str(e), flush=True)

_original_cycle = getattr(app, "_autopilot_cycle", None)
if _original_cycle:
    _wordstat_lock = threading.Lock()
    _wordstat_last_date = {"value": None}
    def _autopilot_with_wordstat():
        result = _original_cycle()
        try:
            import datetime, os
            if os.getenv("YANDEX_WORDSTAT_API_KEY") and _wordstat_lock.acquire(blocking=False):
                today = datetime.datetime.utcnow().date().isoformat()
                if _wordstat_last_date["value"] != today:
                    _wordstat_last_date["value"] = today
                    threading.Thread(target=_wordstat_once_daily, daemon=True, name="cpa-wordstat-daily").start()
                _wordstat_lock.release()
        except Exception as e:
            print("CPA_WORDSTAT_SCHEDULE_ERROR", type(e).__name__, str(e), flush=True)
        return result
    app._autopilot_cycle = _autopilot_with_wordstat
    print("CPA_WORDSTAT_DAILY_HOOK_READY", flush=True)
