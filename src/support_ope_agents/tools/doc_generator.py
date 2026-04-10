from __future__ import annotations

from collections import Counter
from pathlib import Path

from support_ope_agents.config import load_config
from support_ope_agents.tools.registry import ToolRegistry, ToolSpec


def _role_slug(role: str) -> str:
    chunks: list[str] = []
    current = ""
    for char in role.replace("Agent", ""):
        if char.isupper() and current:
            chunks.append(current.lower())
            current = char
        else:
            current += char
    if current:
        chunks.append(current.lower())
    return "-".join(chunks) or role.lower()


def _implementation_status(tool: ToolSpec) -> str:
    if tool.provider == "builtin":
        return "implemented"
    if tool.provider.startswith("mcp:"):
        return "mcp_override"
    if tool.name in {"external_ticket", "internal_ticket"}:
        return "unavailable_by_default"
    return "planned"


def _render_tool_line(tool: ToolSpec) -> str:
    target = tool.target or "n/a"
    return (
        f"- {tool.name}: {tool.description} "
        f"(provider={tool.provider}, target={target}, status={_implementation_status(tool)}, override=allowed)"
    )


def build_tool_docs_markdown(registry: ToolRegistry, role: str) -> str:
    role_tools = registry.get_tools(role)
    tool_counts = Counter(tool.name for listed_role in registry.list_roles() for tool in registry.get_tools(listed_role))
    common_tools = [tool for tool in role_tools if tool_counts[tool.name] >= 2]
    role_specific_tools = [tool for tool in role_tools if tool_counts[tool.name] < 2]

    lines = [f"# {role} ツール下書き", "", "このファイルは ToolRegistry から半自動生成した下書きです。", ""]
    lines.append("## 共通ツール")
    if common_tools:
        lines.extend(_render_tool_line(tool) for tool in common_tools)
    else:
        lines.append("- なし")

    lines.extend(["", "## role 固有ツール"])
    if role_specific_tools:
        lines.extend(_render_tool_line(tool) for tool in role_specific_tools)
    else:
        lines.append("- なし")

    lines.extend(
        [
            "",
            "## 手編集メモ",
            "- ここに入出力例、運用上の注意、MCP 接続前提などを追記する。",
            "- 既存の docs/tools/*.md を置き換えるのではなく、レビュー用の下書きとして使う。",
        ]
    )
    return "\n".join(lines) + "\n"


def export_tool_docs(config_path: str, output_dir: str | Path) -> list[Path]:
    config = load_config(config_path)
    registry = ToolRegistry(config)
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for role in registry.list_roles():
        output_path = target_dir / f"{_role_slug(role)}-tools.generated.md"
        output_path.write_text(build_tool_docs_markdown(registry, role), encoding="utf-8")
        generated.append(output_path)
    return generated