"""Tests for backend selection and the Claude Code transport.

No subprocess is ever spawned: a fake runner stands in for `subprocess.run` and
returns scripted CompletedProcess objects, so the CLI's failure modes can be
exercised directly.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

from src.backends import BACKENDS, build_backend
from src.backends.anthropic_api import AnthropicAPIBackend
from src.backends.base import (
    BackendError,
    parse_json_object,
    schema_instruction,
    strip_code_fence,
)
from src.backends.claude_code import ClaudeCodeBackend
from src.config import DEFAULT_BACKEND
from src.llm import StructuredCallError, StructuredClient, prompt_fingerprint
from src.loader import load_destination_schema, load_source_schema
from src.models import FieldMappingProposal
from src.stages.map_fields import map_field

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PROPOSAL = {
    "destination_field": "employment.startDate",
    "type_transform": "DATETIME -> ISODate",
    "confidence": 0.93,
    "reasoning": "The legacy hire date is the start of the employment period.",
    "notes": None,
}


@pytest.fixture(scope="module")
def source():
    return load_source_schema()


@pytest.fixture(scope="module")
def destination():
    return load_destination_schema()


def field(source, table: str, name: str):
    return next(f for f in source.tables[table].fields if f.name == name)


# --------------------------------------------------------------------------
# Fake CLI runner
# --------------------------------------------------------------------------


def envelope(result_text: str, **overrides) -> str:
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result_text,
        "session_id": "test-session",
    }
    payload.update(overrides)
    return json.dumps(payload)


class FakeRunner:
    """Replays scripted CompletedProcess results and records invocations."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    def __call__(self, command, stdin_text, timeout, cwd=None):
        self.calls.append(
            {
                "command": command,
                "stdin": stdin_text,
                "timeout": timeout,
                "cwd": cwd,
                "cwd_entries": sorted(os.listdir(cwd)) if cwd else None,
            }
        )
        if not self._script:
            raise AssertionError("the fake runner ran out of scripted results")

        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, subprocess.CompletedProcess):
            return item
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout=item, stderr=""
        )


def make_backend(script, **kwargs) -> tuple[ClaudeCodeBackend, FakeRunner]:
    runner = FakeRunner(script)
    kwargs.setdefault("model", "claude-sonnet-5")
    return ClaudeCodeBackend(runner=runner, **kwargs), runner


# --------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------


def test_claude_code_is_the_default_backend(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert DEFAULT_BACKEND == "claude-code"
    assert build_backend().name == "claude-code"


def test_the_backend_is_selectable_by_environment_variable(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "anthropic-api")
    assert isinstance(build_backend(), AnthropicAPIBackend)


def test_an_empty_backend_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "  ")
    assert build_backend().name == DEFAULT_BACKEND


