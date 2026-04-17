from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar, cast

from support_ope_agents.agents.roles import DEFAULT_AGENT_ROLES
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.runtime.service_support import resolve_ticket_lookup_enabled
from support_ope_agents.tools import ToolRegistry
from support_ope_agents.workflow import WORKFLOW_LABELS
from support_ope_agents.workflow.state import WorkflowKind


class AbstractRuntimeContext(ABC):
	def __init__(
		self,
		config: AppConfig,
		memory_store: CaseMemoryStore,
		runtime_harness_manager: RuntimeHarnessManager,
		instruction_loader: InstructionLoader,
		tool_registry: ToolRegistry,
		case_id_resolver_service: CaseIdResolverService,
	) -> None:
		self.config = config
		self.memory_store = memory_store
		self.runtime_harness_manager = runtime_harness_manager
		self.instruction_loader = instruction_loader
		self.tool_registry = tool_registry
		self.case_id_resolver_service = case_id_resolver_service


ContextT = TypeVar("ContextT", bound=AbstractRuntimeContext)


class AbstractRuntimeService(ABC, Generic[ContextT]):
	def __init__(self, context: ContextT) -> None:
		self._context = context

	@property
	def context(self) -> ContextT:
		return self._context

	def resolve_case_id(
		self,
		*,
		prompt: str | None = None,
		case_id: str | None = None,
		workspace_path: str | None = None,
	) -> str:
		return self._context.case_id_resolver_service.resolve(
			prompt or "",
			explicit_case_id=case_id,
			workspace_path=workspace_path,
		)

	@staticmethod
	def _coerce_workflow_kind(value: object) -> WorkflowKind:
		normalized = str(value or "").strip()
		if normalized in WORKFLOW_LABELS:
			return cast(WorkflowKind, normalized)
		return "ambiguous_case"

	def initialize_case(self, case_id: str, workspace_path: str) -> Path:
		case_paths = self._context.memory_store.initialize_case(case_id, workspace_path=workspace_path)
		for role in DEFAULT_AGENT_ROLES:
			self._context.memory_store.ensure_agent_working_memory(case_id, role, workspace_path=workspace_path)
		return case_paths.root

	def _resolve_ticket_lookup_enabled(
		self,
		*,
		explicit_ticket_id: str | None,
		saved_ticket_id: object,
		saved_lookup_enabled: object,
		ticket_kind: str,
	) -> bool:
		return resolve_ticket_lookup_enabled(
			explicit_ticket_id=explicit_ticket_id,
			saved_ticket_id=saved_ticket_id,
			saved_lookup_enabled=saved_lookup_enabled,
			ticket_kind=ticket_kind,
			case_id_resolver_service=self._context.case_id_resolver_service,
		)

	@abstractmethod
	def _migrate_legacy_traces(self) -> None:
		raise NotImplementedError
