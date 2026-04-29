# ObjectiveEvaluator 詳細設計

## 1. 役割

ObjectiveEvaluator は改善レポート専用の評価エージェントである。
SuperVisorAgent や各サブエージェントの判断をそのまま採用せず、workflow state、shared memory、各エージェントの working memory、成果物を照合して、ケース対応の品質を客観評価する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: generate-report、または action / resume 後の自動レポート生成
- 呼び出し先: なし
- 参照先: CaseState、shared memory、各エージェント working memory、workspace 成果物

## 3. 入力

- CaseState
- shared/context.md
- shared/progress.md
- shared/summary.md
- .memory/agents/<agent_name>/working.md
- .artifacts、.evidence 配下の成果物一覧

## 4. 出力

- support-improvement-<trace_id>.md
- エージェント呼び出しシーケンス
- サブグラフ詳細シーケンス
- エージェント別点数
- 情報伝達監査結果
- 総合評価と改善提案

## 5. 評価観点

- 各エージェントの出力が state に反映されているか
- 次工程に必要な情報が shared memory に伝播しているか
- 各エージェントの working memory にしか存在しない重要情報がないか
- エスカレーション判断や回答ドラフトが、調査根拠と整合しているか
- エージェント別に品質を 0 から 100 の点数で表現できるか

## 6. 実装方針

- agent 定義メタデータは [src/support_desk_agent/agents/objective_evaluator.py](/home/user/source/repos/support-ope-agents/src/support_desk_agent/agents/objective_evaluator.py) に置く
- 実際の評価ロジックは [src/support_desk_agent/runtime/reporting.py](/home/user/source/repos/support-ope-agents/src/support_desk_agent/runtime/reporting.py) に置き、サービス層から呼び出す
- 減点ルールや合格閾値は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.ObjectiveEvaluator 配下で調整可能とする
- instruction は [src/support_desk_agent/instructions/defaults/ObjectiveEvaluator.md](/home/user/source/repos/support-ope-agents/src/support_desk_agent/instructions/defaults/ObjectiveEvaluator.md) を既定とし、必要に応じて override 可能とする