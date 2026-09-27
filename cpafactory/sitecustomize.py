"""Render health-check compatibility and automatic MP4 self-test."""

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

# Run one real ffmpeg/Pillow render automatically after the application module is loaded.
# This verifies the production MP4 toolchain without requiring the user to click anything.
def _mp4_selftest():
    import os, shutil, threading
    try:
        import app
        row = {
            "id": 0,
            "title": "CPA Factory MP4 self-test",
            "script": "MP4 self-test",
            "platform": "rutube",
            "scenes": '[{"time":"00:00-00:02","text":"CPA Factory MP4 test"},{"time":"00:02-00:04","text":"FFmpeg OK"}]'
        }
        offer = {"id": 0, "name": "MP4 self-test", "price": 0, "cpa_rate": ""}
        path, tmp = app._make_mp4(0, row, offer)
        size = os.path.getsize(path)
        if size < 1000:
            raise RuntimeError(f"MP4 слишком маленький: {size} bytes")
        print("MP4_SELFTEST", {"status":"ok", "bytes":size, "ffmpeg":shutil.which("ffmpeg") or "imageio-ffmpeg"})
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        print("MP4_SELFTEST", {"status":"error", "error":f"{type(e).__name__}: {e}"})

try:
    threading.Timer(12, _mp4_selftest).start()
except Exception:
    pass
