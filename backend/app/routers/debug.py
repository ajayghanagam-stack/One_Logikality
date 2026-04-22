"""Debug / smoke-test endpoints.

Gated to platform-admin only — these are operator tools, not customer-facing
APIs, and they exercise paid external providers so we don't want them open
to the tenant plane.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.adapters.llm import LLMAdapter
from app.config import settings
from app.deps import (
    get_anthropic_adapter,
    get_vertex_adapter,
    require_platform_admin,
)
from app.models import User

router = APIRouter(prefix="/api/debug", tags=["debug"])


# Matches both providers: a single-key JSON object we can eyeball in the
# response. Both Gemini (response_schema) and Claude (forced tool-use) are
# capable of satisfying this constraint.
_SMOKE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "greeting": {
            "type": "string",
            "description": "A short, friendly greeting — one sentence.",
        }
    },
    "required": ["greeting"],
}

_SMOKE_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are a smoke-test harness. Reply with a single short greeting "
            "confirming you received the prompt. Do not add extra fields."
        ),
    },
    {
        "role": "user",
        "content": "Say hello from your provider so the operator knows you are reachable.",
    },
]


class ProviderResult(BaseModel):
    ok: bool
    model: str
    latency_ms: int
    response: dict[str, Any] | None = None
    error: str | None = None


class SmokeResult(BaseModel):
    vertex: ProviderResult
    anthropic: ProviderResult


@router.get("/llm-smoke", response_model=SmokeResult)
async def llm_smoke(
    _user: Annotated[User, Depends(require_platform_admin)],
) -> SmokeResult:
    """Round-trip a trivial JSON-constrained prompt to both providers.

    Runs sequentially (not in parallel) so a failure on one provider leaves
    the other's timing uncontaminated by event-loop contention.
    """
    vertex = await _call_provider(
        get_vertex_adapter(),
        model=settings.vertex_classify_model,
    )
    anthropic = await _call_provider(
        get_anthropic_adapter(),
        model=settings.anthropic_model,
    )

    if not vertex.ok and not anthropic.ok:
        # If both failed the smoke test is useless — surface 502 so the
        # operator knows the entire AI plane is down, not a handler bug.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "vertex_error": vertex.error,
                "anthropic_error": anthropic.error,
            },
        )

    return SmokeResult(vertex=vertex, anthropic=anthropic)


async def _call_provider(adapter: LLMAdapter, *, model: str) -> ProviderResult:
    start = time.perf_counter()
    try:
        result = await adapter.complete(
            model=model,
            messages=_SMOKE_MESSAGES,
            response_schema=_SMOKE_SCHEMA,
        )
    except Exception as exc:  # noqa: BLE001 — we want the reason surfaced in the response
        elapsed = int((time.perf_counter() - start) * 1000)
        return ProviderResult(
            ok=False, model=model, latency_ms=elapsed, error=f"{type(exc).__name__}: {exc}"
        )
    elapsed = int((time.perf_counter() - start) * 1000)
    return ProviderResult(ok=True, model=model, latency_ms=elapsed, response=result)
