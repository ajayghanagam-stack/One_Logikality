"""LLM provider abstraction per docs/TechStack.md §8, §15.

Routed via LiteLLM once implementations land. All model calls must be locked
to strict JSON schemas (Claude tool-use; Gemini response_schema) — never
free-form parsing. Every returned finding must carry
(document_id, page, MISMO_3.6_path, text_snippet) evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMAdapter(ABC):
    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the LLM and return a structured response.

        When ``response_schema`` is provided, the output is validated against
        it before being returned.
        """
