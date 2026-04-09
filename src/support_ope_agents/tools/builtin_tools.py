from __future__ import annotations

import base64
import json
import mimetypes
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import fitz
import pyzipper
import requests
from docx import Document as DocxDocument
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from openpyxl import load_workbook
from pdfminer.high_level import extract_text as extract_pdf_text
from PIL import Image
from pptx import Presentation

from support_ope_agents.config.models import AppConfig


ToolCallable = Callable[..., Any]


TEXT_FILE_SUFFIXES = {
    ".txt",
    ".log",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".sql",
}


@dataclass(frozen=True, slots=True)
class BuiltinTool:
    name: str
    description: str
    handler: ToolCallable


def _ensure_existing_paths(paths: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File was not found: {path}")
        resolved.append(path)
    return resolved


def _stringify_response_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def _get_chat_model(config: AppConfig) -> ChatOpenAI | None:
    if config.llm.provider.lower() != "openai":
        return None
    if not config.llm.api_key:
        return None
    return ChatOpenAI(model=config.llm.model, api_key=config.llm.api_key, temperature=0)


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 16] + "\n...[truncated]"


def _extract_docx_text(path: Path) -> str:
    document = DocxDocument(path)
    lines = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(lines)


def _extract_pptx_text(path: Path) -> str:
    presentation = Presentation(path)
    lines: list[str] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and text.strip():
                lines.append(f"[slide {slide_index}] {text.strip()}")
    return "\n".join(lines)


def _extract_xlsx_text(path: Path) -> str:
    workbook = load_workbook(path, read_only=True, data_only=True)
    lines: list[str] = []
    for sheet in workbook.worksheets:
        lines.append(f"[sheet] {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            values = [str(value).strip() for value in row if value is not None and str(value).strip()]
            if values:
                lines.append("\t".join(values))
    workbook.close()
    return "\n".join(lines)


def _extract_text_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_FILE_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        return extract_pdf_text(str(path))
    if suffix == ".docx":
        return _extract_docx_text(path)
    if suffix == ".pptx":
        return _extract_pptx_text(path)
    if suffix in {".xlsx", ".xlsm"}:
        return _extract_xlsx_text(path)
    raise ValueError(f"Text extraction is not supported for file type: {path.suffix or '<none>'}")


def _coerce_url(value: Any) -> tuple[str, dict[str, str] | None]:
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict):
        url = value.get("url") or value.get("uri") or value.get("href")
        headers = value.get("headers")
        if isinstance(url, str):
            normalized_headers = None
            if isinstance(headers, dict):
                normalized_headers = {str(key): str(item) for key, item in headers.items()}
            return url, normalized_headers
    raise ValueError(f"Unsupported URL entry: {value!r}")


def _suffix_from_url(url: str, response: requests.Response) -> str:
    candidate = Path(urlparse(url).path).suffix
    if candidate:
        return candidate
    content_type = response.headers.get("content-type")
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return guessed or ".bin"


def _download_urls(config: AppConfig, url_entries: list[Any]) -> tuple[tempfile.TemporaryDirectory[str], list[Path]]:
    tmpdir = tempfile.TemporaryDirectory()
    downloaded: list[Path] = []
    for index, entry in enumerate(url_entries, start=1):
        url, headers = _coerce_url(entry)
        response = requests.get(url, headers=headers, timeout=config.tools.download_timeout_seconds)
        response.raise_for_status()
        suffix = _suffix_from_url(url, response)
        target = Path(tmpdir.name) / f"download_{index:04d}{suffix}"
        target.write_bytes(response.content)
        downloaded.append(target)
    return tmpdir, downloaded


def _serialize_document_summaries(documents: list[dict[str, Any]], prompt: str, mode: str) -> str:
    return json.dumps(
        {
            "mode": mode,
            "prompt": prompt,
            "documents": documents,
        },
        ensure_ascii=False,
        indent=2,
    )


async def _analyze_text_documents(config: AppConfig, documents: list[dict[str, Any]], prompt: str) -> str:
    model = _get_chat_model(config)
    if model is None:
        return _serialize_document_summaries(documents, prompt, "metadata_only")

    payload_lines = ["You are analyzing customer support evidence.", f"Task: {prompt}", ""]
    for document in documents:
        payload_lines.append(f"Document: {document['name']}")
        payload_lines.append(document["content"])
        payload_lines.append("")
    response = await model.ainvoke([HumanMessage(content="\n".join(payload_lines))])
    return _stringify_response_content(response.content)


