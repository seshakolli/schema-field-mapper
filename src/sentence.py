"""Deterministic check that `reasoning` is one plain-English sentence.

The assignment asks for "one plain-English sentence explaining the match", so
the pipeline enforces it rather than hoping the prompt was obeyed. A rejection
here feeds the retry loop like any other validation failure.

This is a heuristic, not a parser. It counts terminal punctuation followed by
the start of a new sentence, after masking the abbreviations that would
otherwise look like sentence ends ("e.g.", "ISO 4217, e.g. USD"). That is
enough to separate one sentence from two without pulling in an NLP dependency,
and its failure mode -- accepting an odd single sentence -- is harmless.
"""

from __future__ import annotations

import re
from typing import Optional

MIN_LENGTH = 15
MAX_LENGTH = 400

TERMINATORS = ".!?"

# Abbreviations whose trailing period is not a sentence end. Matched
# case-insensitively at a word boundary.
_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
    "cf.",
    "approx.",
    "no.",
    "inc.",
    "ltd.",
    "dr.",
    "mr.",
    "ms.",
    "st.",
)

_ABBREVIATION_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")",
    re.IGNORECASE,
)

# A terminator (plus any closing quote/bracket) followed by whitespace and the
# start of something new.
_BOUNDARY_RE = re.compile(r"[.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")


def _mask_abbreviations(text: str) -> str:
    """Replace abbreviation periods so they cannot read as sentence ends."""
    return _ABBREVIATION_RE.sub(lambda m: m.group(0).replace(".", "•"), text)


def count_sentences(text: str) -> int:
    """Number of sentences, by the heuristic above. Empty text counts as zero."""
    stripped = text.strip()
    if not stripped:
        return 0
    return len(_BOUNDARY_RE.findall(_mask_abbreviations(stripped))) + 1


def describe_problem(text: str) -> Optional[str]:
    """Return why `text` is not one plain-English sentence, or None if it is.

    The message is written to be handed straight back to the model as the
    reason its answer was rejected.
    """
    stripped = text.strip()

    if not stripped:
        return "reasoning must not be empty."

    if "\n" in stripped:
        return "reasoning must be a single line, not multiple lines."

    if len(stripped) < MIN_LENGTH:
        return (
            f"reasoning is too short to be an explanation "
            f"({len(stripped)} characters); write one full sentence."
        )

    if len(stripped) > MAX_LENGTH:
        return (
            f"reasoning is {len(stripped)} characters; keep it to one sentence "
            f"of at most {MAX_LENGTH}."
        )

    if stripped[-1] not in TERMINATORS:
        return "reasoning must end with a full stop."

    sentences = count_sentences(stripped)
    if sentences > 1:
        return (
            f"reasoning must be exactly one sentence, but it reads as "
            f"{sentences}; merge it into one."
        )

    return None


def is_one_sentence(text: str) -> bool:
    return describe_problem(text) is None
