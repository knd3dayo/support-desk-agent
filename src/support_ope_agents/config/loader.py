from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml

from .models import AppConfig

ROOT_KEY = "support_ope_agents"
ENV_REF_PREFIX = "os.environ/"


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

    config_paths = resolved.get("config_paths", {})
    if config_paths.get("instructions_path"):
        config_paths["instructions_path"] = _resolve_path(base_dir, config_paths["instructions_path"])
    resolved["config_paths"] = config_paths

    resolved["data_paths"] = resolved.get("data_paths", {})

    tools = resolved.get("tools", {})
    manifest_path = tools.get("mcp_manifest_path")
    if manifest_path:
        tools["mcp_manifest_path"] = _resolve_path(base_dir, manifest_path)
    resolved["tools"] = tools

    return AppConfig.model_validate(resolved)