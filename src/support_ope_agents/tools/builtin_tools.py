from __future__ import annotations

from datetime import datetime
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, cast, get_args, get_origin, get_type_hints
from urllib.parse import urlparse

from ai_chat_util.ai_chat_util_base.file_util.core.app import (
    create_zip as create_zip_with_ai_chat_util,
    extract_base64_to_text as extract_base64_to_text_with_ai_chat_util,
    extract_text_from_file as extract_text_from_file_with_ai_chat_util,
    extract_zip as extract_zip_with_ai_chat_util,
    list_zip_contents as list_zip_contents_with_ai_chat_util,
)

from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.ai_chat_util_bridge import (
    analyze_image_files as analyze_image_files_with_ai_chat_util,
    analyze_office_files as analyze_office_files_with_ai_chat_util,
    analyze_pdf_files as analyze_pdf_files_with_ai_chat_util,
    convert_office_files_to_pdf as convert_office_files_to_pdf_with_ai_chat_util,
    convert_pdf_files_to_images as convert_pdf_files_to_images_with_ai_chat_util,
    detect_log_format_and_search as detect_log_format_and_search_with_ai_chat_util,
    extract_log_time_range as extract_log_time_range_with_ai_chat_util,
    infer_log_header_pattern as infer_log_header_pattern_with_ai_chat_util,
)


ToolCallable = Callable[..., Any]

@dataclass(frozen=True, slots=True)
class BuiltinTool:
    name: str
    description: str
    handler: ToolCallable
    input_schema: dict[str, Any]


def _annotation_description(annotation: Any) -> tuple[Any, str | None]:
    if get_origin(annotation) is not Annotated:
        return annotation, None

    metadata = get_args(annotation)
    if not metadata:
        return annotation, None

    base_annotation = metadata[0]
    description: str | None = None
    for item in metadata[1:]:
        if isinstance(item, str) and item.strip():
            description = item.strip()
            break
        field_description = getattr(item, "description", None)
        if isinstance(field_description, str) and field_description.strip():
            description = field_description.strip()
            break
    return base_annotation, description


