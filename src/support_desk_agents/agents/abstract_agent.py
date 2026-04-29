from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from support_desk_agent.agents.agent_definition import AgentDefinition


class AbstractAgent(ABC):
    @abstractmethod
    def create_node(self) -> Any:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def build_agent_definition(cls) -> AgentDefinition:
        raise NotImplementedError