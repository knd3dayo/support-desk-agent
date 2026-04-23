# planned logical tools

ToolRegistry 上では定義済みだが、現時点では placeholder handler のみを返す論理ツールを、issue 化しやすい形で整理する。

## 1. 使い方

- 1 issue = 1 logical tool を基本とする
- 仕様の詳細は docs/tools/specs 配下の個別ページを参照する
- 実装着手時は [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py) の placeholder を builtin または orchestration 実装へ置き換える
- config 変更が必要なものは [src/support_ope_agents/config/tool_surface.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/config/tool_surface.py) も合わせて見直す

## 2. Issue テンプレート

- タイトル: Implement logical tool: <tool_name>
- 本文に含める項目: 目的、利用エージェント、入出力契約、既定実装方式、受け入れ条件、必要なテスト

## 3. Supervisor / orchestration

| logical tool | primary role | current state | spec | suggested issue title | minimum acceptance |
| --- | --- | --- | --- | --- | --- |
| inspect_workflow_state | SuperVisorAgent | planned placeholder | [docs/tools/specs/inspect_workflow_state.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/inspect_workflow_state.md) | Implement logical tool: inspect_workflow_state | workflow state を読み、次遷移可否を構造化して返す |
| evaluate_agent_result | SuperVisorAgent | planned placeholder | [docs/tools/specs/evaluate_agent_result.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/evaluate_agent_result.md) | Implement logical tool: evaluate_agent_result | 子エージェント結果を評価し、再実行要否を返す |
| route_phase_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/route_phase_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/route_phase_agent.md) | Implement logical tool: route_phase_agent | 状態に応じた次 phase / agent を決定できる |
| scan_workspace_artifacts | SuperVisorAgent, BackSupportEscalationAgent | planned placeholder | [docs/tools/specs/scan_workspace_artifacts.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/scan_workspace_artifacts.md) | Implement logical tool: scan_workspace_artifacts | workspace 成果物一覧と要約を返せる |
| spawn_log_analyzer_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/spawn_log_analyzer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_log_analyzer_agent.md) | Implement logical tool: spawn_log_analyzer_agent | LogAnalyzerAgent へ委譲し、結果を shared memory に反映できる |
| spawn_knowledge_retriever_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/spawn_knowledge_retriever_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_knowledge_retriever_agent.md) | Implement logical tool: spawn_knowledge_retriever_agent | KnowledgeRetrieverAgent へ委譲し、根拠候補を返せる |
| spawn_draft_writer_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/spawn_draft_writer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_draft_writer_agent.md) | Implement logical tool: spawn_draft_writer_agent | DraftWriterAgent へ委譲し、ドラフト成果物を返せる |
| spawn_investigate_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/spawn_investigate_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_investigate_agent.md) | Implement logical tool: spawn_investigate_agent | InvestigateAgent へ委譲し、調査要約とドラフトを返せる |
| spawn_back_support_escalation_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/spawn_back_support_escalation_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_back_support_escalation_agent.md) | Implement logical tool: spawn_back_support_escalation_agent | escalation 向け論点整理を返せる |
| spawn_back_support_inquiry_writer_agent | SuperVisorAgent | planned placeholder | [docs/tools/specs/spawn_back_support_inquiry_writer_agent.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/spawn_back_support_inquiry_writer_agent.md) | Implement logical tool: spawn_back_support_inquiry_writer_agent | バックサポート問い合わせドラフトを返せる |

## 4. Log analysis / approval / ticket update

| logical tool | primary role | current state | spec | suggested issue title | minimum acceptance |
| --- | --- | --- | --- | --- | --- |
| read_log_file | LogAnalyzerAgent | planned placeholder | [docs/tools/specs/read_log_file.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/read_log_file.md) | Implement logical tool: read_log_file | 対象ログの本文とメタデータを範囲指定で返せる |
| run_python_analysis | LogAnalyzerAgent | planned placeholder | [docs/tools/specs/run_python_analysis.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/run_python_analysis.md) | Implement logical tool: run_python_analysis | 制限付き Python 分析を実行し、結果を構造化して返せる |
| record_approval_decision | ApprovalAgent | planned placeholder | [docs/tools/specs/record_approval_decision.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/record_approval_decision.md) | Implement logical tool: record_approval_decision | 承認・差戻し結果を共有メモリまたは状態へ反映できる |
| zendesk_reply | TicketUpdateAgent | planned placeholder | [docs/tools/specs/zendesk_reply.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/zendesk_reply.md) | Implement logical tool: zendesk_reply | Zendesk 更新 API または MCP を呼び出し、結果を返せる |
| redmine_update | TicketUpdateAgent | planned placeholder | [docs/tools/specs/redmine_update.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/redmine_update.md) | Implement logical tool: redmine_update | Redmine 更新 API または MCP を呼び出し、結果を返せる |