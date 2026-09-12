"""`narrate.voices`, the Kokoro catalogue, and the two-direction claim.

⛔ **The claim this module exists for is the one `NS-04`'s row states and the
one that is usually only half-tested**: changing a corpus's voice invalidates
that corpus's cached audio **and does not invalidate another corpus's**.
⚠️ **The negative half is the half that matters** -- a scheme that invalidated
everything would pass every positive assertion and cost a re-synthesis of the
whole store on every voice change.

⭐ **The instrument for both halves is the ENGINE'S CALL LIST, not a status
string.** A manifest saying `cached` is the code agreeing with itself; a fake
engine that records what it was asked is outside that agreement.
"""

from __future__ import annotations

import pytest

from narrate.artifacts import ArtifactStore
from narrate.config import FORMAT_MEDIA_TYPES, Config, DEFAULT_VOICE
from narrate.engine import UnknownEngine, build_engine
from narrate.engine.kokoro import (
    GENDER_BY_PREFIX,
    LANGUAGE_BY_PREFIX,
    VOICE_IDS,
    decode_voice,
    voice_catalogue,
)
from narrate.jobs import parse_job, run_job
from narrate.voices import UNKNOWN, UnknownVoice, Voice, VoiceCatalogue
from tests.support import NO_SUCH_VOICE, FakeEngine

PROVIDES_UNDER_TEST = 3


def a_voice(voice_id="am_liam"):
    return Voice(id=voice_id, name="Liam", language="en-US", gender="male")


class TestTheCatalogueItself:
    def test_it_keeps_the_order_it_was_given(self):
        """⛔ Ordered, because it is rendered into a menu and into a file.

        An order that changed between two runs would make a published
        declaration's diff meaningless.
        """
        ids = ("c_one", "a_two", "b_three")
        catalogue = VoiceCatalogue([a_voice(v) for v in ids], "c_one")
        assert catalogue.ids() == ids
        assert [v["id"] for v in catalogue.listing()] == list(ids)

    def test_a_duplicate_id_is_refused_rather_than_shadowed(self):
        """⛔ The manifest's duplicate-id rule, one level down: a catalogue
        keyed by id cannot describe two voices under one key without one of
        them being invisible."""
        with pytest.raises(ValueError, match="duplicate voice id: am_liam"):
            VoiceCatalogue([a_voice(), a_voice()], "am_liam")

    def test_a_default_outside_the_catalogue_is_refused_at_construction(self):
        with pytest.raises(UnknownVoice) as raised:
            VoiceCatalogue([a_voice()], NO_SUCH_VOICE)
        assert "am_liam" in str(raised.value)

    def test_membership_and_lookup_answer_without_refusing(self):
        catalogue = VoiceCatalogue([a_voice()], "am_liam")
        assert "am_liam" in catalogue
        assert NO_SUCH_VOICE not in catalogue
        assert catalogue.get("am_liam").name == "Liam"
        assert catalogue.get(NO_SUCH_VOICE) is None
        assert len(catalogue) == 1

    def test_require_names_what_is_permitted(self):
        catalogue = VoiceCatalogue([a_voice("am_liam"), a_voice("af_bella")],
                                   "am_liam")
        with pytest.raises(UnknownVoice) as raised:
            catalogue.require(NO_SUCH_VOICE)
        message = str(raised.value)
        assert "am_liam" in message and "af_bella" in message

    def test_the_refusal_does_NOT_echo_what_arrived(self):
        """⛔ `config._one_of`'s rule. A refusal is copied into whatever log an
        operator pastes somewhere, and this service is a third party to
        everything in a caller's request."""
        catalogue = VoiceCatalogue([a_voice()], "am_liam")
        with pytest.raises(UnknownVoice) as raised:
            catalogue.require("profile-9876543210")
        assert "9876543210" not in str(raised.value)

    def test_the_default_is_kept_out_of_the_listing(self):
        """⭐ A catalogue is an engine-family fact; the default is a deployment
        fact. Two sources for one answer is how they come to disagree."""
        catalogue = VoiceCatalogue([a_voice()], "am_liam")
        assert all("default" not in entry for entry in catalogue.listing())
        assert catalogue.as_dict()["default"] == "am_liam"


class TestTheKokoroCatalogue:
    """⛔ The ids are a MEASUREMENT; the rest is a published decoding of them."""

    def test_it_carries_the_ids_that_were_measured(self):
        catalogue = voice_catalogue(DEFAULT_VOICE)
        assert catalogue.ids() == VOICE_IDS
        assert len(VOICE_IDS) == len(set(VOICE_IDS))

    def test_the_configured_default_is_one_of_them(self):
        assert DEFAULT_VOICE in VOICE_IDS

    @pytest.mark.parametrize("voice_id", VOICE_IDS)
    def test_every_measured_id_decodes_to_a_usable_voice(self, voice_id):
        """⛔ Total. A voice the engine really serves must stay selectable even
        where the naming rule does not reach it."""
        voice = decode_voice(voice_id)
        assert voice.id == voice_id
        assert voice.name
        assert voice.language in set(LANGUAGE_BY_PREFIX.values()) | {UNKNOWN}
        assert voice.gender in set(GENDER_BY_PREFIX.values()) | {UNKNOWN}

    @pytest.mark.parametrize("voice_id,language,gender", [
        ("af_bella", "en-US", "female"),
        ("am_liam", "en-US", "male"),
        ("bf_emma", "en-GB", "female"),
        ("bm_george", "en-GB", "male"),
        ("ef_dora", "es", "female"),
        ("jm_kumo", "ja", "male"),
        ("zf_xiaoni", "zh", "female"),
    ])
    def test_the_published_rule_decodes_the_prefixes_it_claims(
        self, voice_id, language, gender
    ):
        voice = decode_voice(voice_id)
        assert (voice.language, voice.gender) == (language, gender)

    def test_an_UNRECOGNISED_prefix_decodes_to_unknown_and_not_to_a_guess(self):
        """⚠️ The direction that matters when the engine adds a voice: it must
        become selectable, not become wrong."""
        voice = decode_voice("qx_someone")
        assert voice.language == UNKNOWN
        assert voice.gender == UNKNOWN
        assert voice.id == "qx_someone"

    @pytest.mark.parametrize("voice_id,name", [
        ("af_bella", "Bella"),
        ("af_v0bella", "Bella (v0)"),
        ("af_v0", "Legacy (v0)"),
    ])
    def test_a_legacy_voice_is_named_as_one(self, voice_id, name):
        assert decode_voice(voice_id).name == name


