# Evita divergencias entre mensajes emitidos, JSON Schema y las interfaces TypeScript.
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from backend.messages import AlertMsg, CameraStatusMsg, PoseMsg, StatusMsg
from scripts.export_schema import export_schema

ROOT = Path(__file__).resolve().parents[1]


def test_documented_schema_matches_backend_and_validates_messages():
    schema = json.loads((ROOT / "docs/ws.schema.json").read_text(encoding="utf-8"))
    assert schema == export_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    examples = [PoseMsg(timestamp=0), PoseMsg(timestamp=0, landmarks=[(0.5, 0.5, 1)] * 33),
                StatusMsg(timestamp=0, level="ok", reasons=[], camera="waiting", diagnostics={"phase":"UPRIGHT","fps":24,"angle_deg":None}),
                AlertMsg(id="synthetic", timestamp=0, updated_at=0, level="critical", reasons=[], state="OPEN"),
                PoseMsg(camera_id="cam-2", timestamp=0),
                AlertMsg(id="multi", timestamp=0, updated_at=0, level="critical", reasons=[], state="OPEN", sources=["cam-1", "cam-2"]),
                CameraStatusMsg(timestamp=0, cameras=[{"camera_id": "cam-1", "name": "Sala", "state": "streaming"}])]
    for message in examples:
        validator.validate(message.model_dump(mode="json"))


def test_typescript_fields_and_discriminants_match_canonical_messages():
    source = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
    for model in [PoseMsg, StatusMsg, AlertMsg, CameraStatusMsg]:
        body = re.search(rf"export interface {model.__name__} \{{(.*?)\n\}}", source, re.S).group(1)
        fields = set(re.findall(r"^\s*(\w+):", body, re.M))
        assert fields == set(model.model_fields)
        assert f'type: "{model.model_fields["type"].default}"' in body
    for name, values in {"Level": {"ok", "suspect", "critical"},
                         "AlertState": {"OPEN", "ACKNOWLEDGED", "RESOLVED"},
                         "CameraState": {"waiting", "streaming", "disconnected"}}.items():
        declaration = re.search(rf"export type {name} = (.*?);", source).group(1)
        assert set(re.findall(r'"(.*?)"', declaration)) == values
