from __future__ import annotations

from ai_chat_util.ai_chat_util_base.chat import create_llm_client
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