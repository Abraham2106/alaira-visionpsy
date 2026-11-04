# Carga y valida YAML y entorno sin permitir autenticación vacía ni CORS abierto.
import ipaddress
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RiskConfig(ConfigModel):
    torso_angle_deg: float = Field(default=60, gt=0, le=180)
    hip_drop_speed: float = Field(default=0.8, gt=0)
    drop_window_seconds: float = Field(default=1, gt=0)
    immobile_seconds: float = Field(default=5, gt=0)
    motion_epsilon: float = Field(default=0.015, gt=0)
    min_visibility: float = Field(default=0.5, ge=0, le=1)
    max_pose_gap_seconds: float = Field(default=1, gt=0)
    safe_zones: list[list[tuple[float, float]]] = Field(default_factory=list)

    @field_validator("safe_zones")
    @classmethod
    def polygons(cls, zones):
        if any(len(zone) < 3 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in zone)
               for zone in zones):
            raise ValueError("Cada zona necesita al menos tres puntos normalizados")
        return zones


class ServerConfig(ConfigModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    max_frame_bytes: int = Field(default=2_000_000, gt=0)
    auth_timeout_seconds: float = Field(default=5, gt=0)
    send_timeout_seconds: float = Field(default=2, gt=0)
    camera_timeout_seconds: float = Field(default=4, gt=0)
    tick_seconds: float = Field(default=0.5, gt=0)

    @field_validator("host")
    @classmethod
    def local_host(cls, host):
        address = ipaddress.ip_address(host)
        if not address.is_private or address.is_unspecified or address.is_multicast:
            raise ValueError("APP_HOST debe ser una IP concreta local/LAN")
        return host

    @field_validator("allowed_origins")
    @classmethod
    def restricted_origins(cls, origins):
        from urllib.parse import urlparse
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or "*" in origin or parsed.path:
                raise ValueError("Usa orígenes HTTP(S) explícitos sin ruta ni comodines")
        return origins


class AlertConfig(ConfigModel):
    auto_resolve_seconds: float = Field(default=3, gt=0)
    expire_seconds: float = Field(default=120, gt=0)
    history_size: int = Field(default=100, ge=1)


class PoseConfig(ConfigModel):
    backend: str = "stub"
    model_path: str = "../models/pose_landmarker_lite.task"
    scenario: str = "standing"
    demo_cycle_seconds: float = Field(default=24, gt=12)


class VisionConfig(ConfigModel):
    backend: str = "stub"
    gguf_path: str = "../models/visionpsy-nano-flash/visionpsy-nano-460m-flash-q4_k_m-imat.gguf"
    mmproj_path: str = "../models/visionpsy-nano-flash/mmproj-visionpsy-nano-460m-flash-q8.gguf"
    executable: str = "../models/visionpsy-nano-flash/runtime/bin/llama-server.exe"
    runtime_library_dirs: list[str] = Field(default_factory=list)
    port: int = Field(default=8089, ge=1, le=65535)
    gpu_layers: int = Field(default=99, ge=0, le=99)
    startup_timeout_seconds: float = Field(default=90, gt=0)
    max_tokens: int = Field(default=128, ge=1, le=512)
    timeout_seconds: float = Field(default=15, gt=0)


class ModelsConfig(ConfigModel):
    pose: PoseConfig = Field(default_factory=PoseConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)


class PipelineConfig(ConfigModel):
    history_seconds: float = Field(default=30, gt=0)
    history_size: int = Field(default=1024, ge=2)
    vision_question: str = "¿Hay una persona en el suelo fuera de la cama o silla?"


class PrivacyConfig(ConfigModel):
    save_clips: bool = False


class StorageConfig(ConfigModel):
    path: str = ":memory:"
    retention_days: int = Field(default=7, ge=1, le=365)


class NotificationConfig(ConfigModel):
    enabled: bool = False
    reminder_seconds: float = Field(default=60, ge=10)
    room_alias: str = Field(default="Habitación", min_length=1, max_length=80)


class Settings(ConfigModel):
    token: str = Field(min_length=1, repr=False)
    server: ServerConfig = Field(default_factory=ServerConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)

    @field_validator("token")
    @classmethod
    def nonempty_token(cls, token):
        if not token.strip():
            raise ValueError("APP_TOKEN es obligatorio")
        return token

    @model_validator(mode="after")
    def history_covers_immobility(self):
        if self.pipeline.history_seconds <= self.risk.immobile_seconds:
            raise ValueError(
                "pipeline.history_seconds debe superar risk.immobile_seconds "
                "para poder verificar la inmovilidad"
            )
        return self


def load_settings(path: str | Path | None = None) -> Settings:
    base = Path(__file__).parent
    load_dotenv(base / ".env", override=False)
    config_path = Path(path or os.getenv("CONFIG_PATH", base / "config.yaml")).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw["token"] = os.getenv("APP_TOKEN", "")
    raw.setdefault("storage", {}).setdefault("path", str((base.parent / "data" / "visionpsy.sqlite3").resolve()))
    if os.getenv("APP_STORAGE_PATH"):
        raw["storage"]["path"] = os.environ["APP_STORAGE_PATH"]
    if os.getenv("POSE_BACKEND"):
        raw.setdefault("models", {}).setdefault("pose", {})["backend"] = os.environ["POSE_BACKEND"]
    if os.getenv("APP_PORT"):
        raw.setdefault("server", {})["port"] = os.environ["APP_PORT"]
    server = raw.setdefault("server", {})
    if os.getenv("APP_HOST"):
        server["host"] = os.environ["APP_HOST"]
    if os.getenv("APP_ALLOWED_ORIGINS"):
        server["allowed_origins"] = os.environ["APP_ALLOWED_ORIGINS"].split(",")
    settings = Settings.model_validate(raw)
    pose = settings.models.pose
    vision = settings.models.vision
    pose_path = (config_path.parent / pose.model_path).resolve()
    vision_paths = {name: str((config_path.parent / getattr(vision, name)).resolve())
                    for name in ("gguf_path", "mmproj_path", "executable")}
    vision_paths["runtime_library_dirs"] = [str((config_path.parent / path).resolve())
                                            for path in vision.runtime_library_dirs]
    return settings.model_copy(update={"models": settings.models.model_copy(update={
        "pose": pose.model_copy(update={"model_path": str(pose_path)}),
        "vision": vision.model_copy(update=vision_paths)})})
