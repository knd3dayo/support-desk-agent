from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree


@dataclass(frozen=True, slots=True)
class McpToolSelectionDecision:
    get_tool_name: str
    get_arguments: dict[str, Any]
    list_tool_name: str = "skip"
    list_arguments: dict[str, Any] | None = None
    attachment_tool_name: str = "skip"
    attachment_arguments: dict[str, Any] | None = None
    reason: str = ""


def extract_xml_block(raw_text: str, *, tag_name: str = "decision") -> str:
    pattern = rf"<{re.escape(tag_name)}(?:\s[^>]*)?>.*?</{re.escape(tag_name)}>"
    match = re.search(pattern, raw_text, flags=re.DOTALL)
    if match:
        return match.group(0)
    return raw_text.strip()


def parse_xml_mapping(node: ElementTree.Element | None) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if node is None:
        return arguments
    text = str(node.text or "").strip()
    if text:
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("XML tool decision arguments must be a JSON object")
        return {str(key): value for key, value in loaded.items()}
    for child in node.findall("arg"):
        name = str(child.attrib.get("name") or "").strip()
        if name:
            arguments[name] = str(child.text or "").strip()
    return arguments


def parse_mcp_tool_selection_xml(raw_text: str, *, decision_tag: str = "decision") -> McpToolSelectionDecision:
    xml_block = extract_xml_block(raw_text, tag_name=decision_tag)
    root = ElementTree.fromstring(xml_block)

    def _find_alias(*tag_names: str) -> ElementTree.Element | None:
        for tag_name in tag_names:
            node = root.find(tag_name)
            if node is not None:
                return node
        return None

    get_tool_node = _find_alias("get_tool", "call")
    get_arguments_node = _find_alias("get_arguments", "arguments")
    list_tool_node = _find_alias("list_tool")
    list_arguments_node = _find_alias("list_arguments")
    attachment_tool_node = _find_alias("get_attachment_tool", "attachment_tool")
    attachment_arguments_node = _find_alias("get_attachment_arguments", "attachment_arguments")
    reason_node = _find_alias("reason")

    get_tool_name = str(get_tool_node.text or "").strip() if get_tool_node is not None else ""
    if not get_tool_name:
        raise ValueError("XML tool decision did not contain a get tool name")

    return McpToolSelectionDecision(
        get_tool_name=get_tool_name,
        get_arguments=parse_xml_mapping(get_arguments_node),
        list_tool_name=str(list_tool_node.text or "skip").strip() if list_tool_node is not None else "skip",
        list_arguments=parse_xml_mapping(list_arguments_node),
        attachment_tool_name=(
            str(attachment_tool_node.text or "skip").strip() if attachment_tool_node is not None else "skip"
        ),
        attachment_arguments=parse_xml_mapping(attachment_arguments_node),
        reason=str(reason_node.text or "").strip() if reason_node is not None else "",
    )