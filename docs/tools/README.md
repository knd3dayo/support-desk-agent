# ツール設計書

本ディレクトリは、各 agent が利用する論理ツールの設計を role 単位で分離して管理する。
agent 設計書ではツール詳細を直接持たず、本ディレクトリ配下の文書を参照する。

## 1. 参照順

- 共通事項: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- SuperVisorAgent 用ツール: [docs/tools/supervisor-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/supervisor-tools.md)
- IntakeAgent 用ツール: [docs/tools/intake-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/intake-tools.md)
- LogAnalyzerAgent 用ツール: [docs/tools/log-analyzer-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/log-analyzer-tools.md)
- KnowledgeRetrieverAgent 用ツール: [docs/tools/knowledge-retriever-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/knowledge-retriever-tools.md)
- DraftWriterAgent 用ツール: [docs/tools/draft-writer-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/draft-writer-tools.md)
- ComplianceReviewerAgent 用ツール: [docs/tools/compliance-reviewer-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/compliance-reviewer-tools.md)
- BackSupportEscalationAgent 用ツール: [docs/tools/back-support-escalation-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/back-support-escalation-tools.md)
- BackSupportInquiryWriterAgent 用ツール: [docs/tools/back-support-inquiry-writer-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/back-support-inquiry-writer-tools.md)
- ApprovalAgent 用ツール: [docs/tools/approval-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/approval-tools.md)
- TicketUpdateAgent 用ツール: [docs/tools/ticket-update-tools.md](/home/user/source/repos/support-ope-agents/docs/tools/ticket-update-tools.md)

## 2. 方針

- ここでいうツールは ToolRegistry 上の論理ツール名を指す
- 実装は builtin / MCP override / disabled に差し替え可能とする
- tool の責務、主要引数、期待出力、既定実装をここへ記載する
- 共通ツールは [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md) に集約し、role 固有文書では参照のみに留める
- 各 role 文書では 実装済み / 未実装 を明示する