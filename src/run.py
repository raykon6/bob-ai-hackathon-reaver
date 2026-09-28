"""Dev entrypoint:  python run.py   (or:  uvicorn app.main:app --reload)"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("TRIAGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRIAGE_PORT", "8000")),
        reload=True,
    )
