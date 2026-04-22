"""Vertex AI concrete implementation of LLMAdapter.

Uses Google's `google-genai` SDK with the ``vertexai=True`` code path so all
Google model calls route through Vertex (not the Gemini Developer API). Auth
is Application Default Credentials — run ``gcloud auth application-default
login`` locally or set ``GOOGLE_APPLICATION_CREDENTIALS`` in CI/staging.

Structured output uses Gemini's ``response_schema`` (JSON schema), matching
the LLMAdapter contract: if ``response_schema`` is passed, the return value
is the parsed JSON object.
"""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from app.adapters.llm import LLMAdapter


class VertexLLMAdapter(LLMAdapter):
    """Calls Gemini models via Vertex AI.

    One client per process; the SDK itself is thread-safe and supports async
    via the ``client.aio`` namespace.
    """

    def __init__(self, *, project: str, location: str) -> None:
        self._client = genai.Client(vertexai=True, project=project, location=location)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contents, system_instruction = _to_vertex_contents(messages)

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


def _to_vertex_contents(
    messages: list[dict[str, str]],
) -> tuple[list[types.Content], str | None]:
    """Translate OpenAI-style `[{role, content}, ...]` into Vertex Content list.

    Vertex treats ``system`` separately (``system_instruction``), and uses
    ``user`` / ``model`` for the turn roles. Assistant-role messages map to
    ``model``.
    """
    system_parts: list[str] = []
    contents: list[types.Content] = []
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        if role == "system":
            system_parts.append(text)
            continue
        vertex_role = "model" if role in ("assistant", "model") else "user"
        contents.append(types.Content(role=vertex_role, parts=[types.Part.from_text(text=text)]))
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return contents, system_instruction


def _parse_json(text: str) -> dict[str, Any]:
    """Parse Gemini's JSON response. Strips common ```json fences if the model
    emits them despite response_mime_type=application/json (rare, but happens)."""
    if text.startswith("```"):
        # ```json\n...\n```  or  ```\n...\n```
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
