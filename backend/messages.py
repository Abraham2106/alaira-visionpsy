# Esquemas canónicos de los mensajes compartidos con TypeScript y JSON Schema.
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Level = Literal["ok", "suspect", "critical"]
AlertState = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PoseMsg(Message):
    type: Literal["pose"] = "pose"
    timestamp: float
    landmarks: list[tuple[float, float, float]] | None = Field(default=None, min_length=33, max_length=33)


class StatusMsg(Message):
    type: Literal["status"] = "status"
    timestamp: float
    level: Level
    reasons: list[str]
    camera: Literal["waiting", "streaming", "disconnected"]
    model_error: str | None = None


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


ServerMessage = Annotated[PoseMsg | StatusMsg | AlertMsg, Field(discriminator="type")]
MESSAGE_ADAPTER = TypeAdapter(ServerMessage)
