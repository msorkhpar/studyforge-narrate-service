"""Split a long text into synthesis-sized pieces, on boundaries a listener hears.

⭐ **This is the property the service owes its callers**: send one text of any
length and get one artifact. No caller keeps stitching logic, and no caller has
to know the engine's input limit -- which is an engine detail that changes when
the engine does.

The split is deliberately *ours* rather than the engine's. An engine that
happens to split internally today gives the same result, but the property then
belongs to the engine rather than to the service, and it silently stops holding
when the engine is swapped.

**Where it cuts, in order of preference:** a blank line, then a sentence end,
then a space. A cut inside a word is audible; a cut at a sentence end is not.
The last resort is a hard cut at the budget, which only happens for text that
contains no whitespace at all for `budget` characters -- an input no listener is
waiting on, but one the function must still terminate for.
"""

from __future__ import annotations

import re

#: A sentence end followed by whitespace. Kept deliberately simple: this picks a
#: *cut point*, and picking a slightly early one costs nothing, while a clever
#: abbreviation-aware rule would be a second natural-language model to maintain.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s")

_PARAGRAPH_BREAK = "\n\n"


def chunk_text(text, budget):
    """Split `text` into pieces of at most `budget` characters.

    Returns a list of non-empty strings whose concatenation, ignoring the
    whitespace consumed at each cut, is the input. A text already within budget
    comes back as a single-element list, which is the common case and costs one
    comparison.

    Raises `ValueError` for a budget below 1 or for text that is empty or only
    whitespace -- synthesising silence is never what a caller meant, and a
    zero-byte artifact that looks finished is the failure this module's
    neighbours exist to prevent.
    """
    if budget < 1:
        raise ValueError("chunk budget must be at least 1 character")
    if not text or not text.strip():
        raise ValueError("refusing to chunk empty text")

    remaining = text.strip()
    chunks = []
    while len(remaining) > budget:
        cut = _cut_point(remaining, budget)
        head = remaining[:cut].strip()
        if head:
            chunks.append(head)
        remaining = remaining[cut:].strip()
        if not remaining:
            break
    if remaining:
        chunks.append(remaining)
    return chunks


def _cut_point(text, budget):
    """Index to cut `text` at, at most `budget`, preferring an audible boundary."""
    window = text[:budget]

    paragraph = window.rfind(_PARAGRAPH_BREAK)
    if paragraph > 0:
        return paragraph + len(_PARAGRAPH_BREAK)

    sentence = _last_sentence_end(window)
    if sentence is not None:
        return sentence

    space = window.rfind(" ")
    if space > 0:
        return space + 1

    # No whitespace in the whole window. Cut at the budget so the loop makes
    # progress; this is the one case where a cut lands inside a word.
    return budget


def _last_sentence_end(window):
    """End index of the last sentence-ending match in `window`, or `None`."""
    last = None
    for match in _SENTENCE_END.finditer(window):
        last = match.end()
    if last is not None and last > 0:
        return last
    return None