class TestAnUnknownVoiceIsRefusedAtStartup:
    """⛔ *"refused with a clear message rather than silently defaulted"*, at
    the level where it is cheapest: before anything is served.

    ⚠️ **A deployment whose `NARRATE_VOICE` is misspelled would otherwise come
    up healthy** and then mis-serve or fail every request that omitted a voice
    -- which is the shape of failure this repository keeps meeting.
    """

    def test_building_the_engine_refuses_a_default_it_does_not_offer(self):
        with pytest.raises(UnknownVoice) as raised:
            build_engine(Config(voice=NO_SUCH_VOICE))
        assert DEFAULT_VOICE in str(raised.value)

    def test_the_refusal_is_not_swallowed_into_an_unknown_engine_error(self):
        """⚠️ Two different refusals with two different remedies."""
        assert not issubclass(UnknownVoice, UnknownEngine)

    def test_a_KNOWN_default_builds(self):
        engine = build_engine(Config(voice="af_bella"))
        assert engine.voices().default == "af_bella"


def submit(texts, voice, store, engine=None):
    """One job over `texts` in `voice`, into `store`. Returns the manifest."""
    engine = engine if engine is not None else FakeEngine()
    job = parse_job(
        {"segments": [{"id": key, "text": text} for key, text in texts.items()],
         "voice": voice},
        default_voice="am_liam", catalogue=engine.voices(),
    )
    manifest = run_job(job, engine=engine, store=store, chunk_chars=1800,
                       media_types=FORMAT_MEDIA_TYPES,
                       provides=PROVIDES_UNDER_TEST)
    return manifest, engine


def addresses(manifest):
    return {e["id"]: e["artifact_id"] for e in manifest["segments"]}


#: ⭐ Two corpora, disjoint prose, ONE store -- which is where a
#: cross-invalidation would actually happen. Two stores would make the negative
#: half true by construction and prove nothing.
CORPUS_A = {f"a-s{n:03d}": f"Corpus A, speech unit {n}." for n in range(1, 5)}
CORPUS_B = {f"b-s{n:03d}": f"Corpus B, speech unit {n}." for n in range(1, 5)}


class TestChangingAVoiceInvalidatesThatCorpusAndNoOther:
    """⛔ `NS-04`'s Acceptance, and both halves are asserted on the ENGINE."""

    @pytest.fixture
    def both_corpora(self, tmp_path):
        """Both corpora synthesised into one store, in one voice."""
        store = ArtifactStore(tmp_path)
        first_a, engine_a = submit(CORPUS_A, "am_liam", store)
        first_b, engine_b = submit(CORPUS_B, "am_liam", store)
        assert len(engine_a.calls) == len(CORPUS_A)
        assert len(engine_b.calls) == len(CORPUS_B)
        return store, addresses(first_a), addresses(first_b)

    def test_the_corpus_whose_voice_changed_is_ENTIRELY_resynthesised(
        self, both_corpora
    ):
        store, before_a, _ = both_corpora
        manifest, engine = submit(CORPUS_A, "af_bella", store)

        assert len(engine.calls) == len(CORPUS_A)
        assert {call["voice"] for call in engine.calls} == {"af_bella"}
        after_a = addresses(manifest)
        assert set(after_a) == set(before_a)
        for key in before_a:
            assert after_a[key] != before_a[key]

    def test_the_OTHER_corpus_is_untouched_and_still_costs_NOTHING(
        self, both_corpora
    ):
        """⛔ THE NEGATIVE HALF, and it is the one usually missing.

        ⚠️ Asserted after A's voice has already moved, in the same store, so a
        scheme that invalidated the store rather than the corpus would fail
        here and nowhere else.
        """
        store, _, before_b = both_corpora
        submit(CORPUS_A, "af_bella", store)

        manifest, engine = submit(CORPUS_B, "am_liam", store)

        assert engine.calls == []
        assert [e["status"] for e in manifest["segments"]] == ["cached"] * len(CORPUS_B)
        assert addresses(manifest) == before_b

    def test_the_first_voices_artifacts_are_KEPT_and_not_deleted(
        self, both_corpora, tmp_path
    ):
        """⚠️ Nothing is garbage-collected, and a consumer plans around that.

        ⭐ Changing a voice back is therefore free, and that is worth knowing
        rather than discovering.
        """
        store, before_a, before_b = both_corpora
        submit(CORPUS_A, "af_bella", store)

        for address in list(before_a.values()) + list(before_b.values()):
            assert store.path_for(address).exists()

        back, engine = submit(CORPUS_A, "am_liam", store)
        assert engine.calls == []
        assert addresses(back) == before_a
