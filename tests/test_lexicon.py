import pytest

from lexicon import SkyrimLexicon


def make(tmp_path, entries, **kwargs):
    path = tmp_path / "lexicon.json"
    path.write_text(__import__("json").dumps(entries), encoding="utf-8")
    return path


def test_alias_and_punctuation_are_preserved(tmp_path):
    lexicon = SkyrimLexicon.load(make(tmp_path, [{"canonical": "Paarthurnax", "aliases": ["partysnax"]}]))
    assert lexicon.correct("Talk to partysnax!") == "Talk to Paarthurnax!"


def test_phrase_correction(tmp_path):
    lexicon = SkyrimLexicon.load(make(tmp_path, ["Winterhold", "Whiterun"]), threshold=0.89, margin=0.10)
    assert lexicon.correct("Travel to winter hold.") == "Travel to Winterhold."


def test_ambiguous_or_common_text_is_untouched(tmp_path):
    lexicon = SkyrimLexicon.load(make(tmp_path, ["Whiterun", "Whiteroom"]), threshold=0.80, margin=0.10)
    assert lexicon.correct("walk the road") == "walk the road"
    assert lexicon.correct("the room is white") == "the room is white"


def test_missing_lexicon_is_empty(tmp_path):
    assert SkyrimLexicon.load(tmp_path / "missing.json").correct("Whiterun") == "Whiterun"


def test_bad_lexicon_fails_clearly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        SkyrimLexicon.load(path)
