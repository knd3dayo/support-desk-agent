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


def load_config(config_path: str | Path) -> AppConfig:
    load_dotenv()
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    section = raw.get(ROOT_KEY, {})
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
    manifest_path = tools.get("mcp_manifest_path")
    if manifest_path:
        tools["mcp_manifest_path"] = _resolve_path(base_dir, manifest_path)
    resolved["tools"] = tools

    return AppConfig.model_validate(resolved)