"""Anthropic concrete implementation of LLMAdapter.

Uses `anthropic.AsyncAnthropic`. When ``response_schema`` is passed, we use
forced tool-use to get structured output — Anthropic does not have a native
JSON-schema response-format flag, but tool-use with ``tool_choice`` pinned to
a specific tool is the documented path and returns a JSON object guaranteed
to match ``input_schema``.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from app.adapters.llm import LLMAdapter

# The single virtual tool we force when callers pass a response_schema.
_EMIT_TOOL_NAME = "emit_result"


class AnthropicLLMAdapter(LLMAdapter):
    """Calls Claude models via the Anthropic Messages API."""

    def __init__(self, *, api_key: str, max_tokens: int = 4096) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._max_tokens = max_tokens

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_prompt, turns = _split_system(messages)

        create_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "messages": turns,
        }
        if system_prompt:
            create_kwargs["system"] = system_prompt

        if response_schema is not None:
            create_kwargs["tools"] = [
                {
                    "name": _EMIT_TOOL_NAME,
                    "description": (
                        "Emit the structured result. Call this tool exactly once "
                        "with the JSON matching the schema."
                    ),
                    "input_schema": response_schema,
                }
            ]
            create_kwargs["tool_choice"] = {"type": "tool", "name": _EMIT_TOOL_NAME}

        response = await self._client.messages.create(**create_kwargs)

        if response_schema is not None:
            for block in response.content:
                if block.type == "tool_use" and block.name == _EMIT_TOOL_NAME:
                    # block.input is already a dict parsed from tool_use JSON.
                    return dict(block.input)
            raise RuntimeError("Anthropic response did not include the expected tool_use block")

        text_parts = [b.text for b in response.content if b.type == "text"]
        return {"text": "".join(text_parts)}


def _split_system(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, str]]]:
    """Claude takes `system` as a top-level param, not a message. Peel any
    system messages off the front and concatenate them; return the remaining
    turns unchanged (they must alternate user/assistant)."""
    system_parts: list[str] = []
    turns: list[dict[str, str]] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content", ""))
        else:
            turns.append({"role": m["role"], "content": m.get("content", "")})
    system_prompt = "\n\n".join(system_parts) if system_parts else None
    return system_prompt, turns
