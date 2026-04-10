# ツール設計書

本ディレクトリは、各 agent が利用する論理ツールを tool 単位で管理する。
agent 設計書では role 別の中間ページを介さず、必要な tool 個別ページへ直接リンクする。

## 1. 参照順

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- tool 個別仕様: [docs/tools/specs](/home/user/source/repos/support-ope-agents/docs/tools/specs)

## 2. ツール一覧

### 2.1 共有メモリ / ドラフト

- [docs/tools/specs/read_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/read_shared_memory.md)
- [docs/tools/specs/write_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_shared_memory.md)
- [docs/tools/specs/write_working_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_working_memory.md)
- [docs/tools/specs/write_draft.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_draft.md)

### 2.2 証跡解析 / 前処理

- [docs/tools/specs/analyze_pdf_files.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/analyze_pdf_files.md)
- [docs/tools/specs/analyze_office_files.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/analyze_office_files.md)
- [docs/tools/specs/analyze_image_files.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/analyze_image_files.md)
- [docs/tools/specs/extract_text_from_file.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/extract_text_from_file.md)
- [docs/tools/specs/list_zip_contents.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/list_zip_contents.md)
- [docs/tools/specs/extract_zip.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/extract_zip.md)
- [docs/tools/specs/convert_pdf_files_to_images.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/convert_pdf_files_to_images.md)
- [docs/tools/specs/detect_log_format.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/detect_log_format.md)
- [docs/tools/specs/read_log_file.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/read_log_file.md)
- [docs/tools/specs/run_python_analysis.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/run_python_analysis.md)

### 2.3 Supervisor / orchestration

- [docs/tools/specs/inspect_workflow_state.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/inspect_workflow_state.md)
- [docs/tools/specs/evaluate_agent_result.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/evaluate_agent_result.md)
- [docs/tools/specs/route_phase_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/route_phase_agent.md)
- [docs/tools/specs/scan_workspace_artifacts.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/scan_workspace_artifacts.md)
- [docs/tools/specs/spawn_log_analyzer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_log_analyzer_agent.md)
- [docs/tools/specs/spawn_knowledge_retriever_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_knowledge_retriever_agent.md)
- [docs/tools/specs/spawn_draft_writer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_draft_writer_agent.md)
- [docs/tools/specs/spawn_compliance_reviewer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_compliance_reviewer_agent.md)
- [docs/tools/specs/spawn_back_support_escalation_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_back_support_escalation_agent.md)
- [docs/tools/specs/spawn_back_support_inquiry_writer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_back_support_inquiry_writer_agent.md)

### 2.4 Intake / knowledge / review / external update

- [docs/tools/specs/pii_mask.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/pii_mask.md)
- [docs/tools/specs/classify_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/classify_ticket.md)
- [docs/tools/specs/search_documents.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/search_documents.md)
- [docs/tools/specs/external_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/external_ticket.md)
- [docs/tools/specs/internal_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/internal_ticket.md)
- [docs/tools/specs/check_policy.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/check_policy.md)
- [docs/tools/specs/request_revision.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/request_revision.md)
- [docs/tools/specs/record_approval_decision.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/record_approval_decision.md)
- [docs/tools/specs/prepare_ticket_update.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/prepare_ticket_update.md)
- [docs/tools/specs/zendesk_reply.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/zendesk_reply.md)
- [docs/tools/specs/redmine_update.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/redmine_update.md)

## 3. 方針

- ここでいうツールは ToolRegistry 上の論理ツール名を指す
- 実装は builtin / MCP override / disabled に差し替え可能とする
- 各 tool ページでは責務、利用 agent、既定実装、実装状況を管理する
- agent 文書では「使う tool への直接リンク」のみを持ち、role 別の重複説明は持たない
- 既存の role 別ツール文書は互換のため残すが、新規記述の入口にはしない

## 4. 半自動更新

- ToolRegistry から role ごとの下書きを生成する場合は support-ope-agents export-tool-docs --config config.yml --output-dir docs/tools/generated を使う
- 生成結果は [docs/tools/generated](/home/user/source/repos/support-ope-agents/docs/tools/generated) 配下へ .generated.md として出力し、tool 個別ページ更新時のレビュー補助に使う