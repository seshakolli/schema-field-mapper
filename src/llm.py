"""Structured-call orchestration: cache, retry, validate.

Backend-agnostic. The actual model call lives behind the `Backend` interface in
`src.backends`, so switching between Claude Code and the Anthropic API changes
the transport and nothing else -- the cache key, the retry budget, the
authorization guard and the one-sentence check are identical either way.

Backends are injected rather than constructed inline, which is what makes the
stage above testable without a subprocess or a network call. No credential is
read, stored or logged here by either backend.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Literal, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from src.backends import Backend, BackendError, build_backend
from src.backends.anthropic_api import AnthropicAPIBackend
from src.config import CACHE_DIR, MAX_ATTEMPTS, MAX_TOKENS, resolve_model

T = TypeVar("T", bound=BaseModel)


class StructuredCallError(RuntimeError):
    """Raised when every attempt at a structured call was rejected."""


class CallOutcome(BaseModel):
    """A validated response plus how it was obtained.

    `attempts` and `rejections` are kept so a run can be audited: a field that
    needed three tries is worth looking at even when the final answer is good.

    Provenance is recorded precisely. "API" would be wrong for a Claude Code
    answer, so `origin` says whether the value was replayed from cache or
    produced live, and `backend` names the runtime that produced it.
    """

    attempts: int
    origin: Literal["cache", "live"]
    backend: str
    rejections: list[str] = []

    @property
    def from_cache(self) -> bool:
        return self.origin == "cache"

    def describe(self) -> str:
        """Human-readable provenance, e.g. "live backend: claude-code"."""
        if self.origin == "cache":
            return f"cache (backend: {self.backend})"
        return f"live backend: {self.backend}"


def prompt_fingerprint(
    system: str,
    user: str,
    schema_name: str,
    model: str,
    backend: str = "",
) -> str:
    """Stable cache key over everything that can change the answer.

    The backend is part of the key: the same prompt answered through Claude Code
    and through the API are different results, and neither should be served in
    place of the other.
    """
    payload = json.dumps(
        {
            "system": system,
            "user": user,
            "schema": schema_name,
            "model": model,
            "backend": backend,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class StructuredClient:
    """Issues structured calls through a backend, with caching and retries."""

    def __init__(
        self,
        client=None,
        backend: Optional[Backend] = None,
        model: Optional[str] = None,
        max_attempts: int = MAX_ATTEMPTS,
        max_tokens: int = MAX_TOKENS,
        cache_dir: Optional[Path] = CACHE_DIR,
        use_cache: bool = True,
    ) -> None:
        # Model and backend are resolved per client, not at import, so a .env
        # loaded by a caller is still honoured.
        self.model = model or resolve_model()

        if backend is not None:
            self._backend = backend
        elif client is not None:
            # A raw SDK client is a convenience shorthand for the API backend.
            self._backend = AnthropicAPIBackend(
                model=self.model, client=client, max_tokens=max_tokens
            )
        else:
            self._backend = None  # built lazily, see `backend`

        self.max_attempts = max_attempts
        self.max_tokens = max_tokens
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.use_cache = use_cache and self.cache_dir is not None

    # -- backend ----------------------------------------------------------

    @property
    def backend(self) -> Backend:
        """The configured backend, built lazily so imports stay cheap."""
        if self._backend is None:
            self._backend = build_backend(model=self.model)
        return self._backend

    @property
    def backend_name(self) -> str:
        return self.backend.name

    # -- cache ------------------------------------------------------------

    def _cache_path(self, key: str) -> Optional[Path]:
        return self.cache_dir / f"{key}.json" if self.cache_dir else None

    def _read_cache(self, key: str, response_model: type[T]) -> Optional[T]:
        path = self._cache_path(key)
        if not (self.use_cache and path and path.exists()):
            return None
        try:
            return response_model.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError):
            # A stale or corrupt cache entry should cost a call, not a crash.
            return None

    def _write_cache(self, key: str, value: BaseModel) -> None:
        path = self._cache_path(key)
        if not (self.use_cache and path):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value.model_dump_json(indent=2), encoding="utf-8")

    # -- call -------------------------------------------------------------

    def call(
        self,
        system: str,
        user: str,
        response_model: type[T],
        validate: Optional[Callable[[T], None]] = None,
    ) -> tuple[T, CallOutcome]:
        """Issue a structured call, retrying while the answer fails validation.

        `validate` raises ValueError to reject an otherwise well-formed answer --
        that is how a hallucinated destination path is caught. The rejection text
        is fed back to the model on the next attempt, so the retry is informed
        rather than a blind re-roll.
        """
        key = prompt_fingerprint(
            system, user, response_model.__name__, self.model, self.backend_name
        )

        cached = self._read_cache(key, response_model)
        if cached is not None:
            return cached, CallOutcome(
                attempts=0, origin="cache", backend=self.backend_name
            )

        rejections: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            prompt = user if not rejections else _with_correction(user, rejections[-1])

            try:
                value = self._invoke(system, prompt, response_model)
                if validate is not None:
                    validate(value)
            except (ValidationError, ValueError) as exc:
                rejections.append(_describe(exc))
                continue

            self._write_cache(key, value)
            return value, CallOutcome(
                attempts=attempt,
                origin="live",
                backend=self.backend_name,
                rejections=rejections,
            )

        raise StructuredCallError(
            f"no valid response after {self.max_attempts} attempts; "
            f"rejections: {rejections}"
        )

    def _invoke(self, system: str, user: str, response_model: type[T]) -> T:
        return self.backend.generate(system, user, response_model)


def _with_correction(user: str, rejection: str) -> str:
    return (
        f"{user}\n\n"
        f"Your previous answer was rejected: {rejection}\n"
        f"Return a corrected answer that satisfies the rules."
    )


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
    return str(exc)
