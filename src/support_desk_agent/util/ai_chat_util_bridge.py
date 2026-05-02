from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ai_chat_util.core.analysis.analyze_util import AnalyzeImageUtil, AnalyzeLogUtil, AnalyzeOfficeUtil, AnalyzePDFUtil
from ai_chat_util.core.chat import create_llm_client
from ai_chat_util.core.chat.model import ChatResponse
from ai_chat_util.core.common.config.runtime import AiChatUtilConfig
from ai_chat_util.core.analysis.model import ExtractLogTimeRangeData, InferLogFormatData
from support_desk_agent.config.models import AppConfig


def build_ai_chat_util_config(config: AppConfig) -> AiChatUtilConfig:
    return AiChatUtilConfig.model_validate(
        {
            "llm": {
                "provider": config.llm.provider,
                "completion_model": config.llm.model,
                "api_key": config.llm.api_key,
                "base_url": config.llm.base_url,
            },
            "features": {
                "use_custom_pdf_analyzer": False,
            },
            "office2pdf": {
                "method": "libreoffice_exec",
                "libreoffice_exec": {
                    "libreoffice_path": config.tools.libreoffice_command,
                },
            },
            "logging": {
                "level": "INFO",
                "file": None,
            },
        }
    )


def create_ai_chat_util_client(config: AppConfig):
    return create_llm_client(build_ai_chat_util_config(config))


def chat_response_to_text(response: ChatResponse) -> str:
    return response.output.strip()


def _parse_datetime_value(value: str, time_format: str | None = None) -> datetime:
    text = value.strip()
    if time_format:
        return datetime.strptime(text, time_format)
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported datetime value: {value}. Provide ISO-8601 text or specify time_format."
        ) from exc


async def analyze_image_files(config: AppConfig, file_list: list[str], prompt: str, detail: str = "auto") -> str:
    client = create_ai_chat_util_client(config)
    response = await AnalyzeImageUtil.analyze_image_files(client, file_list, prompt, detail)
    return chat_response_to_text(response)


async def analyze_pdf_files(config: AppConfig, file_list: list[str], prompt: str, detail: str = "auto") -> str:
    client = create_ai_chat_util_client(config)
    response = await AnalyzePDFUtil.analyze_pdf_files(client, file_list, prompt, detail)
    return chat_response_to_text(response)


async def analyze_office_files(config: AppConfig, file_list: list[str], prompt: str, detail: str = "auto") -> str:
    client = create_ai_chat_util_client(config)
    response = await AnalyzeOfficeUtil.analyze_office_files(client, file_list, prompt, detail)
    return chat_response_to_text(response)


async def convert_office_files_to_pdf(
    config: AppConfig,
    office_path_list: list[str],
    output_dir: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    resolved_output_dir = None if output_dir is None else Path(output_dir).expanduser().resolve()
    if dry_run:
        return [
            {
                "source_path": office_path,
                "pdf_path": str(
                    (resolved_output_dir / Path(office_path).with_suffix(".pdf").name)
                    if resolved_output_dir is not None
                    else Path(office_path).expanduser().resolve().with_suffix(".pdf")
                ),
            }
            for office_path in office_path_list
        ]
    return AnalyzePDFUtil.convert_office_files_to_pdf(
        office_path_list,
        output_dir=None if resolved_output_dir is None else str(resolved_output_dir),
        libreoffice_path=config.tools.libreoffice_command,
    )


async def convert_pdf_files_to_images(
    config: AppConfig,
    pdf_path_list: list[str],
    output_dir: str | None = None,
    dry_run: bool = False,
    dpi: int = 144,
) -> list[dict[str, object]]:
    resolved_output_dir = None if output_dir is None else Path(output_dir).expanduser().resolve()
    if dry_run:
        results: list[dict[str, object]] = []
        for pdf_path in pdf_path_list:
            path = Path(pdf_path).expanduser().resolve()
            image_dir = (resolved_output_dir / f"{path.stem}_pages") if resolved_output_dir is not None else (path.parent / f"{path.stem}_pages")
            results.append({"source_path": str(path), "image_dir": str(image_dir), "image_paths": []})
        return results
    return AnalyzePDFUtil.convert_pdf_files_to_images(
        pdf_path_list,
        output_dir=None if resolved_output_dir is None else str(resolved_output_dir),
        dpi=dpi,
    )
async def infer_log_header_pattern(
    config: AppConfig,
    file_path: str,
    sample_line_limit: int = 100,
) -> InferLogFormatData:
    client = create_ai_chat_util_client(config)
    return await AnalyzeLogUtil.infer_log_header_pattern(
        client,
        file_path,
        sample_line_limit,
    )


async def extract_log_time_range(
    config: AppConfig,
    file_path: str,
    workspace_path: str,
    range_start: str,
    range_end: str,
    time_format: str | None = None,
    output_subdir: str = "log_extracts",
    output_filename: str | None = None,
    sample_line_limit: int = 100,
) -> ExtractLogTimeRangeData:
    client = create_ai_chat_util_client(config)
    output_dir = Path(workspace_path).expanduser().resolve() / output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    result = await AnalyzeLogUtil.extract_time_range_from_logfile(
        client,
        file_path=file_path,
        output_path=str(output_dir),
        start_time=_parse_datetime_value(range_start, time_format),
        end_time=_parse_datetime_value(range_end, time_format),
        sample_line_limit=sample_line_limit,
    )

    if output_filename:
        target_path = output_dir / output_filename
        Path(result.output_path).replace(target_path)
        result = result.model_copy(update={"output_path": str(target_path)})
    return result

