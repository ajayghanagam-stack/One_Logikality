"""FastAPI application entrypoint.

Phase 0: health check only. Real routers land in Step 1 (auth) and later.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="One Logikality API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