def test_an_unknown_backend_is_rejected_with_the_valid_choices(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gpt-whatever")
    with pytest.raises(BackendError, match="unknown LLM_BACKEND"):
        build_backend()


def test_the_backend_registry_covers_both_runtimes():
    assert set(BACKENDS) == {"claude-code", "anthropic-api"}


def test_the_backend_uses_the_resolved_model(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    assert build_backend().model == "claude-opus-5"


def test_the_claude_code_backend_needs_no_api_key(monkeypatch):
    """Constructing it must not touch ANTHROPIC_API_KEY at all."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    backend = build_backend()
    assert backend.name == "claude-code"
    assert backend.generate is not None


# --------------------------------------------------------------------------
# Command construction
# --------------------------------------------------------------------------


def test_the_command_runs_print_mode_with_json_output():
    backend, _ = make_backend([])
    command = backend.build_command("SYSTEM")

    assert command[0] == "claude"
    assert "-p" in command
    assert command[command.index("--output-format") + 1] == "json"
    assert command[command.index("--model") + 1] == "claude-sonnet-5"
    assert command[command.index("--system-prompt") + 1] == "SYSTEM"


def test_the_command_disables_tools_and_extra_turns():
    backend, _ = make_backend([])
    command = backend.build_command("SYSTEM")

    assert command[command.index("--allowed-tools") + 1] == ""
    assert command[command.index("--max-turns") + 1] == "1"


def test_the_user_prompt_goes_in_on_stdin_not_argv(source, destination):
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    backend.generate("SYSTEM", "USER PROMPT", FieldMappingProposal)

    call = runner.calls[0]
    assert call["stdin"] == "USER PROMPT"
    assert "USER PROMPT" not in call["command"]


def test_the_schema_is_appended_to_the_system_prompt():
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    backend.generate("SYSTEM", "USER", FieldMappingProposal)

    system = runner.calls[0]["command"][
        runner.calls[0]["command"].index("--system-prompt") + 1
    ]
    assert system.startswith("SYSTEM")
    assert "destination_field" in system
    assert "single JSON object" in system


def test_the_cli_path_is_overridable(monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI", "/opt/bin/claude")
    assert ClaudeCodeBackend(model="m").cli == "/opt/bin/claude"


def test_a_missing_cli_reports_how_to_fix_it():
    backend = ClaudeCodeBackend(model="m", cli="definitely-not-a-real-binary")
    assert backend.is_available() is False
    with pytest.raises(BackendError, match="LLM_BACKEND=anthropic-api"):
        backend.require_available()


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def test_a_well_formed_response_parses_into_the_proposal_model():
    backend, _ = make_backend([envelope(json.dumps(PROPOSAL))])
    proposal = backend.generate("SYSTEM", "USER", FieldMappingProposal)

    assert isinstance(proposal, FieldMappingProposal)
    assert proposal.destination_field == "employment.startDate"
    assert proposal.confidence == 0.93


def test_a_markdown_fenced_response_still_parses():
    fenced = "```json\n" + json.dumps(PROPOSAL) + "\n```"
    backend, _ = make_backend([envelope(fenced)])
    assert backend.generate("SYSTEM", "USER", FieldMappingProposal).is_match


def test_json_surrounded_by_prose_still_parses():
    chatty = "Here is the mapping:\n" + json.dumps(PROPOSAL) + "\nHope that helps!"
    backend, _ = make_backend([envelope(chatty)])
    assert backend.generate("SYSTEM", "USER", FieldMappingProposal).is_match


def test_a_null_destination_parses_as_no_match():
    no_match = dict(
        PROPOSAL,
        destination_field=None,
        type_transform=None,
        reasoning="The destination employee document carries no date of birth.",
    )
    backend, _ = make_backend([envelope(json.dumps(no_match))])
    assert backend.generate("SYSTEM", "USER", FieldMappingProposal).is_match is False


def test_strip_code_fence_handles_both_fence_styles():
    assert strip_code_fence("```json\n{}\n```") == "{}"
    assert strip_code_fence("```\n{}\n```") == "{}"
    assert strip_code_fence("  {}  ") == "{}"


def test_non_json_output_is_retryable_not_fatal():
    with pytest.raises(ValueError, match="not JSON"):
        parse_json_object("I am afraid I cannot do that", FieldMappingProposal)


def test_a_json_array_is_rejected():
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object("[1, 2, 3]", FieldMappingProposal)


def test_the_schema_instruction_forbids_prose_and_fences():
    instruction = schema_instruction(FieldMappingProposal)
    assert "no markdown code fence" in instruction
    assert "confidence" in instruction


# --------------------------------------------------------------------------
# CLI failure modes
# --------------------------------------------------------------------------


def test_a_non_zero_exit_is_a_transport_error():
    failed = subprocess.CompletedProcess(
        args=["claude"], returncode=1, stdout="", stderr="Invalid API key"
    )
    backend, _ = make_backend([failed])
    with pytest.raises(BackendError, match="exited with code 1"):
        backend.generate("SYSTEM", "USER", FieldMappingProposal)


def test_empty_stdout_is_a_transport_error():
    backend, _ = make_backend([""])
    with pytest.raises(BackendError, match="produced no output"):
        backend.generate("SYSTEM", "USER", FieldMappingProposal)


def test_an_unparseable_envelope_is_a_transport_error():
    backend, _ = make_backend(["not json at all"])
    with pytest.raises(BackendError, match="response envelope"):
        backend.generate("SYSTEM", "USER", FieldMappingProposal)


def test_an_error_envelope_is_a_transport_error():
    backend, _ = make_backend(
        [envelope("rate limited", is_error=True, subtype="error_during_execution")]
    )
    with pytest.raises(BackendError, match="reported an error"):
        backend.generate("SYSTEM", "USER", FieldMappingProposal)


def test_an_empty_result_is_retryable_rather_than_fatal():
    backend, _ = make_backend([envelope("   ")])
    with pytest.raises(ValueError, match="empty result"):
        backend.generate("SYSTEM", "USER", FieldMappingProposal)


# The two process-level failures below are wrapped inside `_run_subprocess`,
# so they are exercised against the real runner rather than the fake one.


def test_the_real_runner_wraps_process_failures(monkeypatch):
    from src.backends import claude_code

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(claude_code.subprocess, "run", boom)
    with pytest.raises(BackendError, match="timed out"):
        claude_code._run_subprocess(["claude"], "prompt", 1.0)


def test_the_real_runner_wraps_a_missing_binary(monkeypatch):
    from src.backends import claude_code

    def boom(*args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(claude_code.subprocess, "run", boom)
    with pytest.raises(BackendError, match="could not run"):
        claude_code._run_subprocess(["claude"], "prompt", 1.0)


# --------------------------------------------------------------------------
# Integration with the existing pipeline guarantees
# --------------------------------------------------------------------------


def test_the_pipeline_runs_end_to_end_over_the_claude_code_backend(source, destination):
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    client = StructuredClient(backend=backend, use_cache=False, cache_dir=None)

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.proposal.destination_field == "employment.startDate"
    assert result.outcome.attempts == 1
    assert len(runner.calls) == 1


def test_hallucination_is_still_rejected_and_retried(source, destination):
    invented = json.dumps(dict(PROPOSAL, destination_field="employment.hireDate"))
    backend, runner = make_backend(
        [envelope(invented), envelope(json.dumps(PROPOSAL))]
    )
    client = StructuredClient(backend=backend, use_cache=False, cache_dir=None)

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.proposal.destination_field == "employment.startDate"
    assert result.outcome.attempts == 2
    assert "employment.hireDate" in result.outcome.rejections[0]
    # The rejection reason reached the retry, on stdin as before.
    assert "was rejected" in runner.calls[1]["stdin"]


def test_multi_sentence_reasoning_is_still_rejected(source, destination):
    wordy = json.dumps(
        dict(PROPOSAL, reasoning="The hire date starts employment. It needs a timezone.")
    )
    backend, _ = make_backend([envelope(wordy), envelope(json.dumps(PROPOSAL))])
    client = StructuredClient(backend=backend, use_cache=False, cache_dir=None)

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert "exactly one sentence" in result.outcome.rejections[0]


def test_unparseable_output_is_retried_within_the_budget(source, destination):
    backend, runner = make_backend(
        [envelope("sorry, no"), envelope("still no"), envelope("nope")]
    )
    client = StructuredClient(
        backend=backend, use_cache=False, cache_dir=None, max_attempts=3
    )

    with pytest.raises(StructuredCallError, match="after 3 attempts"):
        map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert len(runner.calls) == 3


def test_a_transport_failure_is_not_retried(source, destination):
    """A missing binary will not fix itself; fail fast instead of burning turns."""
    failed = subprocess.CompletedProcess(
        args=["claude"], returncode=127, stdout="", stderr="command not found"
    )
    backend, runner = make_backend([failed])
    client = StructuredClient(backend=backend, use_cache=False, cache_dir=None)

    with pytest.raises(BackendError):
        map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert len(runner.calls) == 1


def test_the_prompt_still_carries_one_field_and_its_shortlist(source, destination):
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    client = StructuredClient(backend=backend, use_cache=False, cache_dir=None)
    map_field(field(source, "emp_master", "hire_dt"), destination, client)

    stdin = runner.calls[0]["stdin"]
    assert "hire_dt" in stdin
    for other in source.all_fields:
        if other.name in {"hire_dt", "city"}:
            continue
        assert other.name not in stdin


def test_caching_works_over_the_claude_code_backend(tmp_path, source, destination):
    src = field(source, "emp_master", "hire_dt")

    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    cold = StructuredClient(backend=backend, cache_dir=tmp_path, use_cache=True)
    assert map_field(src, destination, cold).outcome.from_cache is False

    warm_backend, warm_runner = make_backend([])
    warm = StructuredClient(backend=warm_backend, cache_dir=tmp_path, use_cache=True)
    assert map_field(src, destination, warm).outcome.from_cache is True
    assert warm_runner.calls == []


def test_the_backend_is_part_of_the_cache_key():
    base = prompt_fingerprint("sys", "user", "Model", "claude-sonnet-5", "claude-code")
    other = prompt_fingerprint("sys", "user", "Model", "claude-sonnet-5", "anthropic-api")
    assert base != other


def test_switching_backend_does_not_reuse_the_other_cache(tmp_path, source, destination):
    src = field(source, "emp_master", "hire_dt")

    backend, _ = make_backend([envelope(json.dumps(PROPOSAL))])
    first = StructuredClient(backend=backend, cache_dir=tmp_path, use_cache=True)
    map_field(src, destination, first)

    api_backend = AnthropicAPIBackend(model="claude-sonnet-5", client=object())
    second = StructuredClient(backend=api_backend, cache_dir=tmp_path, use_cache=True)
    assert second._read_cache(
        prompt_fingerprint("x", "y", "FieldMappingProposal", "m", "anthropic-api"),
        FieldMappingProposal,
    ) is None


# --------------------------------------------------------------------------
# Working-directory isolation
# --------------------------------------------------------------------------


def test_the_subprocess_runs_from_an_isolated_working_directory():
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    backend.generate("SYSTEM", "USER", FieldMappingProposal)

    cwd = runner.calls[0]["cwd"]
    assert cwd is not None, "the call must not inherit the caller's directory"
    assert pathlib.Path(cwd).resolve() != REPO_ROOT


def test_the_isolated_working_directory_is_empty():
    """No repository file, no project settings, nothing to read."""
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    backend.generate("SYSTEM", "USER", FieldMappingProposal)

    assert runner.calls[0]["cwd_entries"] == []


def test_the_isolated_directory_is_not_inside_the_repository():
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    backend.generate("SYSTEM", "USER", FieldMappingProposal)

    cwd = pathlib.Path(runner.calls[0]["cwd"]).resolve()
    assert REPO_ROOT not in cwd.parents


def test_the_isolated_directory_is_removed_afterwards():
    backend, runner = make_backend([envelope(json.dumps(PROPOSAL))])
    backend.generate("SYSTEM", "USER", FieldMappingProposal)

    assert not pathlib.Path(runner.calls[0]["cwd"]).exists()


def test_each_call_gets_a_fresh_directory():
    backend, runner = make_backend(
        [envelope(json.dumps(PROPOSAL)), envelope(json.dumps(PROPOSAL))]
    )
    backend.generate("SYSTEM", "USER", FieldMappingProposal)
    backend.generate("SYSTEM", "USER", FieldMappingProposal)

    assert runner.calls[0]["cwd"] != runner.calls[1]["cwd"]


def test_the_real_runner_passes_the_working_directory_through(monkeypatch, tmp_path):
    from src.backends import claude_code

    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=["claude"], returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(claude_code.subprocess, "run", capture)
    claude_code._run_subprocess(["claude"], "prompt", 1.0, str(tmp_path))
    assert seen["cwd"] == str(tmp_path)


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_a_live_claude_code_result_is_labelled_by_backend(source, destination):
    backend, _ = make_backend([envelope(json.dumps(PROPOSAL))])
    client = StructuredClient(backend=backend, use_cache=False, cache_dir=None)

    outcome = map_field(field(source, "emp_master", "hire_dt"), destination, client).outcome
    assert outcome.origin == "live"
    assert outcome.backend == "claude-code"
    assert outcome.describe() == "live backend: claude-code"
    assert "API" not in outcome.describe()


def test_a_cached_result_is_labelled_as_cache(tmp_path, source, destination):
    src = field(source, "emp_master", "hire_dt")

    backend, _ = make_backend([envelope(json.dumps(PROPOSAL))])
    cold = StructuredClient(backend=backend, cache_dir=tmp_path, use_cache=True)
    map_field(src, destination, cold)

    warm_backend, _ = make_backend([])
    warm = StructuredClient(backend=warm_backend, cache_dir=tmp_path, use_cache=True)
    outcome = map_field(src, destination, warm).outcome

    assert outcome.origin == "cache"
    assert outcome.describe().startswith("cache")
    assert outcome.from_cache is True
