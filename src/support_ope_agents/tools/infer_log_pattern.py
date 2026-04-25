from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.instructions import InstructionLoader


class _LogHeaderPatternInference(BaseModel):
    header_pattern: str = Field(default="")
    timestamp_start: int = Field(default=-1)
    timestamp_end: int = Field(default=-1)
    timestamp_format: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


def build_default_infer_log_pattern_tool(config: AppConfig):
    def _infer_log_pattern(*, file_path: str, sample_line_limit: int = 100) -> str:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File was not found: {path}")

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        sample_lines = lines[:sample_line_limit]
        if not sample_lines:
            payload = {
                "status": "unavailable",
                "file_path": str(path),
                "sample_line_limit": sample_line_limit,
                "sample_preview": [],
                "header_pattern": "",
                "timestamp_start": -1,
                "timestamp_end": -1,
                "timestamp_format": "",
                "confidence": 0.0,
                "reason": "ログファイルが空です。",
            }
            return json.dumps(payload, ensure_ascii=False)

        model = build_chat_openai_model(config, temperature=0)
        structured_model = model.with_structured_output(_LogHeaderPatternInference)

        # InstructionLoaderでプロンプトを外部化（instructionsが空なら例外）
        loader = InstructionLoader(config)
        instructions = loader.load(case_id="infer_log_pattern", role="infer_log_pattern")
        if not instructions:
            raise RuntimeError("instructions for infer_log_pattern is not defined.")

        prompt = (
            f"{instructions}\n\n"
            f"file_path: {path}\n"
            f"sample_line_limit: {sample_line_limit}\n"
            "sample_lines:\n"
            + "\n".join(f"{index + 1:03d}: {line}" for index, line in enumerate(sample_lines))
        )

        response = structured_model.invoke([
            {"role": "user", "content": prompt}
        ])
        if isinstance(response, _LogHeaderPatternInference):
            parsed = response
        elif isinstance(response, dict):
            parsed = _LogHeaderPatternInference.model_validate(response)
        elif hasattr(response, "model_dump"):
            parsed = _LogHeaderPatternInference.model_validate(response.model_dump())
        else:
            raise ValueError("infer_log_header_pattern returned an unsupported structured output payload")

        payload = {
            "status": "matched" if parsed.header_pattern and parsed.timestamp_start >= 0 and parsed.timestamp_end > parsed.timestamp_start else "unavailable",
            "file_path": str(path),
            "sample_line_limit": sample_line_limit,
            "sample_preview": sample_lines[:10],
            **parsed.model_dump(),
        }
        return json.dumps(payload, ensure_ascii=False)

    return _infer_log_pattern