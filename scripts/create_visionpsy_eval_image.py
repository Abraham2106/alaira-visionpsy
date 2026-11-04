"""Create a simple synthetic image for local VisionPsy smoke checks."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "models" / "visionpsy-nano-flash" / "test-scene.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (512, 512), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 60, 440, 450), outline="black", width=5)
    draw.ellipse((200, 105, 295, 200), fill="orange", outline="black", width=4)
    draw.line((248, 200, 248, 340), fill="blue", width=14)
    draw.line((248, 240, 175, 305), fill="blue", width=12)
    draw.line((248, 240, 325, 305), fill="blue", width=12)
    draw.line((248, 340, 185, 430), fill="green", width=14)
    draw.line((248, 340, 310, 430), fill="green", width=14)
    image.save(output, quality=90)
    print(output)


if __name__ == "__main__":
    main()
