from __future__ import annotations

from typing import TYPE_CHECKING

from .case_id_resolver import CaseIdResolverService

if TYPE_CHECKING:
	from .service import RuntimeContext, RuntimeService

__all__ = ["CaseIdResolverService", "RuntimeContext", "RuntimeService", "build_runtime_context"]


def build_runtime_context(*args, **kwargs):
	from .service import build_runtime_context as _build_runtime_context

	return _build_runtime_context(*args, **kwargs)


def __getattr__(name: str):
	if name in {"RuntimeContext", "RuntimeService", "build_runtime_context"}:
		from .service import RuntimeContext, RuntimeService, build_runtime_context

		exports = {
			"RuntimeContext": RuntimeContext,
			"RuntimeService": RuntimeService,
			"build_runtime_context": build_runtime_context,
		}
		return exports[name]
	raise AttributeError(name)