async def _analyze_images(config: AppConfig, paths: list[Path], prompt: str, detail: str) -> str:
    image_summaries: list[dict[str, Any]] = []
    for path in paths:
        with Image.open(path) as image:
            image_summaries.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": {"width": image.width, "height": image.height},
                    "format": image.format,
                    "mode": image.mode,
                }
            )

    model = _get_chat_model(config)
    if model is None:
        return json.dumps(
            {
                "mode": "metadata_only",
                "prompt": prompt,
                "detail": detail,
                "images": image_summaries,
            },
            ensure_ascii=False,
            indent=2,
        )

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": prompt,
        }
    ]
    for path in paths:
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append({"type": "text", "text": f"Image: {path.name}"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{encoded}",
                    "detail": detail,
                },
            }
        )
    response = await model.ainvoke([HumanMessage(content=content)])
    return _stringify_response_content(response.content)


def _resolve_output_dir(output_dir: str | None) -> Path | None:
    if output_dir is None or not str(output_dir).strip():
        return None
    return Path(output_dir).expanduser().resolve()


def _resolve_libreoffice_command(config: AppConfig) -> str:
    candidates = [config.tools.libreoffice_command, "soffice", "libreoffice"]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if resolved:
            return resolved
    raise RuntimeError(
        "LibreOffice command was not found. Set tools.libreoffice_command in config.yml or install soffice/libreoffice."
    )


