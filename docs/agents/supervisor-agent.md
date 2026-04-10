# SuperVisorAgent 詳細設計

## 1. 役割

SuperVisorAgent はケース全体の進行管理を担う親エージェントである。
IntakeAgent の出力を受けて調査方針を決定し、LogAnalyzerAgent と KnowledgeRetrieverAgent の結果を統合したうえで、DraftWriterAgent と ComplianceReviewerAgent による回答案作成とレビューを直接管理する。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: IntakeAgent 後の investigation フェーズ、および draft_review フェーズ
- 呼び出し先: LogAnalyzerAgent、KnowledgeRetrieverAgent、DraftWriterAgent、ComplianceReviewerAgent
- 接続先: 承認前は wait_for_approval フェーズへ結果を引き渡す

## 3. 入力

SuperVisorAgent が主要入力として扱うものは次のとおり。

- IntakeAgent が整えた CaseState
- shared/context.md に蓄積された確定事実
- shared/progress.md に蓄積された進捗と未解決事項
- 各子エージェントの返却結果
- execution_mode、workflow_kind、approval_decision

## 4. 出力

SuperVisorAgent の出力は、調査フェーズの統合結果と、ドラフト作成フェーズの統制結果に分かれる。

CaseState へ反映する主な出力:

- current_agent = SuperVisorAgent
- investigation_summary
- draft_response
- next_action
- intake_rework_required
- intake_rework_reason
- intake_missing_fields
- log_analysis_summary
- log_analysis_file

共有メモリへ反映する主な出力:

- shared/context.md: 確定事実、採用した根拠、顧客回答に反映すべき要点
- shared/progress.md: 調査状況、ドラフト差戻し状況、次アクション

## 5. 使用ツール

SuperVisorAgent は論理ツールとして次を利用する。

- inspect_workflow_state
- evaluate_agent_result
- route_phase_agent
- read_shared_memory
- scan_workspace_artifacts
- spawn_log_analyzer_agent
- spawn_knowledge_retriever_agent
- spawn_draft_writer_agent
- spawn_compliance_reviewer_agent
- write_shared_memory

## 6. 処理内容

SuperVisorAgent の処理は大きく次の 3 段階に分かれる。

1. 調査フェーズ管理
   IntakeAgent の出力と read_shared_memory で取得した共有メモリ内容を参照し、workflow_kind を基準にしつつ、workflow_kind が ambiguous_case で intake_category がより具体的な場合はそちらを優先して、LogAnalyzerAgent と KnowledgeRetrieverAgent の起動組み合わせを決め、結果を収束させる。
   ただしその前に Intake 品質ゲートを実行し、分類、緊急度、障害時の発生時間帯など必須項目が不足していれば IntakeAgent へ差し戻す。
2. ドラフト作成フェーズ管理
   調査結果をもとに DraftWriterAgent を起動し、顧客向け回答ドラフトを生成する。
3. レビューループ管理
   read_shared_memory で取得した intake 分類結果や調査状況も参照しながら ComplianceReviewerAgent の指摘を評価し、差戻しが必要なら DraftWriterAgent を再実行し、承認フェーズへ進める水準まで整える。

investigation フェーズでは、LogAnalyzerPhaseExecutor を通して detect_log_format を呼び出し、検出形式、例外有無、主要一致件数を investigation summary と shared memory に反映する。

## 7. 共有メモリ更新

shared/context.md には、子エージェントの生ログではなく、Supervisor が採用した事実と判断のみを反映する。

shared/progress.md には次を残す。

- 現在フェーズ
- 実行済み子エージェント
- 差戻しの有無
- 承認前に人間が確認すべき点

## 8. plan / action 差分

- plan モード: 調査観点、起動予定エージェント、ドラフト作成方針、レビュー観点を整理して返す
- action モード: 実際に子エージェントを順次起動し、結果を統合して承認待ちへ進める
- intake の必須項目が欠ける場合は plan / action を問わず調査へ進まず、IntakeAgent が追加質問を生成して WAITING_CUSTOMER_INPUT で停止する

## 9. 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/supervisor_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/supervisor_agent.py) の build_supervisor_agent_definition に残す
- investigation と draft_review は workflow 上の別フェーズとして扱うが、どちらも責務主体は SuperVisorAgent とする
- workflow_kind と intake_category は同じ語彙体系で扱い、Supervisor は workflow_kind を基準にしつつ ambiguous_case を intake_category で絞り込む
- 子エージェント起動の詳細は ToolRegistry と DeepAgentFactory の責務に委ねる
- shared/context.md への反映は Supervisor が最終判断した内容に限定する
- 実行クラスは read_shared_memory と write_shared_memory を用いて、investigation / draft_review フェーズの共有メモリ更新経路を統一し、共有メモリ内容を子エージェント起動計画やレビュー重点の判断材料として使う

## 10. 未決事項

- draft_review フェーズ内で何回まで再レビューを許可するか
- ComplianceReviewerAgent の差戻し結果を構造化して持つかどうか
- 承認前に Supervisor が自動で不足情報を再調査する条件
- Intake 差し戻しを何回まで許可するか