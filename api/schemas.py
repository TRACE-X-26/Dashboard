from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ProfilePayload(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    rated_voltage: float = Field(gt=0)
    rated_current: float = Field(gt=0)
    rated_rpm: float = Field(gt=0)
    winding_resistance: float = Field(gt=0)
    max_current: float = Field(gt=0)
    max_temperature: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_current_limits(self):
        if self.max_current < self.rated_current:
            raise ValueError("max_current cannot be below rated_current")
        return self


class TestRequest(BaseModel):
    device_id: str
    scenario: str = "healthy"
    samples: int = Field(default=25, ge=5, le=500)
    interval_ms: int = Field(default=100, ge=0, le=5000)


class MotorCommandPayload(BaseModel):
    command_id: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=40)
    value: int | str | None = None


class CircuitRunPayload(BaseModel):
    profile_id: str
    mode: str = "DIAGNOSE"
    scenario: str = "healthy"


class STM32CommandPayload(BaseModel):
    command: str = Field(min_length=1, max_length=40)
    arguments: dict = Field(default_factory=dict)


class HistoricalImportPayload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)
    device_id: str = Field(min_length=1, max_length=80)
    condition: str = Field(default="UNKNOWN", max_length=120)
    attached_mass_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fixture_description: str = Field(default="", max_length=2000)
    target_pwm_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
