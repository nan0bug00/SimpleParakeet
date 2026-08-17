from __future__ import annotations

import numpy as np
import pytest

from asr import ASRError, ParakeetRecognizer
from model_install import DEFAULT_MODEL_CHOICE, MODEL_PROFILES, model_is_complete


def test_missing_model_directory_has_actionable_error(tmp_path):
    with pytest.raises(ASRError, match="model directory is missing"):
        ParakeetRecognizer(tmp_path / "missing").initialize()


def test_empty_audio_does_not_initialize_model(tmp_path):
    recognizer = ParakeetRecognizer(tmp_path / "missing")
    assert recognizer.transcribe(np.array([], dtype=np.float32)) == ""


def test_model_profiles_offer_fast_english_before_multilingual(tmp_path):
    assert DEFAULT_MODEL_CHOICE == "english-110m"
    assert tuple(MODEL_PROFILES) == ("english-110m", "multilingual-600m")
    assert MODEL_PROFILES["english-110m"].model_type == "nemo_ctc"
    assert MODEL_PROFILES["multilingual-600m"].model_type == "nemo_transducer"
    assert not model_is_complete(tmp_path, MODEL_PROFILES["english-110m"])
