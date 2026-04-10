from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import LOG_ANALYZER_AGENT, SUPERVISOR_AGENT

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class LogAnalyzerPhaseExecutor:
    detect_log_format_tool: Callable[..., Any]

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
        result = tool(*args)
        if inspect.isawaitable(result):
            try:
                resolved = asyncio.run(result)  # type: ignore[arg-type]
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    resolved = loop.run_until_complete(result)  # type: ignore[arg-type]
                finally:
                    loop.close()
            return str(resolved)
        return str(result)

    @staticmethod
    def _find_log_candidates(workspace_path: str) -> list[Path]:
        root = Path(workspace_path).expanduser().resolve()
        candidates: set[Path] = set()
        for subdir_name in ("evidence", "artifacts"):
            target_dir = root / subdir_name
            if not target_dir.exists():
                continue
            for pattern in ("*.log", "*.txt", "*.out"):
                candidates.update(path.resolve() for path in target_dir.rglob(pattern) if path.is_file())
        return sorted(candidates)

    @staticmethod
    def _build_search_terms(state: "CaseState") -> list[str]:
        raw_issue = str(state.get("raw_issue") or "")
        defaults = ["error", "exception", "failed", "timeout"]
        extracted = [token.strip(".,:[]()") for token in raw_issue.split() if len(token.strip(".,:[]()")) >= 5]
        terms: list[str] = []
        for token in [*defaults, *extracted[:6]]:
            lowered = token.lower()
            if lowered and lowered not in terms:
                terms.append(lowered)
        return terms

    def execute(self, state: "CaseState") -> dict[str, Any]:
        workspace_path = str(state.get("workspace_path") or "").strip()
        if not workspace_path:
            return {"summary": "workspace_path がないためログ解析をスキップしました。", "file": ""}

        candidates = self._find_log_candidates(workspace_path)
        if not candidates:
            return {"summary": "解析対象のログファイルが見つからなかったためログ解析をスキップしました。", "file": ""}

        selected_file = candidates[0]
        raw_result = self._invoke_tool(
            self.detect_log_format_tool,
            str(selected_file),
            self._build_search_terms(state),
        )
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return {
                "summary": f"ログ解析ツールの結果を解釈できませんでした: {raw_result}",
                "file": str(selected_file),
            }

        detected_format = str(parsed.get("detected_format") or "unknown")
        has_java_stacktrace = bool(parsed.get("has_java_stacktrace"))
        search_results = parsed.get("search_results") if isinstance(parsed.get("search_results"), dict) else {}
        severity_count = len(search_results.get("severity") or [])
        exception_count = len(search_results.get("java_exception") or [])
        summary = (
            f"{selected_file.name} を解析し、形式は {detected_format} と判定しました。"
            f"severity 一致 {severity_count} 件、例外一致 {exception_count} 件"
        )
        summary += "、Java スタックトレースを検出しました。" if has_java_stacktrace else "。"
        return {
            "summary": summary,
            "file": str(selected_file),
            "detected_format": detected_format,
            "has_java_stacktrace": has_java_stacktrace,
            "generated_patterns": parsed.get("generated_patterns") or {},
            "search_results": search_results,
        }


def build_log_analyzer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        LOG_ANALYZER_AGENT,
        "Analyze technical logs",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )