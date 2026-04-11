from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import LOG_ANALYZER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class LogAnalyzerPhaseExecutor:
    detect_log_format_tool: Callable[..., Any]
    write_working_memory_tool: Callable[..., Any] | None = None

    _LOG_PRIORITY = {".log": 0, ".out": 1, ".txt": 2}

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
        result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(result)  # type: ignore[arg-type]
            return str(resolved)
        return str(result)

    @staticmethod
    def _expand_artifact_path(path_text: str) -> list[Path]:
        path = Path(path_text).expanduser().resolve()
        if path.is_file():
            return [path]
        if path.is_dir():
            return [child.resolve() for child in path.rglob("*") if child.is_file()]
        return []

    @classmethod
    def _find_log_candidates(cls, workspace_path: str, prioritized_paths: list[str] | None = None) -> list[Path]:
        root = Path(workspace_path).expanduser().resolve()
        preferred: list[Path] = []
        if prioritized_paths:
            for path_text in prioritized_paths:
                for path in cls._expand_artifact_path(path_text):
                    if path.suffix.lower() in {".log", ".txt", ".out"}:
                        preferred.append(path)
            preferred.sort(key=lambda path: (cls._LOG_PRIORITY.get(path.suffix.lower(), 99), str(path)))

        candidates: set[Path] = set(preferred)
        for subdir_name in (".evidence", ".artifacts", "evidence", "artifacts"):
            target_dir = root / subdir_name
            if not target_dir.exists():
                continue
            for pattern in ("*.log", "*.txt", "*.out"):
                candidates.update(path.resolve() for path in target_dir.rglob(pattern) if path.is_file())

        ordered: list[Path] = []
        seen: set[Path] = set()
        for path in preferred + sorted(candidates):
            if path in seen:
                continue
            ordered.append(path)
            seen.add(path)
        return ordered

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
        case_id = str(state.get("case_id") or "").strip()
        if not workspace_path:
            return {"summary": "workspace_path がないためログ解析をスキップしました。", "file": ""}

        prioritized_paths: list[str] = []
        ticket_artifacts = state.get("intake_ticket_artifacts")
        if isinstance(ticket_artifacts, dict):
            for paths in ticket_artifacts.values():
                if isinstance(paths, list):
                    prioritized_paths.extend(str(item) for item in paths if str(item).strip())

        candidates = self._find_log_candidates(workspace_path, prioritized_paths=prioritized_paths)
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
        if self.write_working_memory_tool is not None and case_id and workspace_path:
            payload: SharedMemoryDocumentPayload = {
                "title": "Log Analysis Result",
                "heading_level": 2,
                "bullets": [
                    f"File: {selected_file}",
                    f"Detected format: {detected_format}",
                    f"Summary: {summary}",
                ],
            }
            self._invoke_tool(self.write_working_memory_tool, case_id, workspace_path, payload, "append")
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