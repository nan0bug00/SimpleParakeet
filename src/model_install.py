"""Verified first-run installation for selectable Sherpa ONNX models."""

from __future__ import annotations

import hashlib
import logging
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelProfile:
    """Immutable installation and recognizer settings for one offered model."""

    id: str
    label: str
    model_type: str
    url: str
    sha256: str
    directory_name: str
    required_files: tuple[str, ...]
    default_threads: int = 4


DEFAULT_MODEL_CHOICE = "english-110m"
MODEL_PROFILES = {
    "english-110m": ModelProfile(
        id="english-110m",
        label="English — Fast (110M), recommended",
        model_type="nemo_ctc",
        url=(
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
            "sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8.tar.bz2"
        ),
        sha256="17f945007b52ccd8b7200ffc7c5652e9e8e961dfdf479cefcabd06cf5703630b",
        directory_name="sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8",
        required_files=("model.int8.onnx", "tokens.txt"),
    ),
    "multilingual-600m": ModelProfile(
        id="multilingual-600m",
        label="Multilingual (0.6B), slower",
        model_type="nemo_transducer",
        url=(
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
            "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
        ),
        sha256="5793d0fd397c5778d2cf2126994d58e9d56b1be7c04d13c7a15bb1b4eafb16bf",
        directory_name="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        required_files=(
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        ),
    ),
}

LOG = logging.getLogger("simpleparakeet.model")


def get_model_profile(choice: str) -> ModelProfile:
    try:
        return MODEL_PROFILES[choice]
    except KeyError as exc:
        available = ", ".join(MODEL_PROFILES)
        raise ValueError(f"Unknown model choice {choice!r}; expected one of: {available}") from exc


def model_is_complete(directory: Path, profile: ModelProfile) -> bool:
    return directory.is_dir() and all(
        (directory / name).is_file() for name in profile.required_files
    )


def default_model_directory(root: Path, profile: ModelProfile) -> Path:
    return root / "models" / profile.directory_name


def ensure_model(profile: ModelProfile, directory: Path) -> None:
    """Install one selected, verified model without touching other profiles."""
    if model_is_complete(directory, profile):
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{profile.id}-", dir=directory.parent) as temp:
        temp_path = Path(temp)
        archive = temp_path / "model.tar.bz2"
        digest = hashlib.sha256()
        LOG.info("Downloading %s (first-run setup)...", profile.label)
        try:
            with urlopen(profile.url, timeout=60) as response, archive.open("wb") as output:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
        except OSError as exc:
            raise RuntimeError(f"Could not download {profile.label}: {exc}") from exc
        if digest.hexdigest() != profile.sha256:
            raise RuntimeError(f"{profile.label} checksum mismatch; the download was discarded.")
        try:
            with tarfile.open(archive, mode="r:bz2") as tar:
                root = temp_path.resolve()
                members = tar.getmembers()
                if any(not (root / member.name).resolve().is_relative_to(root) for member in members):
                    raise RuntimeError(f"{profile.label} archive contains an unsafe path.")
                for member in members:
                    tar.extract(member, path=temp_path)
        except (OSError, tarfile.TarError) as exc:
            raise RuntimeError(f"Could not unpack {profile.label}: {exc}") from exc
        extracted = temp_path / profile.directory_name
        if not model_is_complete(extracted, profile):
            raise RuntimeError(f"{profile.label} archive is incomplete; the download was discarded.")
        if directory.exists():
            shutil.rmtree(directory)
        shutil.move(str(extracted), str(directory))
        LOG.info("%s installed and checksum verified.", profile.label)
