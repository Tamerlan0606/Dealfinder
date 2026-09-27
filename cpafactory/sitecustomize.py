"""CPA Factory boot hooks."""
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
