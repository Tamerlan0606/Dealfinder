from app.main import app

# Render starts the app with uvicorn directly.
# This module intentionally does not call uvicorn.run(), so it is safe to use
# as the import target: uvicorn run:app
