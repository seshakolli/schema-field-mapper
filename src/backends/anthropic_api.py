"""Anthropic API backend -- the Messages API with native structured output.

Kept as an alternative to the default Claude Code backend. It needs an
ANTHROPIC_API_KEY in the environment; the SDK reads it directly and no key is
handled here. The SDK client is constructed lazily so that importing this module,
or running the test suite, never requires a key.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from src.backends.base import Backend, BackendError
from src.config import MAX_TOKENS

T = TypeVar("T", bound=BaseModel)


class AnthropicAPIBackend(Backend):
    """Structured calls via `client.messages.parse`."""

    name = "anthropic-api"

    def __init__(self, model: str, client=None, max_tokens: int = MAX_TOKENS) -> None:
        super().__init__(model)
        self._client = client
        self.max_tokens = max_tokens

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise BackendError(
                    "the anthropic SDK is not installed; "
                    "pip install -r requirements.txt"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def generate(self, system: str, user: str, response_model: type[T]) -> T:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=response_model,
        )
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ValueError("the response contained no structured output")
        return parsed
