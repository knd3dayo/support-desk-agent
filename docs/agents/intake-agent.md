# IntakeAgent 詳細設計

## 1. 役割

IntakeAgent は問い合わせ受付時および継続問い合わせ受付時の定型前処理を担当する疑似エージェントである。
LangGraph 上では true subgraph として実装し、後続の SuperVisorAgent が調査方針を判断できるように、入力問い合わせを正規化したうえで初期メモリと初期証跡を整える。
また、問い合わせ分類、緊急度、障害発生時間帯などの必須項目が揃っているかを品質ゲートとして判定し、不足があれば追加質問を生成して WAITING_CUSTOMER_INPUT へ停止させる。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: receive_case ノード
- 呼び出し先: intake_subgraph 完了後に investigation ノードへ結果を引き渡す
- 参照先: ケース workspace、共有メモリ、IntakeAgent 用ツール

## 3. 入力

IntakeAgent は CaseState を入力として受け取る。最低限必要な入力は次のとおり。

- case_id: 対象問い合わせを識別するケース ID。共有メモリや .traces の保存先を決める基準にも使う。
- trace_id: plan / action をまたいで実行を関連付ける相関 ID。トレースと継続実行の識別に使う。
- workflow_kind: 問い合わせをどのワークフロー種別で扱うかを示す値。後続の調査方針の前提になる。
- execution_mode: plan または action の実行モード。Intake の出力粒度や next_action の決定に使う。
- workspace_path: ケース workspace のパス。共有メモリや artifacts / evidence の参照先になる。
- raw_issue: ユーザーが入力した元の問い合わせ文。正規化、PII マスキング、分類の起点になる。
- external_ticket_id: 明示指定された外部チケット ID。対応する MCP ツールが有効な場合、初期 hydration の対象になる。
- internal_ticket_id: 明示指定された内部チケット ID。対応する MCP ツールが有効な場合、初期 hydration の対象になる。
- plan_summary: 現時点での計画サマリ。plan モード時に後続へ引き継ぐ観点の要約として参照する。
- plan_steps: 実行計画のステップ一覧。Intake 後に Supervisor が計画を補強する際の下敷きとして参照する。
- customer_followup_answers: 追加質問への回答群。WAITING_CUSTOMER_INPUT から再開したときの再 intake 判定に使う。

補助的に、ケース workspace 上の既存ファイル構造も入力文脈として扱う。

- .memory/shared/context.md
- .memory/shared/progress.md
- .memory/shared/summary.md
- .artifacts/
- .evidence/

## 4. 出力

IntakeAgent の出力は、CaseState 更新と共有メモリ初期化に分かれる。

CaseState へ反映する主な出力:

- status = TRIAGED
- current_agent = IntakeAgent
- masked_issue
- intake_category
- intake_urgency
- intake_investigation_focus
- intake_classification_reason
- intake_incident_timeframe
- intake_followup_questions
- customer_followup_answers
- intake_ticket_context_summary
- intake_ticket_artifacts
- next_action

共有メモリへ反映する主な出力:

- shared/context.md: 問い合わせ要約、分類結果、初期調査方針
- shared/progress.md: 現在フェーズ、未完了タスク、Supervisor への引き継ぎ事項
- workspace artifacts: 明示 ticket ID から取得した ticket 要約や添付ファイルの投影結果

後続の SuperVisorAgent へ引き継ぐ集約結果として、少なくとも次を確定させる。

- 問い合わせの正規化結果
- PII マスキング済みの問い合わせ本文
- カテゴリ判定結果
- 緊急度
- 初期調査観点
- 障害調査時の発生時間帯
- ticket 由来の補助情報と取得済み添付ファイルの所在

## 5. 使用ツール

IntakeAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/pii_mask.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/pii_mask.md)
- [docs/tools/specs/external_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/external_ticket.md)
- [docs/tools/specs/internal_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/internal_ticket.md)
- [docs/tools/specs/classify_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/classify_ticket.md)
- [docs/tools/specs/write_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_shared_memory.md)

