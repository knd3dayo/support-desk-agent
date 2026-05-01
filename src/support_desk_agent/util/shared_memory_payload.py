from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


MemoryWriteMode = Literal["replace", "append"]


class SharedMemorySectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    summary: str | None = None
    bullets: list[str] | None = None


class SharedMemoryDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    heading_level: int | None = None
    summary: str | None = None
    bullets: list[str] | None = None
    sections: list[SharedMemorySectionPayload] | None = None