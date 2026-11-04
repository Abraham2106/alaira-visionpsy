# Exporta el contrato canónico a JSON Schema sin importar ni iniciar el servidor.
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.messages import MESSAGE_ADAPTER


def export_schema() -> dict:
    return {"$comment": "Contrato de mensajes JSON de VisionPsy-Local; frames JPEG viajan como binario.",
            "$schema": "https://json-schema.org/draft/2020-12/schema", **MESSAGE_ADAPTER.json_schema()}


if __name__ == "__main__":
    target = ROOT / "docs" / "ws.schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Contrato exportado a docs/ws.schema.json")
