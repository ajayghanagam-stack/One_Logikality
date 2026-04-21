"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.routers import auth as auth_router
from app.routers import customer_admin as customer_admin_router
from app.routers import logikality as logikality_router

app = FastAPI(title="One Logikality API", version="0.1.0")

app.include_router(auth_router.router)
app.include_router(logikality_router.router)
app.include_router(customer_admin_router.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
