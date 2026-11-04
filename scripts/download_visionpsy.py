"""Download only the selected official Flash GGUFs and write a local hash manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download


REPO_ID = "qvac/VisionPsy-Nano-460M-Flash-GGUFs"
REVISION = "a24fb9cdd1119406b15ff60b06a51f8438a931c1"
FILES = (
    "visionpsy-nano-460m-flash-q4_k_m-imat.gguf",
    "mmproj-visionpsy-nano-460m-flash-q8.gguf",
)
SHA256 = (
    "90b0abe16180f1fe5918bc5d89c3b6eeaf40520a50f906d6303a59a32b699fbc",
    "bbb0691873a4e638f6928898b3c3be9a4730bd4ced301197726a4fcb549695d0",
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "models" / "visionpsy-nano-flash"
    destination.mkdir(parents=True, exist_ok=True)
    info = HfApi().model_info(REPO_ID, revision=REVISION, files_metadata=True)
    if info.sha != REVISION:
        raise SystemExit(f"La revisión descargada no coincide: {info.sha}")
    expected = {item.rfilename: item.size for item in info.siblings if item.rfilename in FILES}
    manifest = {"repository": REPO_ID, "revision": REVISION, "files": []}
    for name, checksum in zip(FILES, SHA256):
        if name not in expected:
            raise SystemExit(f"El archivo ya no está publicado en la revisión fijada: {name}")
        path = Path(hf_hub_download(REPO_ID, name, revision=REVISION, local_dir=destination))
        size = path.stat().st_size
        if size != expected[name]:
            raise SystemExit(f"Tamaño inesperado para {name}: {size} != {expected[name]}")
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(8 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != checksum:
            raise SystemExit(f"SHA-256 inesperado para {name}")
        manifest["files"].append({"name": name, "size_bytes": size, "sha256": digest.hexdigest()})
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
