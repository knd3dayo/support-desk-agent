# SuperVisorAgent 用ツール設計

## 1. 対象ツール

- inspect_workflow_state
- evaluate_agent_result
- route_phase_agent
- scan_workspace_artifacts
- spawn_log_analyzer_agent
- spawn_knowledge_retriever_agent
- spawn_draft_writer_agent
- spawn_compliance_reviewer_agent
- spawn_back_support_escalation_agent
- spawn_back_support_inquiry_writer_agent

## 2. 共通ツール参照

- shared memory 系: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)

## 3. role 固有ツール

- inspect_workflow_state: 現在の workflow state と次の遷移候補を点検する
- evaluate_agent_result: 子 agent の結果を評価し、採用可否や次アクションを判断する
- route_phase_agent: workflow_kind や調査状況に応じて次に使う担当を選定する
- scan_workspace_artifacts: workspace 配下の evidence / artifacts を走査して調査材料を把握する
- spawn_log_analyzer_agent: ログ解析担当へ委譲する
- spawn_knowledge_retriever_agent: KB / 過去事例探索担当へ委譲する
- spawn_draft_writer_agent: 顧客向けドラフト作成担当へ委譲する
- spawn_compliance_reviewer_agent: レビュー担当へ委譲する
- spawn_back_support_escalation_agent: エスカレーション材料整理担当へ委譲する
- spawn_back_support_inquiry_writer_agent: エスカレーション問い合わせ文案作成担当へ委譲する

## 4. 実装状況

- inspect_workflow_state: 未実装
- evaluate_agent_result: 未実装
- route_phase_agent: 未実装
- read_shared_memory: 共通ツールとして実装済み
- scan_workspace_artifacts: 未実装
- spawn_log_analyzer_agent: 未実装
- spawn_knowledge_retriever_agent: 未実装
- spawn_draft_writer_agent: 未実装
- spawn_compliance_reviewer_agent: 未実装
- spawn_back_support_escalation_agent: 未実装
- spawn_back_support_inquiry_writer_agent: 未実装
- write_shared_memory: 共通ツールとして実装済み