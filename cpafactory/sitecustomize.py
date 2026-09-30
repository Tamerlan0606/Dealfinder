"""CPA Factory interpreter bootstrap.

Keep this module intentionally small: app.py loads enhancements after all core
routes are declared. Wordstat scheduling lives only in enhancements.py.
"""
try:
    import app
    print("CPA_SITECUSTOMIZE_OK", flush=True)
except Exception as e:
    print("CPA_SITECUSTOMIZE_ERROR", type(e).__name__, str(e), flush=True)
