"""Backend selection.

`LLM_BACKEND` picks the runtime; the default is `claude-code`, which uses the
developer's Claude Code installation and needs no API key. `anthropic-api` is
available for anyone who has one.
"""

from __future__ import annotations

from typing import Optional

from src.backends.anthropic_api import AnthropicAPIBackend
from src.backends.base import Backend, BackendError
from src.backends.claude_code import ClaudeCodeBackend
from src.config import resolve_backend_name, resolve_model

BACKENDS = {
    ClaudeCodeBackend.name: ClaudeCodeBackend,
    AnthropicAPIBackend.name: AnthropicAPIBackend,
}


def build_backend(name: Optional[str] = None, model: Optional[str] = None) -> Backend:
    """Construct the configured backend.

    Resolution happens here, not at import, so a .env loaded by a caller is
    still honoured.
    """
    name = (name or resolve_backend_name()).strip()
    model = model or resolve_model()

    try:
        backend_class = BACKENDS[name]
    except KeyError:
        raise BackendError(
            f"unknown LLM_BACKEND {name!r}; choose one of {sorted(BACKENDS)}"
        ) from None

    return backend_class(model=model)


__all__ = [
    "AnthropicAPIBackend",
    "Backend",
    "BackendError",
    "BACKENDS",
    "ClaudeCodeBackend",
    "build_backend",
]
