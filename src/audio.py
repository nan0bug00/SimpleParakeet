"""Decode uploaded audio (incl. raw PCM) to 16 kHz mono WAV bytes for parakeet.cpp."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

TARGET_SR = 16_000

# Extensions / content-types treated as headerless PCM16 LE
_PCM_EXTS = {".pcm", ".raw", ".s16le"}


def _is_pcm(filename: str | None, content_type: str | None, force_pcm: bool) -> bool:
    if force_pcm:
        return True
    name = (filename or "").lower()
    ctype = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(name).suffix
    if suffix in _PCM_EXTS:
        return True
    if ctype in {"audio/pcm", "audio/l16", "audio/x-pcm"}:
        return True
    # Bare octet-stream / missing type with no media extension → treat as PCM
    # only when the caller also forces it via encoding= / .pcm name.
    return False


def _pcm16_to_float_mono(data: bytes, channels: int) -> np.ndarray:
    if len(data) < 2:
        raise ValueError("PCM payload is empty")
    if len(data) % 2:
        data = data[:-1]
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if channels <= 1:
        return samples
    if samples.size % channels:
        samples = samples[: samples.size - (samples.size % channels)]
    framed = samples.reshape(-1, channels)
    return framed.mean(axis=1)


def _resample_linear(audio: np.ndarray, src_sr: int, dst_sr: int = TARGET_SR) -> np.ndarray:
    if src_sr == dst_sr:
        return audio.astype(np.float32, copy=False)
    if src_sr <= 0:
        raise ValueError(f"Invalid sample rate: {src_sr}")
    if audio.size == 0:
        return audio.astype(np.float32)
    duration = audio.size / float(src_sr)
    n_out = max(1, int(round(duration * dst_sr)))
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def float_mono_to_wav_bytes(audio: np.ndarray, sample_rate: int = TARGET_SR) -> bytes:
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        # try 32-bit float first, then 32-bit int
        as_f32 = np.frombuffer(raw, dtype="<f4")
        if np.isfinite(as_f32).all() and float(np.max(np.abs(as_f32))) <= 8.0:
            samples = as_f32.astype(np.float32)
        else:
            samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width}")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32), int(sr)


def _find_ffmpeg() -> str | None:
    env = (os.environ.get("PARAKEET_FFMPEG") or "").strip()
    if env and Path(env).is_file():
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    # Frozen / portable bundle: bin\ffmpeg.exe next to the exe or cwd
    candidates = [
        Path(sys.executable).resolve().parent / "ffmpeg.exe",
        Path.cwd() / "ffmpeg.exe",
        Path.cwd() / "bin" / "ffmpeg.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def _ffmpeg_to_wav16k(data: bytes, filename: str | None) -> bytes:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found; required to decode non-WAV/non-PCM audio. "
            "Install ffmpeg on PATH or place ffmpeg.exe in bin/."
        )
    suffix = Path(filename or "audio.bin").suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="parakeet-api-") as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(data)
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(TARGET_SR),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not dst.exists():
            err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
            raise RuntimeError(f"ffmpeg decode failed: {err}")
        return dst.read_bytes()


def decode_to_wav16k_mono(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    sample_rate: int = TARGET_SR,
    channels: int = 1,
    force_pcm: bool = False,
) -> bytes:
    """
    Return a RIFF WAV (16-bit PCM, mono, 16 kHz) suitable for parakeet-server.
    """
    if not data:
        raise ValueError("Empty audio payload")

    name = (filename or "").lower()
    ctype = (content_type or "").split(";")[0].strip().lower()

    if _is_pcm(filename, content_type, force_pcm):
        mono = _pcm16_to_float_mono(data, max(1, int(channels)))
        mono = _resample_linear(mono, int(sample_rate), TARGET_SR)
        return float_mono_to_wav_bytes(mono, TARGET_SR)

    # Native WAV path (common for local clients)
    if Path(name).suffix == ".wav" or ctype in {"audio/wav", "audio/x-wav", "audio/wave"}:
        try:
            audio, sr = _decode_wav(data)
            audio = _resample_linear(audio, sr, TARGET_SR)
            return float_mono_to_wav_bytes(audio, TARGET_SR)
        except Exception:
            # fall through to ffmpeg for odd WAV variants
            pass

    # Try WAV magic even if mislabeled
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        try:
            audio, sr = _decode_wav(data)
            audio = _resample_linear(audio, sr, TARGET_SR)
            return float_mono_to_wav_bytes(audio, TARGET_SR)
        except Exception:
            pass

    return _ffmpeg_to_wav16k(data, filename)
