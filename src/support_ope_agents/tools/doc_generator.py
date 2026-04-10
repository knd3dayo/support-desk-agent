from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from support_ope_agents.config import load_config
from support_ope_agents.tools.registry import ToolRegistry, ToolSpec


def _implementation_status(tool: ToolSpec) -> str:
    if tool.provider == "builtin":
        return "implemented"
    if tool.provider.startswith("mcp:"):
        return "mcp_override"
    if tool.name in {"external_ticket", "internal_ticket"}:
        return "unavailable_by_default"
    return "planned"


def _tool_doc_filename(tool_name: str) -> str:
    return f"{tool_name}.generated.md"


def _collect_tools_by_name(registry: ToolRegistry) -> dict[str, list[tuple[str, ToolSpec]]]:
    tools_by_name: dict[str, list[tuple[str, ToolSpec]]] = defaultdict(list)
    for role in registry.list_roles():
        for tool in registry.get_tools(role):
            tools_by_name[tool.name].append((role, tool))
    return dict(sorted(tools_by_name.items()))


def build_tool_docs_markdown(tool_name: str, role_bindings: list[tuple[str, ToolSpec]]) -> str:
    canonical_tool = role_bindings[0][1]
    lines = [f"# {tool_name} ツール下書き", "", "このファイルは ToolRegistry から半自動生成した下書きです。", ""]
    lines.extend(["## 概要", f"- description: {canonical_tool.description}"])
    lines.extend(["", "## 利用エージェント"])
    for role, tool in role_bindings:
        target = tool.target or "n/a"
        lines.append(
            f"- {role}: provider={tool.provider}, target={target}, status={_implementation_status(tool)}, override=allowed"
        )

    lines.extend(
        [
            "",
            "## 手編集メモ",
            "- ここに入出力例、運用上の注意、MCP 接続前提などを追記する。",
            "- docs/tools/specs/*.md の更新時に差分確認用の下書きとして使う。",
        ]
    )
    return "\n".join(lines) + "\n"


def export_tool_docs(config_path: str, output_dir: str | Path) -> list[Path]:
    config = load_config(config_path)
    registry = ToolRegistry(config)
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    tool_bindings = _collect_tools_by_name(registry)
    generated: list[Path] = []
    for stale_path in target_dir.glob("*.generated.md"):
        stale_path.unlink()

    for tool_name, role_bindings in tool_bindings.items():
        output_path = target_dir / _tool_doc_filename(tool_name)
        output_path.write_text(build_tool_docs_markdown(tool_name, role_bindings), encoding="utf-8")
        generated.append(output_path)
    return generated