"""Trusted first-run installation for the bundled Parakeet v3 model."""

from __future__ import annotations

import hashlib
import logging
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
MODEL_SHA256 = "5793d0fd397c5778d2cf2126994d58e9d56b1be7c04d13c7a15bb1b4eafb16bf"
MODEL_DIRNAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
REQUIRED_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
LOG = logging.getLogger("simpleparakeet.model")


def model_is_complete(directory: Path) -> bool:
    return directory.is_dir() and all((directory / name).is_file() for name in REQUIRED_FILES)


def ensure_model(directory: Path) -> None:
    """Install a verified model once, never treating a partial download as valid."""
    if model_is_complete(directory):
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".parakeet-v3-", dir=directory.parent) as temp:
        temp_path = Path(temp)
        archive = temp_path / "model.tar.bz2"
        digest = hashlib.sha256()
        LOG.info("Downloading Parakeet v3 model (first-run setup, about 465 MB)...")
        try:
            with urlopen(MODEL_URL, timeout=60) as response, archive.open("wb") as output:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
        except OSError as exc:
            raise RuntimeError(f"Could not download the Parakeet v3 model: {exc}") from exc
        if digest.hexdigest() != MODEL_SHA256:
            raise RuntimeError("Parakeet v3 model checksum mismatch; the download was discarded.")
        try:
            with tarfile.open(archive, mode="r:bz2") as tar:
                # Do not permit archive members to escape the temporary directory.
                root = temp_path.resolve()
                members = tar.getmembers()
                if any(not (root / member.name).resolve().is_relative_to(root) for member in members):
                    raise RuntimeError("Parakeet v3 archive contains an unsafe path.")
                # Extract member-by-member for compatibility with Python versions
                # that predate tarfile's ``filter=`` parameter.
                for member in members:
                    tar.extract(member, path=temp_path)
        except (OSError, tarfile.TarError) as exc:
            raise RuntimeError(f"Could not unpack the verified Parakeet v3 model: {exc}") from exc
        extracted = temp_path / MODEL_DIRNAME
        if not model_is_complete(extracted):
            raise RuntimeError("Parakeet v3 archive is incomplete; the download was discarded.")
        if directory.exists():
            shutil.rmtree(directory)
        shutil.move(str(extracted), str(directory))
        LOG.info("Parakeet v3 model installed and checksum verified.")
