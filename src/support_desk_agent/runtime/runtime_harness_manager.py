from __future__ import annotations

from typing import Literal, Mapping, TypedDict

from support_desk_agent.agents.roles import (
    DEFAULT_AGENT_ROLES,
    DRAFT_WRITER_AGENT,
    INTAKE_AGENT,
    INVESTIGATE_AGENT,
    KNOWLEDGE_RETRIEVER_AGENT,
    SUPERVISOR_AGENT,
)
from support_desk_agent.config.models import AppConfig


ConstraintCapability = Literal["instruction", "runtime", "summary"]


class RuntimeConstraintResolution(TypedDict):
    role: str
    constraint_mode: str
    instruction_enabled: bool
    runtime_enabled: bool
    summary_constraints_enabled: bool
    policies: list["RuntimePolicyValue"]


class RuntimePolicyValue(TypedDict):
    policy_id: str
    value: object
    source: str
    applies_when: str
    effect_summary: str


class RuntimePolicySnapshot(TypedDict):
    global_policies: list[RuntimePolicyValue]
    role_policies: list[RuntimeConstraintResolution]


class RuntimePolicyImpact(TypedDict):
    owner: str
    policy_id: str
    value: object
    impact_level: str
    effect_summary: str
    observable_output: str


class RuntimeHarnessManager:
    _WORKSPACE_PREVIEW_MAX_CHARS = 16000
    _CONTROL_CATALOG_INSTRUCTION_EXCERPT_MAX_CHARS = 160
    _KNOWLEDGE_HIGHLIGHT_MAX_CHARS: int | None = None
    _DRAFT_SNIPPET_MAX_CHARS = 1200
    _DRAFT_FEATURE_BULLET_MAX_ITEMS = 5
    _DRAFT_EXCEPTION_NAME_MAX_ITEMS = 3
    _SUPERVISOR_REVIEW_EXCERPT_MAX_CHARS: int | None = None

    def __init__(self, config: AppConfig):
        self.config = config

    @staticmethod
    def _coerce_int(value: object, default: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @staticmethod
    def instructions_enabled_for_mode(constraint_mode: str) -> bool:
        return constraint_mode not in {"runtime_only", "bypass"}

    @staticmethod
    def runtime_constraints_enabled_for_mode(constraint_mode: str) -> bool:
        return constraint_mode in {"default", "runtime_only"}

    @staticmethod
    def summary_constraints_enabled_for_mode(constraint_mode: str) -> bool:
        return constraint_mode not in {"bypass", "instruction_only"}

    def resolve(self, role: str) -> str:
        return self.config.agents.resolve_constraint_mode(role)

    def should_load_instructions(self, role: str) -> bool:
        # Runtime constraint: instruction loading is disabled for runtime_only and bypass.
        return self.instructions_enabled_for_mode(self.resolve(role))

    def should_apply_runtime_constraints(self, role: str) -> bool:
        # Runtime constraint: runtime guards are active only for default and runtime_only.
        return self.runtime_constraints_enabled_for_mode(self.resolve(role))

    def should_use_summary_constraints(self, role: str) -> bool:
        # Runtime constraint: summary shaping is disabled for bypass and instruction_only.
        return self.summary_constraints_enabled_for_mode(self.resolve(role))

    def is_enabled(self, role: str, capability: ConstraintCapability) -> bool:
        if capability == "instruction":
            return self.should_load_instructions(role)
        if capability == "runtime":
            return self.should_apply_runtime_constraints(role)
        return self.should_use_summary_constraints(role)

    @staticmethod
    def _policy(
        policy_id: str,
        value: object,
        *,
        source: str,
        applies_when: str,
        effect_summary: str,
    ) -> RuntimePolicyValue:
        return {
            "policy_id": policy_id,
            "value": value,
            "source": source,
            "applies_when": applies_when,
            "effect_summary": effect_summary,
        }

    def get_global_policies(self) -> list[RuntimePolicyValue]:
        return [
            self._policy(
                "workflow.max_context_chars",
                self.config.workflow.max_context_chars,
                source="config.workflow.max_context_chars",
                applies_when="workflow compression and context shaping",
                effect_summary="working context is compacted once the accumulated case context reaches this size",
            ),
            self._policy(
                "workflow.compress_threshold_chars",
                self.config.workflow.compress_threshold_chars,
                source="config.workflow.compress_threshold_chars",
                applies_when="workflow compression pre-check",
                effect_summary="context compression is considered when the case state exceeds this threshold",
            ),
            self._policy(
                "workflow.max_summary_chars",
                self.config.workflow.max_summary_chars,
                source="config.workflow.max_summary_chars",
                applies_when="workflow summary generation",
                effect_summary="workflow-generated summaries are bounded by this character budget",
            ),
            self._policy(
                "runtime.workspace_preview_max_chars",
                self._WORKSPACE_PREVIEW_MAX_CHARS,
                source="runtime.service.get_workspace_file default",
                applies_when="workspace file preview API",
                effect_summary="workspace text previews are truncated beyond this size and returned with truncated=true",
            ),
            self._policy(
                "runtime.control_catalog.instruction_excerpt_max_chars",
                self._CONTROL_CATALOG_INSTRUCTION_EXCERPT_MAX_CHARS,
                source="runtime.production.control_catalog._instruction_excerpt",
                applies_when="control catalog and audit excerpt rendering",
                effect_summary="instruction excerpts shown in audit and reports are shortened to this size",
            ),
        ]

    def get_role_policies(self, role: str) -> list[RuntimePolicyValue]:
        if role in {INVESTIGATE_AGENT, KNOWLEDGE_RETRIEVER_AGENT}:
            return [
                self._policy(
                    "knowledge.highlight_max_chars",
                    self._KNOWLEDGE_HIGHLIGHT_MAX_CHARS,
                    source="agents.knowledge_retriever_agent._build_document_highlight",
                    applies_when="document highlights are emitted into summaries",
                    effect_summary="when set, knowledge highlights are truncated to the configured limit; disabled by default",
                )
            ]
        if role == DRAFT_WRITER_AGENT:
            return [
                self._policy(
                    "draft.summary_snippet_max_chars",
                    self._DRAFT_SNIPPET_MAX_CHARS,
                    source="agents.draft_writer_agent._summary_from_result",
                    applies_when="raw backend content is converted into a customer-facing summary",
                    effect_summary="draft summaries extracted from raw content are bounded to 1200 characters",
                ),
                self._policy(
                    "draft.feature_bullet_max_items",
                    self._DRAFT_FEATURE_BULLET_MAX_ITEMS,
                    source="agents.draft_writer_agent._feature_bullets_from_result",
                    applies_when="feature bullets are extracted or rendered",
                    effect_summary="draft feature bullet lists are limited to 5 items",
                ),
                self._policy(
                    "draft.exception_name_max_items",
                    self._DRAFT_EXCEPTION_NAME_MAX_ITEMS,
                    source="agents.draft_writer_agent._extract_exception_names",
                    applies_when="exception names are summarized from investigation text",
                    effect_summary="at most 3 exception names are surfaced in the generated draft context",
                ),
            ]
        if role == SUPERVISOR_AGENT:
            return [
                self._policy(
                    "supervisor.max_investigation_loops",
                    self.config.agents.SuperVisorAgent.max_investigation_loops,
                    source="config.agents.SuperVisorAgent.max_investigation_loops",
                    applies_when="investigation follow-up loop",
                    effect_summary="supervisor follow-up investigation runs are capped at this count",
                ),
                self._policy(
                    "supervisor.review_excerpt_max_chars",
                    self._SUPERVISOR_REVIEW_EXCERPT_MAX_CHARS,
                    source="agents.supervisor_agent._summarize_text",
                    applies_when="compliance history and draft excerpts are summarized",
                    effect_summary="when set, supervisor review excerpts are shortened to the configured limit; disabled by default",
                ),
            ]
        if role == INTAKE_AGENT:
            return [
                self._policy(
                    "intake.pii_mask_enabled",
                    self.config.agents.IntakeAgent.pii_mask.enabled,
                    source="config.agents.IntakeAgent.pii_mask.enabled",
                    applies_when="intake masking phase",
                    effect_summary="customer input is masked before classification when PII masking is enabled",
                )
            ]
        return []

    def get_policy_value(self, policy_id: str, *, role: str | None = None, default: object = None) -> object:
        policies = self.get_role_policies(role) if role is not None else self.get_global_policies()
        for policy in policies:
            if policy["policy_id"] == policy_id:
                return policy["value"]
        return default

    def get_int_policy_value(self, policy_id: str, *, role: str | None = None, default: int) -> int:
        return self._coerce_int(self.get_policy_value(policy_id, role=role, default=default), default=default)

    def get_optional_int_policy_value(self, policy_id: str, *, role: str | None = None) -> int | None:
        value = self.get_policy_value(policy_id, role=role, default=None)
        if value is None:
            return None
        return self._coerce_int(value, default=0)

    def build_policy_snapshot(self, roles: list[str] | None = None) -> RuntimePolicySnapshot:
        selected_roles = roles or list(DEFAULT_AGENT_ROLES)
        return {
            "global_policies": self.get_global_policies(),
            "role_policies": [self.describe_role(role) for role in selected_roles],
        }

    def evaluate_policy_impacts(self, roles: list[str], state: Mapping[str, object]) -> list[RuntimePolicyImpact]:
        impacts: list[RuntimePolicyImpact] = []
        draft_review_iterations = self._coerce_int(state.get("draft_review_iterations"), default=0)
        draft_review_max_loops = self._coerce_int(state.get("draft_review_max_loops"), default=0)

        for policy in self.get_global_policies():
            impacts.append(
                {
                    "owner": "global",
                    "policy_id": policy["policy_id"],
                    "value": policy["value"],
                    "impact_level": "configured",
                    "effect_summary": str(policy["effect_summary"]),
                    "observable_output": "trace does not record direct usage for this global policy",
                }
            )

        for role in roles:
            for policy in self.get_role_policies(role):
                impact_level = "configured"
                observable_output = "trace does not record direct usage for this policy"

                if policy["policy_id"] == "supervisor.max_investigation_loops" and draft_review_max_loops:
                    impact_level = "observed"
                    observable_output = f"draft review iterations={draft_review_iterations}/{draft_review_max_loops}"
                elif policy["value"] is None:
                    impact_level = "disabled"
                    observable_output = "policy value is null; truncation is disabled by default"

                impacts.append(
                    {
                        "owner": role,
                        "policy_id": policy["policy_id"],
                        "value": policy["value"],
                        "impact_level": impact_level,
                        "effect_summary": str(policy["effect_summary"]),
                        "observable_output": observable_output,
                    }
                )

        return impacts

    def describe_role(self, role: str) -> RuntimeConstraintResolution:
        return {
            "role": role,
            "constraint_mode": self.resolve(role),
            "instruction_enabled": self.should_load_instructions(role),
            "runtime_enabled": self.should_apply_runtime_constraints(role),
            "summary_constraints_enabled": self.should_use_summary_constraints(role),
            "policies": self.get_role_policies(role),
        }

    def describe_roles(self, roles: list[str]) -> list[RuntimeConstraintResolution]:
        return [self.describe_role(role) for role in roles]