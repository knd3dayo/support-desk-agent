# write_shared_memory ツール下書き

このファイルは ToolRegistry から半自動生成した下書きです。

## 概要
- description: Write shared context/progress/summary files for a case workspace

## 利用エージェント
- SuperVisorAgent: provider=builtin, target=default-case-memory-writer, status=implemented, override=allowed
- IntakeAgent: provider=builtin, target=default-case-memory-writer, status=implemented, override=allowed
- InvestigateAgent: provider=builtin, target=default-case-memory-writer, status=implemented, override=allowed
- BackSupportEscalationAgent: provider=builtin, target=default-case-memory-writer, status=implemented, override=allowed
- BackSupportInquiryWriterAgent: provider=builtin, target=default-case-memory-writer, status=implemented, override=allowed

## 手編集メモ
- ここに入出力例、運用上の注意、MCP 接続前提などを追記する。
- docs/tools/specs/*.md の更新時に差分確認用の下書きとして使う。
