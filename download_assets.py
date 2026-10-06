"""Download the local models and portable Windows title-model runtime."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "model"
LLAMA_DIR = ROOT / "llama"
LLAMA_URL = (
    "https://github.com/ggml-org/llama.cpp/releases/download/b11438/"
    "llama-b11438-bin-win-cpu-x64.zip"
)
LLAMA_SHA256 = "8f9350b0082d1b9052992991456206070e817bfa63cd8d49e7b3bad304306c9e"


def download_llama() -> None:
    executable = LLAMA_DIR / "llama-server.exe"
    if executable.is_file():
        print("Portable title runtime is already installed.")
        return
    print("Downloading portable title runtime...")
    with tempfile.TemporaryDirectory(prefix="spoken-slate-") as temp:
        archive = Path(temp) / "llama.zip"
        with urllib.request.urlopen(LLAMA_URL, timeout=90) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive.open("rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if digest.lower() != LLAMA_SHA256.lower():
            raise RuntimeError("The llama.cpp download did not match its expected SHA-256 hash.")
        LLAMA_DIR.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                destination = (LLAMA_DIR / item.filename).resolve()
                if not destination.is_relative_to(LLAMA_DIR.resolve()):
                    raise RuntimeError("The runtime archive contains an invalid file path.")
            bundle.extractall(LLAMA_DIR)
    if not executable.is_file():
        raise RuntimeError("The runtime archive did not contain llama-server.exe.")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("SpokenSlate currently supports Windows only.")
    MODEL_DIR.mkdir(exist_ok=True)
    if not (MODEL_DIR / "model.bin").is_file():
        print("Downloading the local speech model (about 486 MB)...")
        snapshot_download(
            "Systran/faster-whisper-small.en",
            local_dir=MODEL_DIR,
            allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
        )
    if not (MODEL_DIR / "qwen2.5-1.5b-instruct-q4_k_m.gguf").is_file():
        print("Downloading the local title model (about 1.1 GB)...")
        hf_hub_download(
            "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            local_dir=MODEL_DIR,
        )
    download_llama()
    print("All local assets are ready.")


if __name__ == "__main__":
    main()
