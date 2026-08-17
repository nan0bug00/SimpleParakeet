from __future__ import annotations

import json

import pytest

from lexicon import Entry, SkyrimLexicon, _phonetic_keys


def make(tmp_path, entries):
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return path


def canonical_engine(*entries: str) -> SkyrimLexicon:
    return SkyrimLexicon(Entry(entry) for entry in entries)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("your Vaskar", "Jorrvaskr"),
        ("Yor Vaskar", "Jorrvaskr"),
        ("Uthgird", "Uthgerd"),
        ("Youthgird", "Uthgerd"),
        ("Travel to White Run.", "Travel to Whiterun."),
    ],
)
def test_named_contract_examples_need_only_canonical_terms(source, expected):
    engine = canonical_engine("Jorrvaskr", "Uthgerd", "Whiterun")
    assert engine.correct(source) == expected


def test_phonetic_keys_derive_required_equivalence_from_each_text():
    assert set(_phonetic_keys("Yor Vaskar")) & set(_phonetic_keys("Jorrvaskr"))
    assert set(_phonetic_keys("Youthgird")) & set(_phonetic_keys("Uthgerd"))


def test_exact_common_word_boundary_match_is_canonicalized_everywhere():
    engine = canonical_engine("Whiterun")
    assert engine.correct("The white run is long.") == "The Whiterun is long."
    assert engine.correct("White Run") == "Whiterun"
    assert engine.correct("I traveled to white run yesterday.") == "I traveled to Whiterun yesterday."


def test_punctuation_repetition_and_unselected_bytes_are_preserved():
    engine = canonical_engine("Uthgerd")
    source = "  Youthgird—then Uthgird?!  café\n"
    assert engine.correct(source) == "  Uthgerd—then Uthgerd?!  café\n"
    untouched = "  Nothing—changes here?!  café\n"
    assert engine.correct(untouched) == untouched


def test_global_selection_prefers_strong_long_span_without_collateral_changes():
    engine = canonical_engine("High Hrothgar", "Hrothgar")
    assert engine.correct("Visit high hrothgar, now.") == "Visit High Hrothgar, now."


def test_full_and_short_character_names_can_coexist():
    engine = canonical_engine("Ulfberth", "Ulfberth War-Bear")
    assert engine.correct("Good morning, Ulfberth.") == "Good morning, Ulfberth."
    assert engine.correct("Find Ulfberth War Bear.") == "Find Ulfberth War-Bear."


def test_ambiguous_phonetic_collision_is_rejected():
    engine = canonical_engine("Cern", "Kern")
    assert engine.correct("Kurn") == "Kurn"


def test_trace_explains_acceptance_and_rejection():
    engine = canonical_engine("Whiterun")
    output, trace = engine.correct_with_trace("Travel to White Run.")
    assert output == "Travel to Whiterun."
    accepted = [decision for decision in trace.decisions if decision.accepted]
    assert accepted and accepted[0].candidates[0].method == "compact"
    assert accepted[0].candidates[0].context_score > 0
    assert trace.stage_timings_ms["total"] >= 0
    assert "model" not in json.dumps(trace.as_dict()).casefold()


def test_missing_and_invalid_lexicons(tmp_path):
    assert SkyrimLexicon.load(tmp_path / "missing.json").correct("Whiterun") == "Whiterun"
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Skyrim lexicon"):
        SkyrimLexicon.load(bad)


def test_normalized_canonical_collision_fails_at_load(tmp_path):
    path = make(tmp_path, ["High-Hrothgar", "High Hrothgar"])
    with pytest.raises(ValueError, match="Canonical collision"):
        SkyrimLexicon.load(path)