def _json_schema_for_annotation(annotation: Any) -> dict[str, Any]:
    annotation, description = _annotation_description(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is Any:
        schema: dict[str, Any] = {}
    elif annotation in {str, Path}:
        schema = {"type": "string"}
    elif annotation is int:
        schema = {"type": "integer"}
    elif annotation is float:
        schema = {"type": "number"}
    elif annotation is bool:
        schema = {"type": "boolean"}
    elif annotation is datetime:
        schema = {"type": "string", "format": "date-time"}
    elif origin is Literal:
        literal_values = list(args)
        schema = {"enum": literal_values}
        if literal_values:
            first = literal_values[0]
            if isinstance(first, bool):
                schema["type"] = "boolean"
            elif isinstance(first, int) and not isinstance(first, bool):
                schema["type"] = "integer"
            elif isinstance(first, float):
                schema["type"] = "number"
            elif isinstance(first, str):
                schema["type"] = "string"
    elif origin is list:
        item_annotation = args[0] if args else Any
        schema = {"type": "array", "items": _json_schema_for_annotation(item_annotation)}
    elif origin in {dict}:
        schema = {"type": "object"}
    elif origin in {tuple}:
        item_annotation = args[0] if args else Any
        schema = {"type": "array", "items": _json_schema_for_annotation(item_annotation)}
    else:
        union_members = [member for member in args if member is not type(None)]
        has_null = len(union_members) != len(args)
        if args and union_members:
            variants = [_json_schema_for_annotation(member) for member in union_members]
            if has_null:
                variants.append({"type": "null"})
            schema = {"anyOf": variants}
        else:
            schema = {}

    if description:
        schema["description"] = description
    return schema


def _json_safe_default(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def _build_input_schema(handler: ToolCallable) -> dict[str, Any]:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return {}

    try:
        type_hints = get_type_hints(handler, include_extras=True)
    except Exception:
        type_hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        annotation = type_hints.get(parameter.name, Any)
        parameter_schema = _json_schema_for_annotation(annotation)
        if parameter.default is not inspect.Signature.empty:
            parameter_schema["default"] = _json_safe_default(parameter.default)
        else:
            required.append(parameter.name)
        properties[parameter.name] = parameter_schema

    doc = inspect.getdoc(handler) or ""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if doc.strip():
        schema["description"] = doc.strip().splitlines()[0].strip()
    return schema


def _builtin_tool(name: str, description: str, handler: ToolCallable) -> BuiltinTool:
    schema = _build_input_schema(handler)
    resolved_description = description.strip() or str(schema.get("description") or name)
    return BuiltinTool(name=name, description=resolved_description, handler=handler, input_schema=schema)


def _ensure_existing_paths(paths: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File was not found: {path}")
        resolved.append(path)
    return resolved

def _resolve_output_dir(output_dir: str | None) -> Path | None:
    if output_dir is None or not str(output_dir).strip():
        return None
    return Path(output_dir).expanduser().resolve()


def build_builtin_tools(config: AppConfig) -> dict[str, BuiltinTool]:
    async def analyze_image_files(
        file_list: list[str],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        paths = _ensure_existing_paths(file_list)
        return await analyze_image_files_with_ai_chat_util(config, [str(path) for path in paths], prompt, detail)

    async def analyze_pdf_files(
        pdf_path_list: list[str],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        paths = _ensure_existing_paths(pdf_path_list)
        return await analyze_pdf_files_with_ai_chat_util(config, [str(path) for path in paths], prompt, detail)

    async def analyze_office_files(
        office_path_list: list[str],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        paths = _ensure_existing_paths(office_path_list)
        return await analyze_office_files_with_ai_chat_util(config, [str(path) for path in paths], prompt, detail)


    async def extract_text_from_file(file_path: str) -> str:
        path = _ensure_existing_paths([file_path])[0]
        return await extract_text_from_file_with_ai_chat_util(str(path))

    async def extract_base64_to_text(extension: str, base64_data: str) -> str:
        return await extract_base64_to_text_with_ai_chat_util(extension, base64_data)

    async def list_zip_contents(file_path: str) -> list[str]:
        path = _ensure_existing_paths([file_path])[0]
        return await list_zip_contents_with_ai_chat_util(str(path))

    async def extract_zip(file_path: str, extract_to: str, password: str | None = None) -> bool:
        archive_path = _ensure_existing_paths([file_path])[0]
        target_dir = Path(extract_to).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        return await extract_zip_with_ai_chat_util(str(archive_path), str(target_dir), password)

    async def create_zip(file_paths: list[str], output_zip: str, password: str | None = None) -> bool:
        paths = _ensure_existing_paths(file_paths)
        output_path = Path(output_zip).expanduser().resolve()
        return await create_zip_with_ai_chat_util([str(path) for path in paths], str(output_path), password)

    async def convert_office_files_to_pdf(
        office_path_list: list[str],
        output_dir: str | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, str]]:
        paths = _ensure_existing_paths(office_path_list)
        resolved_output_dir = None if output_dir is None else str(_resolve_output_dir(output_dir))
        return await convert_office_files_to_pdf_with_ai_chat_util(
            config,
            [str(path) for path in paths],
            resolved_output_dir,
            dry_run,
        )

    async def convert_pdf_files_to_images(
        pdf_path_list: list[str],
        output_dir: str | None = None,
        dry_run: bool = False,
        dpi: int = 144,
    ) -> list[dict[str, Any]]:
        paths = _ensure_existing_paths(pdf_path_list)
        resolved_output_dir = None if output_dir is None else str(_resolve_output_dir(output_dir))
        return await convert_pdf_files_to_images_with_ai_chat_util(
            config,
            [str(path) for path in paths],
            resolved_output_dir,
            dry_run,
            dpi,
        )

    async def detect_log_format_and_search(
        file_path: Annotated[str, "解析対象のログファイルパス"],
        search_terms: Annotated[list[str] | None, "追加で検索するキーワード一覧"] = None,
        sample_line_limit: Annotated[int, "ログ先頭から形式判定に使う最大行数"] = 100,
        match_limit: Annotated[int, "パターンごとに返す最大ヒット件数"] = 50,
    ) -> str:
        path = _ensure_existing_paths([file_path])[0]
        return await detect_log_format_and_search_with_ai_chat_util(
            config,
            str(path),
            search_terms,
            sample_line_limit,
            match_limit,
        )

    async def infer_log_header_pattern(
        file_path: Annotated[str, "解析対象のログファイルパス"],
        sample_line_limit: Annotated[int, "ログ先頭から推定に使う最大行数"] = 100,
    ) -> str:
        path = _ensure_existing_paths([file_path])[0]
        return await infer_log_header_pattern_with_ai_chat_util(config, str(path), sample_line_limit)

    async def extract_log_time_range(
        file_path: Annotated[str, "抽出対象のログファイルパス"],
        workspace_path: Annotated[str, "派生ファイルを書き出す workspace ルート"],
        header_pattern: Annotated[str, "各ログレコード先頭行に一致する正規表現"],
        timestamp_start: Annotated[int, "先頭行内の時刻文字列の開始位置"],
        timestamp_end: Annotated[int, "先頭行内の時刻文字列の終了位置"],
        range_start: Annotated[str, "抽出開始時刻"],
        range_end: Annotated[str, "抽出終了時刻"],
        time_format: Annotated[str | None, "datetime.strptime 互換の時刻書式"] = None,
        output_subdir: Annotated[str, "抽出ログを書き出す artifacts 配下サブディレクトリ"] = "log_extracts",
        output_filename: Annotated[str | None, "抽出結果の出力ファイル名"] = None,
    ) -> str:
        source_path = _ensure_existing_paths([file_path])[0]
        return await extract_log_time_range_with_ai_chat_util(
            config,
            str(source_path),
            workspace_path,
            header_pattern,
            timestamp_start,
            timestamp_end,
            range_start,
            range_end,
            time_format,
            output_subdir,
            output_filename,
        )

    return {
        "analyze_image_files": _builtin_tool("analyze_image_files", "Analyze local image files", analyze_image_files),
        "analyze_pdf_files": _builtin_tool("analyze_pdf_files", "Analyze local PDF files", analyze_pdf_files),
        "analyze_office_files": _builtin_tool("analyze_office_files", "Analyze local Office files", analyze_office_files),
        "convert_office_files_to_pdf": _builtin_tool(
            "convert_office_files_to_pdf",
            "Convert Office files to PDF",
            convert_office_files_to_pdf,
        ),
        "convert_pdf_files_to_images": _builtin_tool(
            "convert_pdf_files_to_images",
            "Convert PDF files to page images",
            convert_pdf_files_to_images,
        ),
        "extract_text_from_file": _builtin_tool("extract_text_from_file", "Extract text from a local file", extract_text_from_file),
        "extract_base64_to_text": _builtin_tool(
            "extract_base64_to_text",
            "Extract text from base64-encoded file content",
            extract_base64_to_text,
        ),
        "list_zip_contents": _builtin_tool("list_zip_contents", "List ZIP archive contents", list_zip_contents),
        "extract_zip": _builtin_tool("extract_zip", "Extract ZIP archive", extract_zip),
        "create_zip": _builtin_tool("create_zip", "Create ZIP archive", create_zip),
        "detect_log_format_and_search": _builtin_tool(
            "detect_log_format_and_search",
            "Detect log format from the first lines, generate regex patterns, and search the log",
            detect_log_format_and_search,
        ),
        "infer_log_header_pattern": _builtin_tool(
            "infer_log_header_pattern",
            "Infer a log header regex and timestamp slice from the first lines of a log file",
            infer_log_header_pattern,
        ),
        "extract_log_time_range": _builtin_tool(
            "extract_log_time_range",
            "Extract records in a timestamp range from a log file and save them into the workspace artifacts",
            extract_log_time_range,
        ),
    }