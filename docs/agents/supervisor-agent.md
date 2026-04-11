# SuperVisorAgent 詳細設計

## 1. 役割

SuperVisorAgent はケース全体の進行管理を担う親エージェントである。
IntakeAgent の出力を受けて調査方針を決定し、LogAnalyzerAgent と KnowledgeRetrieverAgent の結果を統合したうえで、DraftWriterAgent と ComplianceReviewerAgent による回答案作成とレビューを直接管理する。
また、調査結果だけでは確実な回答ができない場合は、BackSupportEscalationAgent と BackSupportInquiryWriterAgent を起動してエスカレーション材料と問い合わせ文案を作成する。
Intake 品質ゲートと追加質問生成は IntakeAgent 側の責務とし、SuperVisorAgent は gate 通過済みの入力を受けて investigation を開始する。
LangGraph 上では true subgraph として実装し、workflow 側は `supervisor_subgraph` を 1 ノードとして呼び出す。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: IntakeAgent 後の supervisor_subgraph、および承認差戻し後の supervisor_subgraph 再入場
- 呼び出し先: LogAnalyzerAgent、KnowledgeRetrieverAgent、DraftWriterAgent、ComplianceReviewerAgent、BackSupportEscalationAgent、BackSupportInquiryWriterAgent
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
- log_analysis_summary
- log_analysis_file
- escalation_required
- escalation_summary
- escalation_missing_artifacts
- escalation_draft

共有メモリへ反映する主な出力:

- shared/context.md: 確定事実、採用した根拠、顧客回答に反映すべき要点
- shared/progress.md: 調査状況、ドラフト差戻し状況、次アクション

## 5. 使用ツール

SuperVisorAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/read_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/read_shared_memory.md)
- [docs/tools/specs/write_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_shared_memory.md)
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

## 6. 処理内容

SuperVisorAgent の処理は supervisor_subgraph 内で大きく次の 4 段階に分かれる。

1. 調査フェーズ管理
   IntakeAgent の出力と read_shared_memory で取得した共有メモリ内容を参照し、workflow_kind を基準にしつつ、workflow_kind が ambiguous_case で intake_category がより具体的な場合はそちらを優先して、LogAnalyzerAgent と KnowledgeRetrieverAgent の起動組み合わせを決め、結果を収束させる。
   Intake 側で品質ゲートを通過している前提で、workflow_kind または intake_category の妥当性を解釈し、以降の調査方針と child agent 起動順を決める。
2. ドラフト作成フェーズ管理
   調査結果をもとに DraftWriterAgent を起動し、顧客向け回答ドラフトを生成する。
3. レビューループ管理
   read_shared_memory で取得した intake 分類結果や調査状況も参照しながら ComplianceReviewerAgent の指摘を評価し、差戻しが必要なら DraftWriterAgent を再実行し、承認フェーズへ進める水準まで整える。
4. エスカレーション管理
   通常の調査結果から確実な回答が得られない場合は、BackSupportEscalationAgent に必要資料と未解決事項を整理させ、BackSupportInquiryWriterAgent にバックサポート問い合わせ文案または追加ログ依頼文案を生成させる。

エスカレーション判定条件は初期実装では次を想定する。

- investigation_summary や共有メモリに、未解決、不明、確証不足、追加ログ必要などの不確実性シグナルがある
- incident_investigation なのに解析対象ログが不足している、またはログ解析結果から根拠が足りない
- 通常回答ドラフトを作るより先に、追加ログ取得やバックサポート確認を促す方が妥当と Supervisor が判断した

このとき Supervisor は escalation_required を true にし、escalation_reason、escalation_missing_artifacts、escalation_summary を埋めてからエスカレーション文案作成フェーズへ分岐する。

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
- intake の必須項目が欠ける場合は IntakeAgent 側の quality gate で停止済みであり、SuperVisorAgent へは到達しない前提とする
- 確実な回答が得られない場合は、通常回答ドラフトではなくエスカレーション文案生成フローへ切り替える

## 9. 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/supervisor_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/supervisor_agent.py) の build_supervisor_agent_definition に残す
- workflow 側の入口は [src/support_ope_agents/agents/supervisor_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/supervisor_agent.py) の create_node() とし、親 graph は `supervisor_subgraph` を呼び出すだけにする
- subgraph 内部ノードは investigation、draft_review、escalation_review を維持し、runtime audit / reporting / control catalog との互換を保つ
- reject 時は draft_review から、initial / reinvestigate 時は investigation から再入場できる entry routing を持たせる
- workflow_kind と intake_category は同じ語彙体系で扱い、Supervisor は workflow_kind を基準にしつつ ambiguous_case を intake_category で絞り込む
- 子エージェント起動の詳細は ToolRegistry と DeepAgentFactory の責務に委ねる
- shared/context.md への反映は Supervisor が最終判断した内容に限定する
- 実行クラスは read_shared_memory と write_shared_memory を用いて、investigation / draft_review フェーズの共有メモリ更新経路を統一し、共有メモリ内容を子エージェント起動計画やレビュー重点の判断材料として使う
- Intake 品質ゲートの判定ロジック自体は共通 validator を参照するが、その workflow 上の実行責務は IntakeAgent 側に置く
- BackSupportEscalationAgent / BackSupportInquiryWriterAgent は、通常回答ドラフト系とは別の補助分岐として扱う
- エスカレーション判定語彙と workflow_kind ごとの既定依頼資料は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.BackSupportEscalationAgent.escalation で調整可能とする
- Intake 出力評価のチェックリストは [src/support_ope_agents/instructions/defaults/SuperVisorAgent.md](/home/user/source/repos/support-ope-agents/src/support_ope_agents/instructions/defaults/SuperVisorAgent.md) の既定指示に置き、必要なら config_paths.instructions_path 配下の SuperVisorAgent.md で丸ごとオーバーライドする

## 10. 未決事項

- draft_review フェーズ内で何回まで再レビューを許可するか
- ComplianceReviewerAgent の差戻し結果を構造化して持つかどうか
- 承認前に Supervisor が自動で不足情報を再調査する条件
- どの条件で通常回答を諦めてエスカレーションへ切り替えるか