"""Sherpa-ONNX Parakeet v3 offline recognition backend."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

MODEL_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
DEFAULT_ONNX_THREADS = min(4, max(1, (os.cpu_count() or 1) // 2))


class ASRError(RuntimeError):
    """A user-actionable recognizer or model error."""


class ParakeetRecognizer:
    """One reusable offline recognizer; decode calls are serialized safely."""

    def __init__(
        self,
        model_dir: str | Path,
        num_threads: int = DEFAULT_ONNX_THREADS,
        *,
        model_type: str = "nemo_transducer",
    ):
        self.model_dir = Path(model_dir)
        self.num_threads = max(1, int(num_threads))
        self.model_type = model_type
        self._recognizer = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        if self._recognizer is not None:
            return
        if not self.model_dir.is_dir():
            raise ASRError(f"Parakeet v3 model directory is missing: {self.model_dir}")

        def required(label: str, suffix: str) -> Path:
            candidates = sorted(
                p for p in self.model_dir.glob(f"*{suffix}") if label in p.name.lower()
            )
            if not candidates:
                raise ASRError(
                    f"Parakeet v3 model is incomplete: missing {label}{suffix} in {self.model_dir}"
                )
            return candidates[0]

        try:
            import sherpa_onnx

            if self.model_type == "nemo_ctc":
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                    model=str(required("model", ".onnx")),
                    tokens=str(required("tokens", ".txt")),
                    num_threads=self.num_threads,
                    provider="cpu",
                    debug=False,
                )
            elif self.model_type == "nemo_transducer":
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(required("encoder", ".onnx")),
                    decoder=str(required("decoder", ".onnx")),
                    joiner=str(required("joiner", ".onnx")),
                    tokens=str(required("tokens", ".txt")),
                    num_threads=self.num_threads,
                    model_type="nemo_transducer",
                    debug=False,
                )
            else:
                raise ASRError(f"Unsupported Parakeet model type: {self.model_type}")
        except ImportError as exc:
            raise ASRError("sherpa-onnx is not installed; reinstall SimpleParakeet.") from exc
        except Exception as exc:
            raise ASRError(f"Could not initialize Parakeet v3: {exc}") from exc

    def transcribe(self, samples: np.ndarray, sample_rate: int = 16_000) -> str:
        if sample_rate != 16_000:
            raise ASRError(f"Parakeet v3 expects 16 kHz audio, received {sample_rate} Hz")
        if samples.size == 0 or not np.isfinite(samples).all():
            return ""
        self.initialize()
        # The Python binding's recognizer is reusable, but streams are per utterance.
        # Serializing prevents concurrent requests from corrupting decoder state.
        with self._lock:
            try:
                stream = self._recognizer.create_stream()
                stream.accept_waveform(sample_rate, samples.astype(np.float32, copy=False))
                self._recognizer.decode_stream(stream)
                return (stream.result.text or "").strip()
            except Exception as exc:
                raise ASRError(f"Parakeet v3 transcription failed: {exc}") from exc
