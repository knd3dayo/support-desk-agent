from __future__ import annotations

from .agent_definition import AgentDefinition
from .roles import DEFAULT_AGENT_ROLES

__all__ = ["AgentDefinition", "DEFAULT_AGENT_ROLES", "build_default_agent_definitions"]


def build_default_agent_definitions():
	from .catalog import build_default_agent_definitions as _build_default_agent_definitions

	return _build_default_agent_definitions()


def __getattr__(name: str):
	if name == "build_default_agent_definitions":
		return build_default_agent_definitions
	raise AttributeError(name)