"""FastAPI application entrypoint."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.routers import auth as auth_router
from app.routers import compliance as compliance_router
from app.routers import customer_admin as customer_admin_router
from app.routers import debug as debug_router
from app.routers import income as income_router
from app.routers import logikality as logikality_router
from app.routers import packets as packets_router
from app.routers import title_exam as title_exam_router
from app.routers import title_search as title_search_router

log = logging.getLogger(__name__)

_gac_tmpfile: tempfile.NamedTemporaryFile | None = None  # kept open so file persists


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Write GOOGLE_APPLICATION_CREDENTIALS_JSON to a temp file so the Google
    auth libraries can find it via GOOGLE_APPLICATION_CREDENTIALS."""
    global _gac_tmpfile
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        try:
            # Validate it's real JSON before writing.
            json.loads(creds_json)
            _gac_tmpfile = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            )
            _gac_tmpfile.write(creds_json)
            _gac_tmpfile.flush()
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _gac_tmpfile.name
            log.info(
                "GOOGLE_APPLICATION_CREDENTIALS set to temp file %s",
                _gac_tmpfile.name,
            )
        except (json.JSONDecodeError, OSError):
            log.exception(
                "Failed to write GOOGLE_APPLICATION_CREDENTIALS_JSON to temp file"
            )
    yield
    if _gac_tmpfile is not None:
        try:
            os.unlink(_gac_tmpfile.name)
        except OSError:
            pass


app = FastAPI(title="One Logikality API", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router.router)
app.include_router(logikality_router.router)
app.include_router(customer_admin_router.router)
app.include_router(packets_router.router)
app.include_router(compliance_router.router)
app.include_router(income_router.router)
app.include_router(title_search_router.router)
app.include_router(title_exam_router.router)
app.include_router(debug_router.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
