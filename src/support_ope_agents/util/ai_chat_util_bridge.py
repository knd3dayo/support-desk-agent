from __future__ import annotations

from pathlib import Path

from ai_chat_util.ai_chat_util_base.chat import create_llm_client
from ai_chat_util.ai_chat_util_base.chat.analysis_service import AnalysisService
from ai_chat_util.ai_chat_util_base.chat.llm_client_util import LLMClientUtil
from ai_chat_util.ai_chat_util_base.ai_chat_util_models import ChatResponse
from ai_chat_util.common.config.runtime import AiChatUtilConfig

from support_ope_agents.config.models import AppConfig


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
                "libreoffice_path": config.tools.libreoffice_command,
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


async def analyze_image_files(config: AppConfig, file_list: list[str], prompt: str, detail: str = "auto") -> str:
    client = create_ai_chat_util_client(config)
    response = await LLMClientUtil.analyze_image_files(client, file_list, prompt, detail)
    return chat_response_to_text(response)


async def analyze_pdf_files(config: AppConfig, file_list: list[str], prompt: str, detail: str = "auto") -> str:
    client = create_ai_chat_util_client(config)
    response = await LLMClientUtil.analyze_pdf_files(client, file_list, prompt, detail)
    return chat_response_to_text(response)


async def analyze_office_files(config: AppConfig, file_list: list[str], prompt: str, detail: str = "auto") -> str:
    client = create_ai_chat_util_client(config)
    response = await LLMClientUtil.analyze_office_files(client, file_list, prompt, detail)
    return chat_response_to_text(response)


async def convert_office_files_to_pdf(
    config: AppConfig,
    office_path_list: list[str],
    output_dir: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    resolved_output_dir = None if output_dir is None else Path(output_dir).expanduser().resolve()
    return AnalysisService.convert_office_files_to_pdf(
        office_path_list,
        output_dir=resolved_output_dir,
        dry_run=dry_run,
        libreoffice_path=config.tools.libreoffice_command,
        resolve_paths=False,
    )


async def convert_pdf_files_to_images(
    config: AppConfig,
    pdf_path_list: list[str],
    output_dir: str | None = None,
    dry_run: bool = False,
    dpi: int = 144,
) -> list[dict[str, object]]:
    resolved_output_dir = None if output_dir is None else Path(output_dir).expanduser().resolve()
    return AnalysisService.convert_pdf_files_to_images(
        pdf_path_list,
        output_dir=resolved_output_dir,
        dry_run=dry_run,
        dpi=dpi,
        resolve_paths=False,
    )


async def detect_log_format_and_search(
    _config: AppConfig,
    file_path: str,
    search_terms: list[str] | None = None,
    sample_line_limit: int = 100,
    match_limit: int = 50,
) -> str:
    return AnalysisService.detect_log_format_and_search_from_file(
        file_path,
        search_terms=search_terms,
        sample_line_limit=sample_line_limit,
        match_limit=match_limit,
        resolve_paths=False,
    )


async def infer_log_header_pattern(
    config: AppConfig,
    file_path: str,
    sample_line_limit: int = 100,
) -> str:
    client = create_ai_chat_util_client(config)
    return await AnalysisService.infer_log_header_pattern(
        client,
        file_path,
        sample_line_limit,
        resolve_paths=False,
    )


async def extract_log_time_range(
    config: AppConfig,
    file_path: str,
    workspace_path: str,
    header_pattern: str,
    timestamp_start: int,
    timestamp_end: int,
    range_start: str,
    range_end: str,
    time_format: str | None = None,
    output_subdir: str = "log_extracts",
    output_filename: str | None = None,
) -> str:
    return AnalysisService.extract_log_time_range_to_file(
        file_path=file_path,
        workspace_path=workspace_path,
        artifacts_subdir=config.data_paths.artifacts_subdir,
        header_pattern=header_pattern,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        range_start=range_start,
        range_end=range_end,
        time_format=time_format,
        output_subdir=output_subdir,
        output_filename=output_filename,
        resolve_paths=False,
    )