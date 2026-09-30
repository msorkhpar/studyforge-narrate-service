"""⛔ Does the address cover EVERY input that changes the audio?

⭐ **This module exists because a drift test could not answer that question.**
`test_profiles.py` asserts that `consuming.json`'s `api.cache.over` equals
`narrate.artifacts.ADDRESS_FIELDS`, and the negative control that drifts one
from the other fires correctly. ⛔ **But that pins a DECLARATION to the CODE,
and both are artefacts this repository controls.** It fires on a declaration
that disagrees with the address and stays silent on an address that disagrees
with **the audio** -- which is the failure that actually mis-serves a caller.

⚠️ **It stayed silent exactly once and that is why this file is here.** The
first version of the address covered `format`, `voice` and `text`, and
`chunk_chars` -- an operator-settable input that decides where the text is cut,
and therefore how many separate engine requests are concatenated -- was not in
it. Two deployments sharing a store served audio that did not match the
request, under an address asserting that it did, and every declaration test
passed.

⭐ **So the assertions below are driven from the SYNTHESIS PATH, not from a
declaration.** Each varies one input, synthesises twice, and asserts the audio
really did change **and** the address changed with it. A control that compares
two things the author controls is worth having; it is not evidence about the
world.

## ⛔ WHAT THIS MODULE DOES NOT PROVE, named because its class was once named as though it did

⚠️ **The list below is HAND-ENUMERATED and derives nothing from the code**, so a
newly added audio-changing input is invisible to it — which is the failure it
was written to prevent, one level up. ⛔ **It is a checklist of
the inputs NAMED IN IT, not a universal**, and the class is named
accordingly. ⚠️ **It was a checklist of four and the voice catalogue made it six** by closing
the gap the next paragraph used to describe -- the list growing by hand, which
is exactly the weakness it declares.

⭐ **THE GAP THIS MODULE NAMED IS CLOSED, AND ITS CASE IS NOW ONE OF THE
ENUMERATED FOUR.** The previous version read: *"the ENGINE MODEL is an
audio-changing input and it is NOT in the address ... routed to the voice
catalogue work, which will touch this seam"*. ⛔ **That work took the first of the two
remedies it offered: the model is hashed in** (`narrate.artifacts`,
`ADDRESS_SCHEME` `narrate-address-3`), and `test_the_ENGINE_MODEL` below is
driven from the synthesis path like every other case here.

⚠️ **The ENGINE FAMILY and the hardware PROFILE remain outside the address and
that is still correct** -- a move between the CPU and GPU builds of one model
must not re-synthesise a corpus. ⛔ **Neither of them is an
audio-changing input in the sense this module tests**, and
`TestTheProducedBytesAreNotInTheAddress` is the assertion that says so.
"""

from __future__ import annotations

import pytest

from narrate.artifacts import ADDRESS_FIELDS, ArtifactStore, address_for
from narrate.config import FORMAT_MEDIA_TYPES
from narrate.synthesis import synthesise
from tests.support import FakeEngine, mpeg_bytes

#: Long enough to be cut by a small budget and not by a large one.
LONG = " ".join(f"Sentence number {n} of the corpus." for n in range(18))

#: Short enough that no budget here cuts it.
SHORT = "One short unit."


