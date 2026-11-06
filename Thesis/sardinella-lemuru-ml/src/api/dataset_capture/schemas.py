"""Validated inputs for the independent collection API."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


METADATA_FIELDS = frozenset({
    "session_name", "operator", "source_code", "batch_id", "specimen_id",
    "specimen_confirmed", "camera_setup", "lighting", "background", "conveyor",
    "angle", "provisional_grade", "review_state", "notes", "consent",
})
GRADES = {"A", "B", "C", "Rejected", "Unknown", "Background", "Hard negative"}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetadataInput(Input):
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value):
        if set(value) - METADATA_FIELDS:
            raise ValueError("Unknown capture metadata field.")
        for key, item in value.items():
            if key in {"specimen_confirmed", "consent"}:
                if not isinstance(item, bool):
                    raise ValueError(f"{key} must be a boolean.")
            elif not isinstance(item, str) or len(item) > (4000 if key == "notes" else 256) or "\x00" in item:
                raise ValueError("Capture metadata must be bounded text.")
        if "provisional_grade" in value and value["provisional_grade"] not in GRADES:
            raise ValueError("Invalid provisional operator grade.")
        if "review_state" in value and value["review_state"] not in {"keep", "review", "exclude"}:
            raise ValueError("Invalid review state.")
        if value.get("specimen_confirmed") and not value.get("specimen_id", "").strip():
            raise ValueError("A confirmed specimen needs an explicit specimen ID.")
        return value


class CameraInput(Input):
    device_index: int = Field(default=0, ge=0, le=11, strict=True)
    width: int = Field(default=1920, ge=64, le=4096, strict=True)
    height: int = Field(default=1080, ge=64, le=4096, strict=True)
    backend: Literal["default", "dshow", "msmf", "v4l2"] = "dshow"


class RunInput(Input):
    session_id: str | None = None
    countdown: Literal[0, 5, 10] = 0
    interval: Literal[1, 2, 5] = 1
    duration: Literal[5, 10, 30, 60] | None = None
    target_count: int | None = Field(default=None, ge=1, le=10000, strict=True)


class ItemPatch(MetadataInput):
    item_ids: list[str] = Field(min_length=1, max_length=200)


class DriveSettings(Input):
    auto_sync: bool = Field(strict=True)


class DriveTest(Input):
    write_test: bool = Field(default=False, strict=True)
