"""`narrate.chunking` -- the property is *the caller never stitches*."""

from __future__ import annotations

import re

import pytest

from narrate.chunking import chunk_text


def test_text_within_budget_is_one_chunk():
    assert chunk_text("Nine words is fewer than the budget here.", 1800) == [
        "Nine words is fewer than the budget here."
    ]


def test_every_chunk_is_within_budget():
    text = " ".join(f"Sentence number {n} carries a little prose." for n in range(400))
    chunks = chunk_text(text, 200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_no_word_is_split_when_whitespace_exists():
    text = " ".join(f"word{n}" for n in range(500))
    chunks = chunk_text(text, 120)
    rejoined = " ".join(chunks)
    assert rejoined.split() == text.split()


def test_nothing_is_lost_or_duplicated():
    text = " ".join(f"Sentence {n} of the corpus." for n in range(300))
    chunks = chunk_text(text, 150)
    assert " ".join(chunks).split() == text.split()


def test_it_prefers_a_paragraph_break():
    first = "A" * 60
    second = "B" * 60
    chunks = chunk_text(f"{first}\n\n{second}", 100)
    assert chunks == [first, second]


def test_it_prefers_a_sentence_end_over_a_bare_space():
    text = "First sentence ends here. Then more words follow along afterwards."
    chunks = chunk_text(text, 40)
    assert chunks[0] == "First sentence ends here."


def test_a_very_long_unbroken_token_still_terminates():
    chunks = chunk_text("x" * 1000, 100)
    assert len(chunks) == 10
    assert all(len(chunk) == 100 for chunk in chunks)
    assert "".join(chunks) == "x" * 1000


def test_a_twenty_thousand_character_text_is_accepted():
    """The size the previous implementation sent to the engine in one request.

    The point of the assertion is that the *service* handles it, so that the
    property survives an engine with a smaller limit.
    """
    text = " ".join(f"Unit {n} speaks a sentence of study prose." for n in range(500))
    assert len(text) > 20_000
    chunks = chunk_text(text, 1800)
    assert len(chunks) > 10
    assert all(len(chunk) <= 1800 for chunk in chunks)


@pytest.mark.parametrize("empty", ["", "   ", "\n\n\t"])
def test_empty_text_is_refused(empty):
    with pytest.raises(ValueError, match="empty"):
        chunk_text(empty, 100)


def test_a_zero_budget_is_refused():
    with pytest.raises(ValueError, match="at least 1"):
        chunk_text("some words", 0)


def test_no_chunk_is_blank():
    text = "One.\n\n\n\nTwo.\n\n\n\nThree."
    assert all(chunk.strip() for chunk in chunk_text(text, 8))


def test_a_refusal_never_echoes_the_text():
    """A message about the input must not repeat the input.

    The gate that keeps personal data out of audio lives in the caller, but a
    refusal raised here travels into the caller's log, so the same reasoning
    applies to it: the message names what is permitted and quotes nothing.
    """
    identifier = "profile-1234567890"
    with pytest.raises(ValueError) as raised:
        chunk_text(" \t\n ", 100)
    message = str(raised.value)
    assert identifier not in message
    assert not re.search(r"\d{6,}", message)
