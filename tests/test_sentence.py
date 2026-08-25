"""Tests for the one-plain-English-sentence check on `reasoning`."""

from __future__ import annotations

import pytest

from src.sentence import (
    MAX_LENGTH,
    count_sentences,
    describe_problem,
    is_one_sentence,
)

ONE_SENTENCE = [
    "The legacy hire date is the start of the employment period.",
    "Primary key maps to the MongoDB _id, so an ID generation strategy is required.",
    "Flat field promoted into the fullName sub-document.",
    "Job level codes such as e.g. L1 or IC3 carry across unchanged.",
    "The currency column holds an ISO 4217 code, i.e. a three-letter string.",
    "Is this really the same field?",
]

NOT_ONE_SENTENCE = [
    ("", "must not be empty"),
    ("   ", "must not be empty"),
    ("Too short.", "too short"),
    ("The hire date maps to the employment start date", "must end with a full stop"),
    (
        "The hire date is the employment start. It also needs a timezone.",
        "exactly one sentence",
    ),
    (
        "First line of the reasoning.\nSecond line of the reasoning.",
        "single line",
    ),
]


@pytest.mark.parametrize("text", ONE_SENTENCE)
def test_accepts_a_single_sentence(text):
    assert is_one_sentence(text), describe_problem(text)


@pytest.mark.parametrize("text, expected", NOT_ONE_SENTENCE)
def test_rejects_everything_else(text, expected):
    problem = describe_problem(text)
    assert problem is not None
    assert expected in problem


def test_abbreviations_do_not_read_as_sentence_ends():
    """"e.g. USD" would otherwise look like two sentences."""
    assert count_sentences("The column holds a currency code, e.g. USD.") == 1
    assert count_sentences("Levels are graded, e.g. L1, and stored as strings.") == 1


def test_counts_genuine_sentence_boundaries():
    assert count_sentences("One sentence here.") == 1
    assert count_sentences("One here. Two here.") == 2
    assert count_sentences("One here. Two here. Three here.") == 3
    assert count_sentences("") == 0


def test_rejects_a_paragraph_length_answer():
    long_text = "The legacy column maps across " + ("and again " * 60) + "cleanly."
    assert len(long_text) > MAX_LENGTH
    assert "keep it to one sentence" in describe_problem(long_text)


def test_the_rejection_message_is_usable_as_model_feedback():
    """Every message should read as an instruction, not a code."""
    for text, _ in NOT_ONE_SENTENCE:
        problem = describe_problem(text)
        assert problem.startswith("reasoning")
        assert problem.endswith(".")