def text_sensitive(chunk):
    """Frames proportional to the chunk's length.

    ⛔ **A fake that returned the same bytes for every chunk would make every
    *audio differs* precondition in this module vacuously false**, and the
    module would pass by proving nothing -- which is the defect it exists to
    catch, one level up. Length is used rather than a digest so the counts
    cannot collide by luck for the inputs chosen here.
    """
    return mpeg_bytes(1 + len(chunk) // 4)


def run(text, tmp_path, voice="am_liam", chunk_chars=1800, engine=None):
    """One synthesis into its own store, returning the result."""
    return synthesise(
        text, voice, "mp3",
        engine=engine if engine is not None else FakeEngine(per_chunk=text_sensitive),
        store=ArtifactStore(tmp_path),
        chunk_chars=chunk_chars,
        media_types=FORMAT_MEDIA_TYPES,
    )


class TestEachEnumeratedInputChangesTheAddress:
    """⛔ One case per input NAMED HERE — not a universal. See the module head.

    ⚠️ **Two cases below assert an input is NOT in the address**, and they are
    in this class deliberately: *which inputs move the address* is not
    answered by the positives alone.

    ⭐ Each case asserts BOTH halves. Asserting only that the addresses differ
    would pass for an input that changes nothing, which is a different bug and
    an equally silent one.
    """

    def test_the_text(self, tmp_path):
        first = run(LONG, tmp_path / "a")
        second = run(LONG + " And one more.", tmp_path / "b")
        assert first.audio != second.audio
        assert first.artifact_id != second.artifact_id

    def test_the_voice(self, tmp_path):
        """⚠️ The engine here returns one chunk's bytes regardless of voice, so
        the audio is compared through what the engine was ASKED, which is the
        honest form for a fake."""
        engine_a = FakeEngine(per_chunk=text_sensitive)
        engine_b = FakeEngine(per_chunk=text_sensitive)
        first = run(LONG, tmp_path / "a", voice="am_liam", engine=engine_a)
        second = run(LONG, tmp_path / "b", voice="af_bella", engine=engine_b)
        assert engine_a.calls[0]["voice"] != engine_b.calls[0]["voice"]
        assert first.artifact_id != second.artifact_id

    def test_the_format(self):
        """⚠️ `SUPPORTED_FORMATS` has one member, so this is asserted on the
        minter directly. A second format would be different bytes and the
        store keeps one file per address."""
        assert (address_for(LONG, "am_liam", "mp3", 1800, "fake-1")
                != address_for(LONG, "am_liam", "wav", 1800, "fake-1"))

    def test_the_ENGINE_MODEL(self, tmp_path):
        """⛔ The second one that was missing, and it is now hashed in.

        The model decides how a voice sounds, so two models are two different
        byte-streams for one request. ⭐ **Driven from the synthesis path**: the
        two fakes are given genuinely different audio for the same text, which
        is what a model change actually is, and the address has to move with
        it.

        ⚠️ **The precondition is asserted first.** Without it this case would
        pass for a model change that produced identical audio, which is a
        different bug and an equally quiet one.
        """
        one = run(SHORT, tmp_path / "a",
                  engine=FakeEngine(per_chunk=mpeg_bytes(3), model="first"))
        two = run(SHORT, tmp_path / "b",
                  engine=FakeEngine(per_chunk=mpeg_bytes(7), model="second"))

        assert one.identity.model != two.identity.model
        assert one.audio != two.audio, (
            "the two models produced identical audio, so this case proves "
            "nothing about an audio-changing input"
        )
        assert one.artifact_id != two.artifact_id, (
            "swapping the model kept the address: a corpus would keep every "
            "cached clip and quietly serve audio in a different voice"
        )

    def test_the_engine_FAMILY_and_PROFILE_are_deliberately_NOT_in_it(self, tmp_path):
        """⛔ The other direction, and it is the property the CPU/GPU profiles need.

        ⚠️ **Same model, different profile and different family**: the address
        must NOT move, or a redeployment from the CPU build to the GPU build
        of one model re-synthesises an entire corpus.
        """
        cpu = run(SHORT, tmp_path / "a",
                  engine=FakeEngine(profile="cpu", model="one-model"))
        gpu = run(SHORT, tmp_path / "b",
                  engine=FakeEngine(profile="gpu", model="one-model"))

        assert cpu.identity.profile != gpu.identity.profile
        assert cpu.artifact_id == gpu.artifact_id

    def test_the_CHUNK_BUDGET(self, tmp_path):
        """⛔ The one that was missing, and the reason this module exists.

        The budget decides where the text is cut; each chunk is a separate
        engine request and the pieces are concatenated, so a different budget
        is a different byte-stream at every join.
        """
        wide = run(LONG, tmp_path / "a", chunk_chars=1800)
        narrow = run(LONG, tmp_path / "b", chunk_chars=60)

        assert wide.chunks == 1
        assert narrow.chunks > 1
        assert wide.audio != narrow.audio, (
            "the budget did not change the audio, so this case proves nothing"
        )
        assert wide.artifact_id != narrow.artifact_id, (
            "two different byte-streams share one content address"
        )


class TestTheProducedBytesAreNotInTheAddress:
    def test_two_engines_emitting_DIFFERENT_bytes_give_ONE_address(self, tmp_path):
        """⛔ The audio carve-out, as the thing that makes the cache possible.

        ⚠️ **This is the claim a replaced test only gestured at** -- it asserted
        that an address was a non-empty string. Here two engines
        genuinely produce different audio for one request, and the address is
        unmoved: an address over the OUTPUT would change on every
        re-synthesis, which is a cache that never hits.
        """
        loud = run(SHORT, tmp_path / "a",
                   engine=FakeEngine(per_chunk=mpeg_bytes(9)))
        quiet = run(SHORT, tmp_path / "b",
                    engine=FakeEngine(per_chunk=mpeg_bytes(2)))

        assert loud.audio != quiet.audio
        assert loud.frames != quiet.frames
        assert loud.artifact_id == quiet.artifact_id


class TestTheCostOfCoveringTheBudget:
    def test_a_budget_change_that_changes_NOTHING_still_moves_the_address(self, tmp_path):
        """⚠️ THE ACCEPTED COST, pinned so it is visible rather than discovered.

        A text shorter than both budgets is one chunk either way, so the audio
        is identical and the address still moves. ⛔ **An operator who retunes
        `NARRATE_CHUNK_CHARS` therefore re-synthesises the whole store.**

        ⭐ The alternative -- addressing the CHUNK LIST rather than the text and
        the budget -- is exactly correct here and was rejected: it makes the
        address impossible for a caller to recompute without reimplementing the
        chunker, and `consuming.json` publishes the recipe so that an
        incremental build can decide what to submit. ⚠️ **The error direction
        chosen is the same one the whitespace decision chose: synthesise twice,
        never speak the wrong words.**
        """
        wide = run(SHORT, tmp_path / "a", chunk_chars=1800)
        narrow = run(SHORT, tmp_path / "b", chunk_chars=200)

        assert wide.chunks == narrow.chunks == 1
        assert wide.audio == narrow.audio
        assert wide.artifact_id != narrow.artifact_id


class TestTheDeclaredSetIsTheHashedSet:
    """⭐ Still worth having -- but now it is the SECOND line, not the first."""

    @pytest.mark.parametrize("field", ADDRESS_FIELDS)
    def test_every_named_field_is_one_the_minter_actually_varies_on(self, field):
        """⛔ The inverse blindness: a field NAMED but not hashed.

        Each declared field is varied on its own and must move the address, so
        `ADDRESS_FIELDS` cannot grow a member that is documentation only.
        """
        # ⚠️ `ADDRESS_FIELDS` names the WIRE spelling (`format`); the minter's
        # parameter is `fmt`. Mapped explicitly rather than assumed equal.
        parameter = {"format": "fmt"}.get(field, field)
        base = {"text": LONG, "voice": "am_liam", "fmt": "mp3",
                "chunk_chars": 1800, "engine_model": "first"}
        other = {"text": LONG + " more", "voice": "af_bella",
                 "fmt": "wav", "chunk_chars": 60, "engine_model": "second"}
        changed = dict(base, **{parameter: other[parameter]})
        assert address_for(**base) != address_for(**changed)
