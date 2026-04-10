# BackSupportEscalationAgent 詳細設計

## 1. 役割

BackSupportEscalationAgent は、通常の調査フローで確実な回答を得られなかった場合に、バックサポートへエスカレーションするための材料を整理する専門エージェントである。
調査結果、未確定事項、追加で必要なログや再現情報をまとめ、バックサポートがすぐに着手できる状態を作る。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: SuperVisorAgent の investigation または draft_review フェーズ
- 呼び出し先: BackSupportInquiryWriterAgent
- 接続先: エスカレーション材料を SuperVisorAgent へ返し、問い合わせ文案作成へつなぐ

## 3. 入力

- investigation_summary
- log_analysis_summary
- shared/context.md の確定事実
- shared/progress.md の未解決事項
- intake_category、intake_urgency

## 4. 出力

CaseState へ反映しうる主な出力:

- escalation_required
- escalation_summary
- escalation_missing_artifacts

共有メモリへ反映する主な出力:

- shared/context.md: バックサポートへ渡す確定事実、暫定仮説、未確定事項
- shared/progress.md: エスカレーション判断理由、必要追加ログ、必要再現手順

## 5. 使用ツール

BackSupportEscalationAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/read_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/read_shared_memory.md)
- [docs/tools/specs/write_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_shared_memory.md)
- [docs/tools/specs/scan_workspace_artifacts.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/scan_workspace_artifacts.md)

## 6. 処理内容

1. 調査結果整理
   LogAnalyzerAgent、KnowledgeRetrieverAgent、Supervisor の統合結果を見て、未解決の論点を整理する。
2. エスカレーション要否判定
   確実な回答ができるか、またはバックサポート判断が必要かを判定する。
3. 必要追加情報抽出
   バックサポートが調査に必要とするログ、設定、再現条件、取得依頼項目を列挙する。
4. エスカレーション材料生成
   バックサポート向けの要約と不足情報一覧を作り、BackSupportInquiryWriterAgent が文案化できる状態へ渡す。

## 7. 共有メモリ更新

- shared/context.md にはエスカレーション理由、渡すべき事実、未確定事項を残す
- shared/progress.md には追加で必要なログや確認依頼項目を残す

## 8. plan / action 差分

- plan モード: どの条件ならエスカレーションするか、必要資料は何かを返す
- action モード: 実際にエスカレーション材料を整理して文案作成へ渡す

## 9. 実装方針

- BackSupportEscalationAgent は通常回答フローとは別の分岐として SuperVisorAgent 配下に配置する
- ドラフト本文そのものは持たず、問い合わせ文案の材料整備に責務を限定する
- 実行クラスは [src/support_ope_agents/agents/back_support_escalation_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/back_support_escalation_agent.py) の BackSupportEscalationPhaseExecutor とし、共有メモリの読み書きで材料整理を行う

## 10. 未決事項

- エスカレーション基準を設定化するかどうか
- 必要追加ログのテンプレート化
- バックサポート向け内部文面と顧客向け依頼文面をどこまで分離するか