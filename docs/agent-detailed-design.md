# エージェント詳細設計書

本書は agent 詳細設計の索引であり、詳細本文は agent 単位の分割文書へ移した。

## 1. 参照順

- 共通事項: [docs/agents/common.md](/home/user/source/repos/support-desk-agent/docs/agents/common.md)
- SuperVisorAgent: [docs/agents/supervisor-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/supervisor-agent.md)
- ObjectiveEvaluator: [docs/agents/objective-evaluator.md](/home/user/source/repos/support-desk-agent/docs/agents/objective-evaluator.md)
- IntakeAgent: [docs/agents/intake-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/intake-agent.md)
- InvestigateAgent: [docs/agents/investigate-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/investigate-agent.md)
- BackSupportEscalationAgent: [docs/agents/back-support-escalation-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/back-support-escalation-agent.md)
- BackSupportInquiryWriterAgent: [docs/agents/back-support-inquiry-writer-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/back-support-inquiry-writer-agent.md)
- ApprovalAgent: [docs/agents/approval-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/approval-agent.md)
- TicketUpdateAgent: [docs/agents/ticket-update-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/ticket-update-agent.md)

## 2. 分割方針

- shared memory payload や記述ルールのような共通事項は [docs/agents/common.md](/home/user/source/repos/support-desk-agent/docs/agents/common.md) に置く
- agent 固有の責務、入出力、実装方針、未決事項は agent 単位の文書へ分離する
- 改善レポートの評価主体も agent として同じ粒度で文書化する
- 今後 agent を追加する場合も同じ粒度で docs/agents 配下へ分割する

## 3. 補足

- 親設計書は [docs/customer-support-deepagents-design.md](/home/user/source/repos/support-desk-agent/docs/customer-support-deepagents-design.md)
- tool 設計書 index は [docs/tools/README.md](/home/user/source/repos/support-desk-agent/docs/tools/README.md)
- このファイルは参照入口として残し、既存のリンク先パスを維持する