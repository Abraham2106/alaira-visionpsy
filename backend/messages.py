# Esquemas canónicos de los mensajes compartidos con TypeScript y JSON Schema.
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from .domain import ZonesDocument

Level = Literal["ok", "suspect", "critical"]
AlertState = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PoseMsg(Message):
    type: Literal["pose"] = "pose"
    camera_id: str = "cam-1"
    timestamp: float
    landmarks: list[tuple[float, float, float]] | None = Field(default=None, min_length=33, max_length=33)


class StatusMsg(Message):
    type: Literal["status"] = "status"
    camera_id: str = "cam-1"
    timestamp: float
    level: Level
    reasons: list[str]
    camera: Literal["waiting", "streaming", "disconnected"]
    model_error: str | None = None
    diagnostics: dict[str, float | str | None] | None = None


class AlertMsg(Message):
    type: Literal["alert"] = "alert"
    id: str
    timestamp: float
    updated_at: float
    level: Level
    reasons: list[str]
    state: AlertState
    event: Literal["acknowledge", "auto_resolve", "expire"] | None = None
    vision: str | None = None
    vision_error: str | None = None
    attention: Literal["pending", "attending", "discarded", "closed", "expired"] = "pending"
    recovery_at: float | None = None
    kind: Literal["fall", "technical"] = "fall"
    zones: ZonesDocument | None = None
    sources: list[str] = Field(default_factory=lambda: ["cam-1"])


class CameraStatusMsg(Message):
    type: Literal["camera_status"] = "camera_status"
    timestamp: float
    cameras: list[dict[str, str | int | float | bool | None]]


ServerMessage = Annotated[PoseMsg | StatusMsg | AlertMsg | CameraStatusMsg, Field(discriminator="type")]
MESSAGE_ADAPTER = TypeAdapter(ServerMessage)
