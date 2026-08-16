from __future__ import annotations

import numpy as np
import pytest

from asr import ASRError, ParakeetRecognizer


def test_missing_model_directory_has_actionable_error(tmp_path):
    with pytest.raises(ASRError, match="model directory is missing"):
        ParakeetRecognizer(tmp_path / "missing").initialize()


def test_empty_audio_does_not_initialize_model(tmp_path):
    recognizer = ParakeetRecognizer(tmp_path / "missing")
    assert recognizer.transcribe(np.array([], dtype=np.float32)) == ""
