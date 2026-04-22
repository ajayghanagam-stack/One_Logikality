"""Gemini Developer API (AI Studio) implementation of LLMAdapter.

Uses the same `google-genai` SDK as the Vertex adapter but authenticates with
an API key instead of Application Default Credentials. This lets the app run
on Replit (or any environment without gcloud auth) while still calling the
same Gemini models.

Obtain a key at https://aistudio.google.com → "Get API key".
"""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from app.adapters.llm import LLMAdapter


class GeminiLLMAdapter(LLMAdapter):
    """Calls Gemini models via the Gemini Developer API (AI Studio API key).

    Drop-in replacement for VertexLLMAdapter — identical `complete()` contract.
    """

    def __init__(self, *, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contents, system_instruction = _to_gemini_contents(messages)

        config_kwargs: dict[str, Any] = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        text = (response.text or "").strip()
        if response_schema is not None:
            return _parse_json(text)
        return {"text": text}


def _to_gemini_contents(
    messages: list[dict[str, str]],
) -> tuple[list[types.Content], str | None]:
    system_parts: list[str] = []
    contents: list[types.Content] = []
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        if role == "system":
            system_parts.append(text)
            continue
        gemini_role = "model" if role in ("assistant", "model") else "user"
        contents.append(types.Content(role=gemini_role, parts=[types.Part.from_text(text=text)]))
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return contents, system_instruction


def _parse_json(text: str) -> dict[str, Any]:
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
