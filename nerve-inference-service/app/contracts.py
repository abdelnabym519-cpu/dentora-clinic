from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    z: float = Field(ge=-1_000_000, le=1_000_000)


class Uncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: float = Field(ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=255)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: str | None = Field(default=None, min_length=1, max_length=128)
    side: Literal["left", "right"]
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: Uncertainty | None = None
    points_mm: list[Point] = Field(min_length=2, max_length=2048)


class InferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["detected", "no_detection", "uncertain"]
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    findings: list[Finding] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _consistent(self) -> "InferenceResponse":
        if self.status == "no_detection" and self.findings:
            raise ValueError("no_detection cannot include findings")
        if self.status != "no_detection" and not self.findings:
            raise ValueError("detected or uncertain requires findings")
        supplied_ids = [item.finding_id for item in self.findings if item.finding_id]
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ValueError("finding identifiers must be unique")
        return self
