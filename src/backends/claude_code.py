"""Claude Code backend -- runs the `claude` CLI in non-interactive print mode.

The default backend for this project. It uses the developer's existing Claude
Code installation as the model runtime, so the pipeline runs end to end without
an ANTHROPIC_API_KEY.

One invocation per source field:

    claude -p --model <model> --output-format json
           --system-prompt <system> --allowed-tools "" --max-turns 1

The user prompt goes in on stdin rather than argv, which avoids command-line
length limits and any shell quoting question. Tools are disabled and the turn
budget is one: this is a single structured question, not an agent session.

Each invocation runs from a fresh empty temporary directory rather than the
repository. That keeps the architectural guarantee honest: the model sees the
scoped system and user prompts for one source field and its shortlist, and has
no repository files, no project settings and no schema documents within reach
even if it tried. The directory is removed when the call returns.

Authentication is entirely the CLI's business. Nothing here reads, prints or
copies a credential.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional, TypeVar

from pydantic import BaseModel

from src.backends.base import Backend, BackendError, parse_json_object, schema_instruction

T = TypeVar("T", bound=BaseModel)

DEFAULT_CLI = "claude"
DEFAULT_TIMEOUT = 180.0
CLI_ENV_VAR = "CLAUDE_CLI"


class ClaudeCodeBackend(Backend):
    """Structured calls via the Claude Code CLI."""

    name = "claude-code"

    def __init__(
        self,
        model: str,
        cli: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        runner=None,
    ) -> None:
        super().__init__(model)
        self.cli = cli or os.environ.get(CLI_ENV_VAR, "").strip() or DEFAULT_CLI
        self.timeout = timeout
        # Injected for tests; defaults to a real subprocess call.
        self._runner = runner or _run_subprocess

    # -- availability -----------------------------------------------------

    def is_available(self) -> bool:
        return shutil.which(self.cli) is not None

    def require_available(self) -> None:
        if not self.is_available():
            raise BackendError(
                f"the '{self.cli}' CLI was not found on PATH. Install Claude Code, "
                f"set {CLI_ENV_VAR} to its full path, or switch backends with "
                f"LLM_BACKEND=anthropic-api."
            )

    # -- call -------------------------------------------------------------

    def build_command(self, system: str) -> list[str]:
        return [
            self.cli,
            "-p",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--system-prompt",
            system,
            "--allowed-tools",
            "",
            "--max-turns",
            "1",
        ]

    def generate(self, system: str, user: str, response_model: type[T]) -> T:
        full_system = system + schema_instruction(response_model)
        command = self.build_command(full_system)

        # A throwaway empty directory, so the call cannot reach repository
        # context. Nothing is written into it by us; it exists to be empty.
        with tempfile.TemporaryDirectory(prefix="schema-mapper-") as workdir:
            completed = self._runner(command, user, self.timeout, workdir)

        text = self._extract_result(completed)
        return parse_json_object(text, response_model)

    # -- response envelope ------------------------------------------------

    def _extract_result(self, completed: subprocess.CompletedProcess) -> str:
        """Pull the assistant text out of the CLI's JSON envelope.

        Envelope shape:
        {"type": "result", "subtype": "success", "is_error": false,
         "result": "<assistant text>", ...}
        """
        if completed.returncode != 0:
            raise BackendError(
                f"`{self.cli} -p` exited with code {completed.returncode}: "
                f"{_tail(completed.stderr) or _tail(completed.stdout) or 'no output'}"
            )

        if not (completed.stdout or "").strip():
            raise BackendError(f"`{self.cli} -p` produced no output")

        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError(
                f"could not parse the CLI response envelope: {exc.msg}"
            ) from exc

        if not isinstance(envelope, dict):
            raise BackendError("the CLI response envelope was not a JSON object")

        if envelope.get("is_error"):
            raise BackendError(
                f"the CLI reported an error: "
                f"{envelope.get('result') or envelope.get('subtype') or 'unknown'}"
            )

        result = envelope.get("result")
        if not isinstance(result, str) or not result.strip():
            # The turn completed but said nothing usable -- retryable, unlike
            # the transport failures above.
            raise ValueError("the CLI returned an empty result; answer with the JSON object")

        return result


def _run_subprocess(command: list[str], stdin_text: str, timeout: float, cwd=None):
    try:
        return subprocess.run(
            command,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise BackendError(f"could not run '{command[0]}': {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"'{command[0]}' timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise BackendError(f"could not run '{command[0]}': {exc}") from exc


def _tail(text: Optional[str], limit: int = 300) -> str:
    stripped = (text or "").strip()
    return stripped[-limit:] if stripped else ""
