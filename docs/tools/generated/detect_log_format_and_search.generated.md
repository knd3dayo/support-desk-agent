# detect_log_format_and_search ツール下書き

このファイルは ToolRegistry から半自動生成した下書きです。

## 概要
- description: Detect log format from the first lines, generate regex patterns, and search the log

## 利用エージェント
- SuperVisorAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- ObjectiveEvaluator: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- IntakeAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- InvestigateAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- BackSupportEscalationAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- BackSupportInquiryWriterAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- ApprovalAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed
- TicketUpdateAgent: provider=builtin, target=detect_log_format_and_search, status=implemented, override=allowed

## 手編集メモ
- ここに入出力例、運用上の注意、MCP 接続前提などを追記する。
- docs/tools/specs/*.md の更新時に差分確認用の下書きとして使う。
