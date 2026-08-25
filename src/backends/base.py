"""Backend contract for structured LLM calls.

A backend turns (system prompt, user prompt, response model) into a validated
Pydantic instance. It owns nothing else -- caching, retries, authorization and
the one-sentence check all live above it in `StructuredClient`, so swapping
backends cannot change the pipeline's guarantees.

Two failure modes, deliberately distinguished:

* `BackendError` -- the transport itself failed (binary missing, non-zero exit,
  timeout). Retrying the same prompt will not help, so it propagates.
* `ValueError` / `ValidationError` -- the model answered, but the answer was
  unusable. These are retried with the reason fed back.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class BackendError(RuntimeError):
    """The backend could not be reached or failed at the transport level."""


class Backend(ABC):
    """Produces one validated structured response per call."""

    name: str = "backend"

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def generate(self, system: str, user: str, response_model: type[T]) -> T:
        """Return a validated instance, or raise.

        Raise `BackendError` for transport failures, `ValueError` or
        `pydantic.ValidationError` for an unusable answer.
        """


def strip_code_fence(text: str) -> str:
    """Remove a surrounding markdown fence, if the model added one."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


def parse_json_object(text: str, response_model: type[T]) -> T:
    """Parse model text into `response_model`.

    Tolerates a markdown fence and leading/trailing prose, because a text-mode
    backend cannot guarantee their absence. Anything else is a ValueError and
    therefore retryable.
    """
    payload = strip_code_fence(text)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span before giving up.
        start, end = payload.find("{"), payload.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(
                "the response was not JSON; return a single JSON object and nothing else"
            )
        try:
            data = json.loads(payload[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"the response was not valid JSON: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError("the response must be a JSON object, not a bare value or list")

    return response_model.model_validate(data)


def schema_instruction(response_model: type[BaseModel]) -> str:
    """The output contract, appended to the system prompt for text backends."""
    schema = json.dumps(response_model.model_json_schema(), indent=2, sort_keys=True)
    return (
        "\n\nOUTPUT FORMAT\n"
        "Respond with a single JSON object and nothing else. No preamble, no "
        "explanation outside the JSON, no markdown code fence. The object must "
        "validate against this JSON Schema:\n"
        f"{schema}"
    )
