# カスタマーサポート Deep Agents 実装設計書

## 1. 目的

本設計書は、support-desk-agent における現行のカスタマーサポート業務シナリオ実装方針をまとめる。
対象業務は、問い合わせ受付、統合調査、回答ドラフト生成、人間承認、チケット更新である。

## 2. 主要エージェント

- 共通事項: [docs/agents/common.md](/home/user/source/repos/support-desk-agent/docs/agents/common.md)
- SuperVisorAgent: [docs/agents/supervisor-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/supervisor-agent.md)
- ObjectiveEvaluator: [docs/agents/objective-evaluator.md](/home/user/source/repos/support-desk-agent/docs/agents/objective-evaluator.md)
- IntakeAgent: [docs/agents/intake-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/intake-agent.md)
- InvestigateAgent: [docs/agents/investigate-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/investigate-agent.md)
- BackSupportEscalationAgent: [docs/agents/back-support-escalation-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/back-support-escalation-agent.md)
- BackSupportInquiryWriterAgent: [docs/agents/back-support-inquiry-writer-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/back-support-inquiry-writer-agent.md)
- ApprovalAgent: [docs/agents/approval-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/approval-agent.md)
- TicketUpdateAgent: [docs/agents/ticket-update-agent.md](/home/user/source/repos/support-desk-agent/docs/agents/ticket-update-agent.md)

## 3. 全体アーキテクチャ

- LangGraph がケース全体の状態遷移、停止点、分岐を管理する
- IntakeAgent が受付情報を正規化する
- SuperVisorAgent が investigation、approval、escalation の流れを制御する
- InvestigateAgent がログ解析、ナレッジ探索、ドラフト作成を一体で実行する
- BackSupport 系 Agent が通常回答で不足する場合の追加問い合わせを準備する
- ObjectiveEvaluator が trace、state、memory を突き合わせて改善レポートを生成する

## 4. ケース状態遷移

代表的な流れは次のとおり。

1. receive_case
2. intake_prepare / intake_mask / intake_hydrate_tickets / intake_classify / intake_finalize
3. investigation
4. draft_review
5. wait_for_approval
6. ticket_update または escalation_review

## 5. InvestigateAgent 集約方針

旧設計ではログ解析、ナレッジ探索、ドラフト作成、レビューを分割していたが、現行設計では user-facing な調査責務を InvestigateAgent に集約する。

- 仕様確認では document source を優先する
- 障害調査では workspace 内証跡とログ解析を優先する
- 必要に応じて external_ticket / internal_ticket を補助的に参照する
- 調査要約と draft を shared memory に毎回反映する

## 6. shared memory 方針

ケース単位で次の共有ファイルを使う。

- shared/context.md: 確定事実と根拠
- shared/progress.md: 進捗、未解決事項、次アクション
- shared/summary.md: 圧縮した要約

InvestigateAgent は毎回 shared memory を更新し、Supervisor はそれを再調査判断に使う。

## 7. tool 設計方針

- tool の詳細仕様は [docs/tools/README.md](/home/user/source/repos/support-desk-agent/docs/tools/README.md) を参照する
- 旧 split role 名ではなく、現行の user-facing role 名で説明する
- generated doc は ToolRegistry から再出力し、旧 role 名を残さない

## 8. 実装上の原則

- runtime 制約は最小限に保ち、主な振る舞い制御は instruction で与える
- config は `config.yml` を正本とする
- secret は `.env` または実環境変数で管理する
- DeepAgent の組み立ては RuntimeService と各 executor で完結させる
