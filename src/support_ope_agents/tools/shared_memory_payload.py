from __future__ import annotations

from typing import Literal, TypedDict


MemoryWriteMode = Literal["replace", "append"]


class SharedMemorySectionPayload(TypedDict, total=False):
    title: str
    summary: str
    bullets: list[str]


class SharedMemoryDocumentPayload(TypedDict, total=False):
    title: str
    heading_level: int
    summary: str
    bullets: list[str]
    sections: list[SharedMemorySectionPayload]