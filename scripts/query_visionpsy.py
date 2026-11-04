"""Run one local query without saving its JPEG or answer to disk."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.visionpsy import VisionPsyModel


def main() -> None:
    root = ROOT
    model_dir = root / "models" / "visionpsy-nano-flash"
    parser = argparse.ArgumentParser()
    parser.add_argument("jpeg", type=Path)
    parser.add_argument("question")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--tokens", type=int, default=128)
    args = parser.parse_args()
    runtime = model_dir / "runtime" / "bin" / "llama-server.exe"
    instance = VisionPsyModel(
        executable=runtime,
        model_path=model_dir / "visionpsy-nano-460m-flash-q4_k_m-imat.gguf",
        mmproj_path=model_dir / "mmproj-visionpsy-nano-460m-flash-q8.gguf",
        timeout_seconds=args.timeout,
        startup_timeout_seconds=180,
        max_tokens=args.tokens,
        runtime_library_dirs=(model_dir / "cuda-13.1.2" / "Library" / "bin",),
    )

    async def query() -> None:
        async with instance:
            answer = await instance.ask(args.jpeg.read_bytes(), args.question)
            print(answer.text)

    asyncio.run(query())


if __name__ == "__main__":
    main()
