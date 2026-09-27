"""Render health-check compatibility: FastAPI GET / should also answer HEAD /."""
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
