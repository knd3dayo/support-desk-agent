from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from support_ope_agents.config.loader import load_config
from .abstract_service import AbstractRuntimeContext
from .case_id_resolver import CaseIdResolverService


def _resolve_runtime_mode(config_path: str | Path) -> str:
	return load_config(config_path).runtime.mode


def _resolve_runtime_exports(config_path: str | Path):
	mode = _resolve_runtime_mode(config_path)
	if mode == "sample":
		from .sample.sample_service import SampleRuntimeContext, SampleRuntimeService, build_runtime_context

		return SampleRuntimeContext, SampleRuntimeService, build_runtime_context
	from .production.production_service import ProductionRuntimeContext, ProductionRuntimeService, build_runtime_context

	return ProductionRuntimeContext, ProductionRuntimeService, build_runtime_context

__all__ = ["CaseIdResolverService", "RuntimeContext", "RuntimeService", "build_runtime_context"]

RuntimeContext = AbstractRuntimeContext


def build_runtime_context(config_path: str | Path = "config.yml"):
	_, _, runtime_build_context = _resolve_runtime_exports(config_path)
	return runtime_build_context(str(config_path))


class RuntimeService:
	def __init__(self, context: AbstractRuntimeContext):
		module_name = type(context).__module__
		if module_name.startswith("support_ope_agents.runtime.sample"):
			from .sample.sample_service import SampleRuntimeContext, SampleRuntimeService

			self._impl = SampleRuntimeService(cast(SampleRuntimeContext, context))
			return
		if module_name.startswith("support_ope_agents.runtime.production"):
			from .production.production_service import ProductionRuntimeContext, ProductionRuntimeService

			self._impl = ProductionRuntimeService(cast(ProductionRuntimeContext, context))
			return
		raise TypeError(f"Unsupported runtime context type: {type(context)!r}")

	@property
	def context(self) -> AbstractRuntimeContext:
		return self._impl.context

	def __getattr__(self, name: str) -> Any:
		return getattr(self._impl, name)


def __getattr__(name: str):
	if name in {"RuntimeContext", "RuntimeService", "build_runtime_context"}:
		exports = {
			"RuntimeContext": RuntimeContext,
			"RuntimeService": RuntimeService,
			"build_runtime_context": build_runtime_context,
		}
		return exports[name]
	raise AttributeError(name)