"""Datos de configuración editables: sin imágenes ni credenciales en las respuestas."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["bed", "chair", "other"] = "other"
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=32)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Escribe un nombre para la zona")
        return value.strip()

    @field_validator("polygon")
    @classmethod
    def geometry(cls, points):
        if any(not math.isfinite(v) or not 0 <= v <= 1 for point in points for v in point):
            raise ValueError("Los puntos deben estar dentro de la imagen")
        if len(set(points)) != len(points):
            raise ValueError("No repitas vértices")
        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        def on_segment(a, b, c):
            return abs(cross(a,b,c)) < 1e-12 and min(a[0],b[0]) <= c[0] <= max(a[0],b[0]) and min(a[1],b[1]) <= c[1] <= max(a[1],b[1])
        edges = list(zip(points, points[1:]+points[:1]))
        area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in edges))/2
        if area < 1e-5:
            raise ValueError("La zona debe tener superficie")
        for i,(a,b) in enumerate(edges):
            for j,(c,d) in enumerate(edges):
                if j <= i+1 or (i == 0 and j == len(edges)-1):
                    continue
                if (cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0) or any((on_segment(a,b,c),on_segment(a,b,d),on_segment(c,d,a),on_segment(c,d,b))):
                    raise ValueError("Los bordes de la zona no pueden cruzarse")
        return points


class ZonesDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(default=0, ge=0)
    zones: list[Zone] = Field(default_factory=list, max_length=16)

    @field_validator("zones")
    @classmethod
    def unique_ids(cls, zones):
        if len({z.id for z in zones}) != len(zones):
            raise ValueError("Los IDs de zona deben ser únicos")
        return zones


class EventAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["attend", "discard", "close"]
    reason: str = Field(default="", max_length=300)
