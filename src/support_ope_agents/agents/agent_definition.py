from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    role: str
    description: str
    kind: str = "agent"
    parent_role: str | None = None