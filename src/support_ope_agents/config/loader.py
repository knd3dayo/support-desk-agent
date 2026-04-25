from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml

from .models import AppConfig

ROOT_KEY = "support_ope_agents"
ENV_REF_PREFIX = "os.environ/"
LLM_MODEL_OVERRIDE_ENV = "SUPPORT_OPE_LLM_MODEL"
LLM_BASE_URL_OVERRIDE_ENV = "SUPPORT_OPE_LLM_BASE_URL"


def _resolve_env_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_refs(item) for item in value]
    if isinstance(value, str) and value.startswith(ENV_REF_PREFIX):
        env_name = value.removeprefix(ENV_REF_PREFIX)
        return os.getenv(env_name, "")
    return value


def _resolve_path(base_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _migrate_legacy_ticket_sources(tools: dict[str, Any]) -> dict[str, Any]:
    ticket_sources = tools.pop("ticket_sources", None)
    if not isinstance(ticket_sources, dict):
        return tools

    logical_tools = tools.get("logical_tools")
    if not isinstance(logical_tools, dict):
        logical_tools = {}
        tools["logical_tools"] = logical_tools

    for ticket_kind in ("external", "internal"):
        binding = ticket_sources.get(ticket_kind)
        if not isinstance(binding, dict):
            continue
        logical_tool_name = f"{ticket_kind}_ticket"
        if logical_tool_name in logical_tools:
            continue

        enabled = bool(binding.get("enabled"))
        server = str(binding.get("server") or "").strip()
        migrated: dict[str, Any] = {
            "enabled": enabled,
            "provider": "mcp",
            "description": str(binding.get("description") or ""),
        }
        if server:
            migrated["server"] = server
        arguments = binding.get("arguments")
        if isinstance(arguments, dict):
            migrated["arguments"] = arguments
        candidate_matching = binding.get("candidate_matching")
        if isinstance(candidate_matching, dict):
            migrated["candidate_matching"] = candidate_matching
        logical_tools[logical_tool_name] = migrated

    return tools


def load_config(config_path: str | Path) -> AppConfig:
    load_dotenv()
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if ROOT_KEY not in raw:
        available_keys = ", ".join(sorted(str(key) for key in raw.keys())) if isinstance(raw, dict) and raw else "<empty>"
        raise ValueError(
            f"config root '{ROOT_KEY}' is required in {path}. available_top_level_keys=[{available_keys}]"
        )

    section = raw.get(ROOT_KEY, {})
    if not isinstance(section, dict):
        raise ValueError(f"config root '{ROOT_KEY}' in {path} must be a mapping")

    resolved = _resolve_env_refs(section)
    base_dir = path.parent

    llm = resolved.get("llm", {})
    model_override = os.getenv(LLM_MODEL_OVERRIDE_ENV)
    if model_override:
        llm["model"] = model_override
    if LLM_BASE_URL_OVERRIDE_ENV in os.environ:
        llm["base_url"] = os.getenv(LLM_BASE_URL_OVERRIDE_ENV) or None
    resolved["llm"] = llm

    config_paths = resolved.get("config_paths", {})
    if config_paths.get("instructions_path"):
        config_paths["instructions_path"] = _resolve_path(base_dir, config_paths["instructions_path"])
    resolved["config_paths"] = config_paths

    resolved["data_paths"] = resolved.get("data_paths", {})
    resolved["runtime"] = resolved.get("runtime", {})

    agents = resolved.get("agents", {})
    investigate = agents.get("InvestigateAgent", {})
    knowledge_retriever = agents.get("KnowledgeRetrieverAgent", {})
    if not investigate and knowledge_retriever:
        investigate = dict(knowledge_retriever)
    document_sources = investigate.get("document_sources", [])
    for source in document_sources:
        if isinstance(source, dict) and source.get("path"):
            source["path"] = _resolve_path(base_dir, source["path"])
    agents["InvestigateAgent"] = investigate
    agents["KnowledgeRetrieverAgent"] = knowledge_retriever
    resolved["agents"] = agents

    tools = resolved.get("tools", {})
    tools = _migrate_legacy_ticket_sources(tools)
    manifest_path = tools.get("mcp_manifest_path")
    if manifest_path:
        tools["mcp_manifest_path"] = _resolve_path(base_dir, manifest_path)
    resolved["tools"] = tools

    return AppConfig.model_validate(resolved)