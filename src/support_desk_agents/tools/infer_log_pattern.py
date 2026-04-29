from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from support_desk_agent.config.models import AppConfig
from support_desk_agent.util.langchain import build_chat_openai_model
from support_desk_agent.instructions import InstructionLoader


class _LogHeaderPatternInference(BaseModel):
    """
    ログ先頭行パターン推定の構造化出力用モデル。
    LLMから返される推定結果を受け取るための型。
    """
    header_pattern: str = Field(default="")
    timestamp_start: int = Field(default=-1)
    timestamp_end: int = Field(default=-1)
    timestamp_format: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


def build_default_infer_log_pattern_tool(config: AppConfig):
    """
    ログファイルの先頭行サンプルから、レコード先頭の正規表現・タイムスタンプ位置・書式を推定するツールを構築。
    指示文(instructions)はInstructionLoader経由で外部化。
    """
    def _infer_log_pattern(*, file_path: str, sample_line_limit: int = 100) -> str:
        """
        指定ファイルの先頭N行サンプルから、LLMでログパターンを推定しJSONで返す。
        :param file_path: ログファイルパス
        :param sample_line_limit: サンプル行数上限
        :return: 推定結果JSON
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File was not found: {path}")


        # ファイルからサンプル行を抽出
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        sample_lines = lines[:sample_line_limit]
        if not sample_lines:
            # サンプルが空ならunavailableで返す
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

        # LLMモデルを初期化し、構造化出力を有効化
        model = build_chat_openai_model(config, temperature=0)
        structured_model = model.with_structured_output(_LogHeaderPatternInference)

        # InstructionLoaderでプロンプトを外部化（instructionsが空なら例外）
        loader = InstructionLoader(config)
        instructions = loader.load(case_id="infer_log_pattern", role="infer_log_pattern")
        if not instructions:
            raise RuntimeError("instructions for infer_log_pattern is not defined.")

        # プロンプトを組み立て
        prompt = (
            f"{instructions}\n\n"
            f"file_path: {path}\n"
            f"sample_line_limit: {sample_line_limit}\n"
            "sample_lines:\n"
            + "\n".join(f"{index + 1:03d}: {line}" for index, line in enumerate(sample_lines))
        )

        # LLMに問い合わせ
        response = structured_model.invoke([
            {"role": "user", "content": prompt}
        ])
        # 構造化出力の型でパース
        if isinstance(response, _LogHeaderPatternInference):
            parsed = response
        elif isinstance(response, dict):
            parsed = _LogHeaderPatternInference.model_validate(response)
        elif hasattr(response, "model_dump"):
            parsed = _LogHeaderPatternInference.model_validate(response.model_dump())
        else:
            raise ValueError("infer_log_header_pattern returned an unsupported structured output payload")

        # 結果をJSONで返す
        payload = {
            "status": "matched" if parsed.header_pattern and parsed.timestamp_start >= 0 and parsed.timestamp_end > parsed.timestamp_start else "unavailable",
            "file_path": str(path),
            "sample_line_limit": sample_line_limit,
            "sample_preview": sample_lines[:10],
            **parsed.model_dump(),
        }
        return json.dumps(payload, ensure_ascii=False)

    return _infer_log_pattern