ticket 取得系ツールの有効化と供給元は [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の tools.ticket_sources.external / internal で管理する。
ticket_sources を有効化した場合は manifest と server 定義を起動時に検証する。logical_tools は classify_ticket など任意差し替え対象だけを扱う。

## 6. 処理内容

IntakeAgent の処理は true subgraph 内で次の段階を基本とする。

1. 入力正規化
   raw_issue の余分なノイズを除去し、問い合わせの主題、事象、期待動作、制約条件を抽出しやすい形へ整える。
2. PII マスキング
   [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の agents.IntakeAgent.pii_mask.enabled が true の場合にのみ実行する。既定値は false とし、無効時は raw_issue をそのまま後続へ渡す。
3. ticket 初期 hydration
   明示指定された external_ticket_id または internal_ticket_id があり、対応する MCP ツールが有効な場合は ticket 情報と添付ファイルを取得し、workspace 配下へ保存する。取得結果は Supervisor と後続 agent が再利用できるよう path と要約を state に載せる。
4. 分類
   masked_issue を入力として、問い合わせカテゴリ、緊急度、初期調査の方向性を判定する。必要に応じて workflow_kind 判断の補助情報としても利用する。
5. 障害時刻抽出
   障害系と判断したケースでは、問い合わせ文から発生日時または時間帯を抽出し、後続の品質チェックに使えるようにする。
6. 品質ゲート
   IntakeAgent 自身が持つ validation API を使って問い合わせ分類、緊急度、incident_investigation 時の発生時間帯を検証する。必要項目が不足している場合は intake_missing_fields と intake_rework_reason を更新する。
7. 共有メモリ初期化と follow-up 整理
   write_shared_memory を使って shared/context.md と shared/progress.md に初期状態を書き込む。不足項目がある場合は follow-up 質問を生成し、WAITING_CUSTOMER_INPUT に遷移できる状態へ整える。
8. 継続問い合わせの再 intake 判定
   resume_customer_input や継続問い合わせ入力を受けた場合は、既存 state、customer_followup_answers、ticket hydration 済み情報を見て、追加質問の回収継続、品質ゲート再判定、または SuperVisorAgent への即時再連携を判断する。

subgraph 内の標準ノード構成は次の通りとする。

- intake_prepare
- intake_mask
- intake_hydrate_tickets
- intake_classify
- intake_quality_gate
- intake_finalize

validation API として、少なくとも次の static / class method を [src/support_desk_agent/agents/intake_agent.py](/home/user/source/repos/support-ope-agents/src/support_desk_agent/agents/intake_agent.py) に持つ。

- resolve_intake_category(state, memory_snapshot)
- resolve_intake_urgency(state, memory_snapshot)
- resolve_incident_timeframe(state, memory_snapshot)
- resolve_effective_workflow_kind(state, memory_snapshot)
- validate_intake(state, memory_snapshot)

validate_intake は category、urgency、incident_timeframe、missing_fields、rework_reason を返す ValidationResult を返し、IntakeAgent 自身の quality gate と SuperVisorAgent の workflow kind 解決の両方から共通利用する。

## 7. 共有メモリ更新

shared/context.md の初期記録例:

- Case ID
- Trace ID
- 正規化済み問い合わせ要約
- マスキング後問い合わせまたは原文
- 分類結果
- 初期調査方針
- ticket 情報の取得結果と添付ファイル保存先

shared/progress.md の初期記録例:

- 現在ステータス: TRIAGED
- 次フェーズ: INVESTIGATING
- Supervisor への引き継ぎ事項
- 未確認事項
- 不足時の追加質問
- 継続問い合わせ時の再 intake 判定結果

## 8. plan / action 差分

- plan モード: 調査計画の提示に必要な初期整理を優先し、next_action はユーザー承認待ちに向けた文言を設定する
- action モード: 以降の Investigation を開始できる状態にすることを優先し、共有メモリの初期化を必須とする
- ただし Intake の品質ゲートで必須項目不足を検出した場合は、plan / action に関係なく不足情報の確認質問を生成し、WAITING_CUSTOMER_INPUT で停止する
- WAITING_CUSTOMER_INPUT で停止した trace は、同じ trace_id を維持したまま追加回答を与えて再開できるようにする
- 再開時の追加回答は customer_followup_answers に構造化して保持し、再 intake 時の入力文脈にも反映する
- customer_followup_answers は missing field をキーとする辞書構造で保持し、複数回の差し戻しでもどの質問への回答かを安定して識別できるようにする
- 継続問い合わせの内容が追加質問への単純回答に留まらず調査状況を変える場合は、IntakeAgent が差分を要約して SuperVisorAgent へ再連携する

## 9. 実装方針

- agent 定義メタデータは [src/support_desk_agent/agents/intake_agent.py](/home/user/source/repos/support-ope-agents/src/support_desk_agent/agents/intake_agent.py) の build_intake_agent_definition に残す
- 複雑化する処理は専用の実行クラスへ切り出す
- intake subgraph の生成責務は [src/support_desk_agent/agents/intake_agent.py](/home/user/source/repos/support-ope-agents/src/support_desk_agent/agents/intake_agent.py) 側に置き、workflow 側は subgraph を呼び出すだけにする
- workflow が呼ぶ入口は IntakeAgent.create_node() と IntakeAgent.create_wait_node() とし、未注入は wiring ミスとして早期に検出する
- 実行クラスは pii_mask、external_ticket、internal_ticket、classify_ticket、write_shared_memory を必要に応じて呼び出したうえで、state 更新、workspace への ticket hydration、品質ゲート、共有メモリ初期化、plan / action 分岐を担う
- 品質ゲート判定ロジックは IntakeAgent の validation API として同居させ、Supervisor からはその API を参照する
- ticket 情報と添付ファイルの保存先は case workspace 配下の .artifacts/intake/ を標準とし、後続 agent はそこを参照する

## 10. 未決事項

- 分類結果のうち、CaseState に載せた項目以外で共有メモリのみに残す補足情報の境界
- 緊急度の表現形式と workflow routing への反映方法
- ticket 添付ファイルをどの形式まで自動展開するか