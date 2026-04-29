from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from support_desk_agent.config.loader import load_config

if TYPE_CHECKING:
	from .abstract_service import AbstractRuntimeService


def _resolve_runtime_mode(config_path: str | Path) -> str:
	return load_config(config_path).runtime.mode


__all__ = ["build_runtime_service"]


def build_runtime_service(config_path: str | Path = "config.yml") -> AbstractRuntimeService[Any]:
	mode = _resolve_runtime_mode(config_path)
	if mode == "sample":
		from .sample.sample_service import SampleRuntimeService, build_runtime_context as build_sample_runtime_context

		return SampleRuntimeService(build_sample_runtime_context(str(config_path)))
	from .production.production_service import ProductionRuntimeService, build_runtime_context as build_production_runtime_context

	return ProductionRuntimeService(build_production_runtime_context(str(config_path)))