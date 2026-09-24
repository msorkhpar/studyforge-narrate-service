"""Which voices exist, what they are called, and how a caller picks one.

⭐ **A voice is part of a segment's content address** (`narrate.artifacts`), so
this module is not cosmetic: the value that reaches `address_for` decides which
file a corpus gets, and until this module existed that value was whatever
string a caller typed. An unknown voice reached the engine, came back as a
`502`, and through the batch route came back as one `failed` entry **per
segment** -- three thousand engine round trips to learn that a name was
misspelled.

## ⛔ The catalogue is DECLARED by the adapter, not fetched from the engine

⚠️ **This is the same distinction `engine/base.py` draws for the hardware
profile, and it is drawn the same way for the same reason.** A live fetch would
put a network call inside request validation, so an engine that is down would
turn *"this voice does not exist"* into *"try again later"* -- and a job
submitted in a misspelled voice would then be attempted rather than refused,
which is precisely the outcome this module exists to prevent.

⭐ **Three properties follow from declaring it, and all three are worth the
cost:**

* validation works with the engine down, so a bad job is refused in
  milliseconds instead of failing three thousand times;
* the catalogue can be published in `consuming.json`, which is a **file** a
  consumer reads without running anything (spec R19);
* it is a pure function, so the suite needs no engine and no GPU.

⛔ **The cost is a real one and it is not hidden: a declared catalogue can
drift from what the engine actually serves.** The reconciliation is a
measurement taken against a running engine and recorded with the image digest
it was taken on -- see `narrate/engine/kokoro.py`, which carries both the list
and the reading that produced it. ⚠️ **A voice this service declares and the
engine does not know still fails at the engine**, as a `502` for that segment;
what the catalogue removes is the far commoner case of a name nobody serves.

## ⛔ A refusal names what is permitted and never echoes what arrived

`config._one_of`'s rule, applied here for the same reason: a refusal is copied
into whatever log an operator pastes somewhere, and this service is a third
party to everything in a caller's request. ⭐ **Naming the permitted set is also
the more useful message** -- the caller already knows what it sent.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What a decoder answers for a part of an id it does not recognise. ⛔ A real
#: value rather than a `None`, so a consumer's table has no empty cells and a
#: newly added voice with an unfamiliar prefix is still selectable.
UNKNOWN = "unknown"


class UnknownVoice(ValueError):
    """A voice id this deployment does not offer. ⛔ Nothing was synthesised."""


@dataclass(frozen=True)
class Voice:
    """One selectable voice, as a consumer sees it.

    ⭐ **Four fields rather than one id**, because a consumer picking a voice
    *per corpus* is choosing a language first and a speaker second, and a bare
    list of ids makes that choice by reading a naming convention it should not
    have to know.

    ⚠️ **`language` and `gender` are DERIVED from the id by a rule the adapter
    publishes, not measured from audio.** The id is the fact; the rest is a
    decoding, and it says `unknown` where the rule does not reach.
    """

    #: What a caller sends. The only field the address is computed over.
    id: str
    #: A human name for a menu. ⚠️ Not unique and not an identifier.
    name: str
    #: A BCP-47 tag where the rule reaches one, else `unknown`.
    language: str
    #: `female`, `male`, or `unknown`.
    gender: str

    def as_dict(self):
        """The JSON shape, for the API and for `consuming.json`."""
        return {
            "id": self.id,
            "name": self.name,
            "language": self.language,
            "gender": self.gender,
        }


class VoiceCatalogue:
    """The voices one engine offers, and which of them is the default.

    ⛔ **Immutable and ordered.** Ordered because it is rendered into a menu
    and into a declaration, and an order that changes between two runs makes a
    published file's diff meaningless.
    """

    def __init__(self, voices, default):
        voices = tuple(voices)
        by_id = {}
        for voice in voices:
            if voice.id in by_id:
                # ⛔ Not a warning. A catalogue keyed by id cannot describe two
                # voices under one key without one of them being invisible --
                # the manifest's duplicate-id rule, one level down.
                raise ValueError(f"duplicate voice id: {voice.id}")
            by_id[voice.id] = voice
        if default not in by_id:
            raise UnknownVoice(
                "the default voice must be one this catalogue offers: "
                + ", ".join(by_id)
            )
        self._voices = voices
        self._by_id = by_id
        self._default = default

    @property
    def default(self):
        """The id used when a caller names no voice.

        ⛔ **Published**, because it is part of the content address of every
        segment submitted without a `voice`, and a caller that recomputes an
        address for itself cannot get it from a constant. Same argument as
        `chunk_chars`; see `narrate.artifacts`.
        """
        return self._default

    def ids(self):
        """Every voice id, in catalogue order."""
        return tuple(voice.id for voice in self._voices)

    def __contains__(self, voice_id):
        return voice_id in self._by_id

    def __iter__(self):
        return iter(self._voices)

    def __len__(self):
        return len(self._voices)

    def get(self, voice_id):
        """The `Voice`, or `None`. ⭐ The question, without the refusal."""
        return self._by_id.get(voice_id)

    def require(self, voice_id):
        """The `Voice`, or raise `UnknownVoice` naming what is permitted.

        ⛔ **The message does not echo `voice_id`**; see the module docstring.
        """
        voice = self._by_id.get(voice_id)
        if voice is None:
            raise UnknownVoice(
                "voice must be one of: " + ", ".join(self.ids())
            )
        return voice

    def listing(self):
        """Every voice as JSON, in catalogue order. ⛔ Without a default.

        ⭐ **The default is kept out of this deliberately.** A catalogue is an
        engine-family fact; which of its voices a deployment falls back to is
        a deployment fact, and `build_server` is the one place that resolves
        it. Returning both here would give the route two sources for one
        answer, which is how they come to disagree.
        """
        return [voice.as_dict() for voice in self._voices]

    def as_dict(self):
        """The catalogue with the default it was constructed against."""
        return {"default": self._default, "voices": self.listing()}


def catalogue_from_ids(ids, default, decode):
    """A `VoiceCatalogue` built from measured ids and a published decoding.

    ⭐ **The two halves are kept apart on purpose.** `ids` is a *measurement*
    -- what an engine answered when it was asked -- and `decode` is a *rule*
    an adapter publishes for turning one of those ids into a language, a
    gender and a name. Mixing them would make a hand-written table that is
    partly measured and partly asserted, with no way for a reader to tell
    which half is which.
    """
    return VoiceCatalogue([decode(voice_id) for voice_id in ids], default)