def _collect_text_documents(config: AppConfig, paths: list[Path]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in paths:
        text = _truncate_text(_extract_text_from_path(path), config.tools.analysis_max_chars)
        documents.append(
            {
                "name": path.name,
                "path": str(path),
                "content": text,
                "content_length": len(text),
            }
        )
    return documents


def build_builtin_tools(config: AppConfig) -> dict[str, BuiltinTool]:
    async def analyze_image_files(
        file_list: list[str],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        paths = _ensure_existing_paths(file_list)
        return await _analyze_images(config, paths, prompt, detail)

    async def analyze_pdf_files(
        pdf_path_list: list[str],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        del detail
        paths = _ensure_existing_paths(pdf_path_list)
        return await _analyze_text_documents(config, _collect_text_documents(config, paths), prompt)

    async def analyze_office_files(
        office_path_list: list[str],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        del detail
        paths = _ensure_existing_paths(office_path_list)
        return await _analyze_text_documents(config, _collect_text_documents(config, paths), prompt)

    async def analyze_image_urls(
        image_path_urls: list[Any],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        tmpdir, paths = _download_urls(config, image_path_urls)
        try:
            return await _analyze_images(config, paths, prompt, detail)
        finally:
            tmpdir.cleanup()

    async def analyze_pdf_urls(
        pdf_path_urls: list[Any],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        del detail
        tmpdir, paths = _download_urls(config, pdf_path_urls)
        try:
            return await _analyze_text_documents(config, _collect_text_documents(config, paths), prompt)
        finally:
            tmpdir.cleanup()

    async def analyze_office_urls(
        office_path_urls: list[Any],
        prompt: str,
        detail: str = "auto",
    ) -> str:
        del detail
        tmpdir, paths = _download_urls(config, office_path_urls)
        try:
            return await _analyze_text_documents(config, _collect_text_documents(config, paths), prompt)
        finally:
            tmpdir.cleanup()

    async def extract_text_from_file(file_path: str) -> str:
        path = _ensure_existing_paths([file_path])[0]
        return _extract_text_from_path(path)

    async def extract_base64_to_text(extension: str, base64_data: str) -> str:
        suffix = extension if extension.startswith(".") else f".{extension}"
        raw = base64.b64decode(base64_data)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
        try:
            return _extract_text_from_path(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    async def list_zip_contents(file_path: str) -> list[str]:
        path = _ensure_existing_paths([file_path])[0]
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()

    async def extract_zip(file_path: str, extract_to: str, password: str | None = None) -> bool:
        archive_path = _ensure_existing_paths([file_path])[0]
        target_dir = Path(extract_to).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        if password:
            with pyzipper.AESZipFile(archive_path) as archive:
                archive.extractall(target_dir, pwd=password.encode("utf-8"))
            return True
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(target_dir)
        return True

    async def create_zip(file_paths: list[str], output_zip: str, password: str | None = None) -> bool:
        paths = _ensure_existing_paths(file_paths)
        output_path = Path(output_zip).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if password:
            with pyzipper.AESZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive:
                archive.setpassword(password.encode("utf-8"))
                for path in paths:
                    if path.is_dir():
                        for child in path.rglob("*"):
                            if child.is_file():
                                archive.write(child, arcname=str(child.relative_to(path.parent)))
                    else:
                        archive.write(path, arcname=path.name)
            return True

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                if path.is_dir():
                    for child in path.rglob("*"):
                        if child.is_file():
                            archive.write(child, arcname=str(child.relative_to(path.parent)))
                else:
                    archive.write(path, arcname=path.name)
        return True

    async def convert_office_files_to_pdf(
        office_path_list: list[str],
        output_dir: str | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, str]]:
        paths = _ensure_existing_paths(office_path_list)
        target_root = _resolve_output_dir(output_dir)
        planned: list[dict[str, str]] = []
        for path in paths:
            pdf_dir = target_root or path.parent
            pdf_path = pdf_dir / f"{path.stem}.pdf"
            planned.append({"source_path": str(path), "pdf_path": str(pdf_path)})
        if dry_run:
            return planned

        command = _resolve_libreoffice_command(config)
        for path in paths:
            pdf_dir = target_root or path.parent
            pdf_dir.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [command, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Failed to convert {path}")
        return planned

    async def convert_pdf_files_to_images(
        pdf_path_list: list[str],
        output_dir: str | None = None,
        dry_run: bool = False,
        dpi: int = 144,
    ) -> list[dict[str, Any]]:
        paths = _ensure_existing_paths(pdf_path_list)
        output_root = _resolve_output_dir(output_dir)
        results: list[dict[str, Any]] = []
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        for path in paths:
            image_dir = (output_root / f"{path.stem}_pages") if output_root is not None else (path.parent / f"{path.stem}_pages")
            with fitz.open(path) as document:
                image_paths = [str(image_dir / f"{path.stem}_page_{page.number + 1:04d}.png") for page in document]
                if not dry_run:
                    image_dir.mkdir(parents=True, exist_ok=True)
                    for page in document:
                        pixmap = page.get_pixmap(matrix=matrix)
                        pixmap.save(str(image_dir / f"{path.stem}_page_{page.number + 1:04d}.png"))
            results.append(
                {
                    "source_path": str(path),
                    "image_dir": str(image_dir),
                    "image_paths": image_paths,
                }
            )
        return results

    return {
        "analyze_image_files": BuiltinTool("analyze_image_files", "Analyze local image files", analyze_image_files),
        "analyze_pdf_files": BuiltinTool("analyze_pdf_files", "Analyze local PDF files", analyze_pdf_files),
        "analyze_office_files": BuiltinTool("analyze_office_files", "Analyze local Office files", analyze_office_files),
        "convert_office_files_to_pdf": BuiltinTool(
            "convert_office_files_to_pdf",
            "Convert Office files to PDF",
            convert_office_files_to_pdf,
        ),
        "convert_pdf_files_to_images": BuiltinTool(
            "convert_pdf_files_to_images",
            "Convert PDF files to page images",
            convert_pdf_files_to_images,
        ),
        "analyze_image_urls": BuiltinTool("analyze_image_urls", "Analyze image URLs", analyze_image_urls),
        "analyze_pdf_urls": BuiltinTool("analyze_pdf_urls", "Analyze PDF URLs", analyze_pdf_urls),
        "analyze_office_urls": BuiltinTool("analyze_office_urls", "Analyze Office URLs", analyze_office_urls),
        "extract_text_from_file": BuiltinTool("extract_text_from_file", "Extract text from a local file", extract_text_from_file),
        "extract_base64_to_text": BuiltinTool(
            "extract_base64_to_text",
            "Extract text from base64-encoded file content",
            extract_base64_to_text,
        ),
        "list_zip_contents": BuiltinTool("list_zip_contents", "List ZIP archive contents", list_zip_contents),
        "extract_zip": BuiltinTool("extract_zip", "Extract ZIP archive", extract_zip),
        "create_zip": BuiltinTool("create_zip", "Create ZIP archive", create_zip),
    }