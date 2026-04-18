from __future__ import annotations

import unittest

from xml.etree import ElementTree

from support_ope_agents.util.parsing import extract_xml_block, parse_mcp_tool_selection_xml, parse_xml_mapping


class StructuredOutputUtilTests(unittest.TestCase):
    def test_extract_xml_block_returns_matching_tag_content(self) -> None:
        raw_text = "prefix\n<decision><get_tool>get_issue</get_tool></decision>\nsuffix"

        result = extract_xml_block(raw_text, tag_name="decision")

        self.assertEqual(result, "<decision><get_tool>get_issue</get_tool></decision>")

    def test_extract_xml_block_returns_trimmed_input_when_tag_missing(self) -> None:
        raw_text = "  no xml here  "

        result = extract_xml_block(raw_text, tag_name="decision")

        self.assertEqual(result, "no xml here")

    def test_parse_xml_mapping_accepts_json_object_text(self) -> None:
        node = ElementTree.fromstring("<arguments>{\"issue_number\": \"123\"}</arguments>")

        result = parse_xml_mapping(node)

        self.assertEqual(result, {"issue_number": "123"})

    def test_parse_xml_mapping_accepts_arg_children(self) -> None:
        node = ElementTree.fromstring(
            "<arguments><arg name=\"issue_number\">123</arg><arg name=\"owner\">acme</arg></arguments>"
        )

        result = parse_xml_mapping(node)

        self.assertEqual(result, {"issue_number": "123", "owner": "acme"})

    def test_parse_xml_mapping_rejects_non_object_json(self) -> None:
        node = ElementTree.fromstring("<arguments>[1, 2, 3]</arguments>")

        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_xml_mapping(node)

    def test_parse_mcp_tool_selection_xml_supports_primary_tags(self) -> None:
        raw_text = (
            "<decision>"
            "<get_tool>get_issue</get_tool>"
            "<get_arguments>{\"issue_number\": \"123\"}</get_arguments>"
            "<list_tool>search_issues</list_tool>"
            "<list_arguments>{\"q\": \"login 500\"}</list_arguments>"
            "<get_attachment_tool>get_issue_attachments</get_attachment_tool>"
            "<get_attachment_arguments>{\"issue_number\": \"123\"}</get_attachment_arguments>"
            "<reason>primary tags</reason>"
            "</decision>"
        )

        result = parse_mcp_tool_selection_xml(raw_text)

        self.assertEqual(result.get_tool_name, "get_issue")
        self.assertEqual(result.get_arguments, {"issue_number": "123"})
        self.assertEqual(result.list_tool_name, "search_issues")
        self.assertEqual(result.attachment_tool_name, "get_issue_attachments")
        self.assertEqual(result.reason, "primary tags")

    def test_parse_mcp_tool_selection_xml_supports_alias_tags(self) -> None:
        raw_text = (
            "<decision>"
            "<call>get_issue</call>"
            "<arguments>{\"issue_number\": \"123\"}</arguments>"
            "<attachment_tool>get_issue_attachments</attachment_tool>"
            "<attachment_arguments><arg name=\"issue_number\">123</arg></attachment_arguments>"
            "</decision>"
        )

        result = parse_mcp_tool_selection_xml(raw_text)

        self.assertEqual(result.get_tool_name, "get_issue")
        self.assertEqual(result.get_arguments, {"issue_number": "123"})
        self.assertEqual(result.list_tool_name, "skip")
        self.assertEqual(result.attachment_tool_name, "get_issue_attachments")
        self.assertEqual(result.attachment_arguments, {"issue_number": "123"})

    def test_parse_mcp_tool_selection_xml_requires_get_tool(self) -> None:
        with self.assertRaisesRegex(ValueError, "get tool name"):
            parse_mcp_tool_selection_xml("<decision><list_tool>search_issues</list_tool></decision>")

    def test_parse_mcp_tool_selection_xml_supports_custom_decision_tag(self) -> None:
        raw_text = "<ticket_decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"123\"}</get_arguments></ticket_decision>"

        result = parse_mcp_tool_selection_xml(raw_text, decision_tag="ticket_decision")

        self.assertEqual(result.get_tool_name, "get_issue")
        self.assertEqual(result.get_arguments, {"issue_number": "123"})


if __name__ == "__main__":
    unittest.main()