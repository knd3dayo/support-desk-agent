from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, MutableMapping

from pydantic import BaseModel, Field

from support_desk_agent.config.models import AppConfig
from support_desk_agent.util.langchain import build_chat_openai_model


_FULL_DATETIME_PATTERN = r"\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?"
_DATE_ONLY_PATTERN = r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
_TIME_ONLY_PATTERN = r"\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?"
_RELATIVE_TIME_MARKERS = ("今日", "昨日", "一昨日", "今朝", "昨夜", "本日", "午前", "午後", "深夜", "夕方", "朝方")
_UNKNOWN_TIME_MARKERS = ("不明", "わから", "未確認", "unknown", "n/a")


class _InferredLogTimeRange(BaseModel):
    range_start: str = Field(default="")
    range_end: str = Field(default="")
    reason: str = Field(default="")


def _parse_datetime_text(value: str) -> datetime | None:
    normalized = value.strip().replace("/", "-").replace(",", ".")
    if not normalized:
        return None
    candidates = (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    )
    for candidate in candidates:
        try:
            return datetime.strptime(normalized, candidate)
        except ValueError:
            continue
    return None


def _to_iso_seconds(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def _should_infer_with_llm(text: str) -> bool:
    lowered = text.lower()
    if any(marker in text for marker in _UNKNOWN_TIME_MARKERS) or any(marker in lowered for marker in _UNKNOWN_TIME_MARKERS):
        return False
    if re.search(_FULL_DATETIME_PATTERN, text) or re.search(_DATE_ONLY_PATTERN, text) or re.search(_TIME_ONLY_PATTERN, text):
        return False
    return any(marker in text for marker in _RELATIVE_TIME_MARKERS)


def _infer_log_extract_range_with_llm(
    timeframe_text: str,
    *,
    config: AppConfig,
    reference_datetime: datetime | None = None,
) -> tuple[str, str] | None:
    now = reference_datetime or datetime.now()
    model = build_chat_openai_model(config)
    structured_model = model.with_structured_output(_InferredLogTimeRange)
    response = structured_model.invoke(
        [
            {
                "role": "user",
                "content": (
                    "あなたはログ抽出用の時間帯正規化ツールです。\n"
                    "問い合わせ文中の障害発生時間帯を、ログ抽出に使える ISO8601 の開始時刻と終了時刻へ正規化してください。\n"
                    "ルール:\n"
                    "- range_start と range_end は秒まで含むローカル時刻の ISO8601 形式にする\n"
                    "- 曖昧表現でも、文脈から妥当な時間帯へ補完する\n"
                    "- 明確に決められない場合は空文字を返す\n"
                    "- 返答は構造化結果のみ\n\n"
                    f"reference_datetime: {now.isoformat(timespec='seconds')}\n"
                    f"timeframe_text: {timeframe_text}\n"
                ),
            }
        ]
    )
    if isinstance(response, _InferredLogTimeRange):
        parsed = response
    elif isinstance(response, dict):
        parsed = _InferredLogTimeRange.model_validate(response)
    elif hasattr(response, "model_dump"):
        parsed = _InferredLogTimeRange.model_validate(response.model_dump())
    else:
        raise ValueError("LLM time range inference returned an unsupported structured output payload")

    start = _parse_datetime_text(parsed.range_start)
    end = _parse_datetime_text(parsed.range_end)
    if start is None or end is None or start > end:
        return None
    return _to_iso_seconds(start), _to_iso_seconds(end)


def derive_log_extract_range_from_timeframe(
    timeframe_text: str,
    *,
    config: AppConfig | None = None,
    reference_datetime: datetime | None = None,
    default_window_minutes: int = 15,
) -> tuple[str, str] | None:
    text = str(timeframe_text or "").strip()
    if not text:
        return None

    full_range_match = re.search(
        rf"(?P<start>{_FULL_DATETIME_PATTERN})\s*(?:〜|~|から|to|-)\s*(?P<end>{_FULL_DATETIME_PATTERN})",
        text,
    )
    if full_range_match:
        start_dt = _parse_datetime_text(full_range_match.group("start"))
        end_dt = _parse_datetime_text(full_range_match.group("end"))
        if start_dt is not None and end_dt is not None and start_dt <= end_dt:
            return _to_iso_seconds(start_dt), _to_iso_seconds(end_dt)

    same_day_range_match = re.search(
        rf"(?P<date>{_DATE_ONLY_PATTERN}).*?(?P<start>{_TIME_ONLY_PATTERN})\s*(?:〜|~|から|to|-)\s*(?P<end>{_TIME_ONLY_PATTERN})",
        text,
    )
    if same_day_range_match:
        date_text = same_day_range_match.group("date").replace("/", "-")
        start_dt = _parse_datetime_text(f"{date_text} {same_day_range_match.group('start')}")
        end_dt = _parse_datetime_text(f"{date_text} {same_day_range_match.group('end')}")
        if start_dt is not None and end_dt is not None and start_dt <= end_dt:
            return _to_iso_seconds(start_dt), _to_iso_seconds(end_dt)

    full_match = re.search(_FULL_DATETIME_PATTERN, text)
    if full_match:
        center = _parse_datetime_text(full_match.group(0))
        if center is not None:
            delta = timedelta(minutes=default_window_minutes)
            return _to_iso_seconds(center - delta), _to_iso_seconds(center + delta)

    date_only_match = re.search(_DATE_ONLY_PATTERN, text)
    if date_only_match:
        day = _parse_datetime_text(date_only_match.group(0))
        if day is not None:
            return _to_iso_seconds(day), _to_iso_seconds(day + timedelta(days=1) - timedelta(seconds=1))

    if config is not None and _should_infer_with_llm(text):
        return _infer_log_extract_range_with_llm(text, config=config, reference_datetime=reference_datetime)

    return None


def apply_derived_log_extract_range(
    state: MutableMapping[str, Any],
    timeframe_text: str,
    *,
    config: AppConfig | None = None,
    reference_datetime: datetime | None = None,
) -> None:
    if str(state.get("log_extract_range_start") or "").strip() and str(state.get("log_extract_range_end") or "").strip():
        return
    derived = derive_log_extract_range_from_timeframe(
        timeframe_text,
        config=config,
        reference_datetime=reference_datetime,
    )
    if derived is None:
        return
    state["log_extract_range_start"], state["log_extract_range_end"] = derived