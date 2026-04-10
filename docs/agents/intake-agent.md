# IntakeAgent 詳細設計

## 1. 役割

IntakeAgent は問い合わせ受付時の定型前処理を担当する疑似エージェントである。
LangGraph 上では subgraph または subgraph 相当の段階的処理として実装し、後続の SuperVisorAgent が調査方針を判断できるように、入力問い合わせを正規化したうえで初期メモリを整える。

## 2. 呼び出し元 / 呼び出し先

- 呼び出し元: receive_case ノード
- 呼び出し先: investigation ノードの前段として SuperVisorAgent に結果を引き渡す
- 参照先: ケース workspace、共有メモリ、IntakeAgent 用ツール

## 3. 入力

IntakeAgent は CaseState を入力として受け取る。最低限必要な入力は次のとおり。

- case_id: 対象問い合わせを識別するケース ID。共有メモリや traces の保存先を決める基準にも使う。
- trace_id: plan / action をまたいで実行を関連付ける相関 ID。トレースと継続実行の識別に使う。
- workflow_kind: 問い合わせをどのワークフロー種別で扱うかを示す値。後続の調査方針の前提になる。
- execution_mode: plan または action の実行モード。Intake の出力粒度や next_action の決定に使う。
- workspace_path: ケース workspace のパス。共有メモリや artifacts / evidence の参照先になる。
- raw_issue: ユーザーが入力した元の問い合わせ文。正規化、PII マスキング、分類の起点になる。
- plan_summary: 現時点での計画サマリ。plan モード時に後続へ引き継ぐ観点の要約として参照する。
- plan_steps: 実行計画のステップ一覧。Intake 後に Supervisor が計画を補強する際の下敷きとして参照する。

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
- next_action

共有メモリへ反映する主な出力:

- shared/context.md: 問い合わせ要約、分類結果、初期調査方針
- shared/progress.md: 現在フェーズ、未完了タスク、Supervisor への引き継ぎ事項

後続の SuperVisorAgent へ引き継ぐ集約結果として、少なくとも次を確定させる。

- 問い合わせの正規化結果
- PII マスキング済みの問い合わせ本文
- カテゴリ判定結果
- 緊急度
- 初期調査観点
- 障害調査時の発生時間帯

## 5. 使用ツール

IntakeAgent が参照する使用ツール詳細は次を参照する。

- 共通方針: [docs/tools/common.md](/home/user/source/repos/support-ope-agents/docs/tools/common.md)
- [docs/tools/specs/pii_mask.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/pii_mask.md)
- [docs/tools/specs/classify_ticket.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/classify_ticket.md)
- [docs/tools/specs/write_shared_memory.md](/home/user/source/repos/support-ope-agents/docs/tools/specs/write_shared_memory.md)

## 6. 処理内容

IntakeAgent の処理は次の 6 段階を基本とする。

1. 入力正規化
   raw_issue の余分なノイズを除去し、問い合わせの主題、事象、期待動作、制約条件を抽出しやすい形へ整える。
2. PII マスキング
   個人情報や秘匿性の高い情報が含まれる場合は masked_issue を生成し、以降の共有出力は原則としてマスキング済み内容を使う。
3. 分類
   masked_issue を入力として、問い合わせカテゴリ、緊急度、初期調査の方向性を判定する。必要に応じて workflow_kind 判断の補助情報としても利用する。
4. 障害時刻抽出
   障害系と判断したケースでは、問い合わせ文から発生日時または時間帯を抽出し、後続の品質チェックに使えるようにする。
5. 共有メモリ初期化
   write_shared_memory を使って shared/context.md と shared/progress.md に初期状態を書き込み、後続フェーズが必要な情報を読み取れる状態にする。
6. 差し戻し時の追加質問生成
   Supervisor から不足項目付きで差し戻された場合は、欠落項目に対応した follow-up 質問を生成し、WAITING_CUSTOMER_INPUT に遷移できる状態へ整える。

## 7. 共有メモリ更新

shared/context.md の初期記録例:

- Case ID
- Trace ID
- 正規化済み問い合わせ要約
- マスキング後問い合わせ
- 分類結果
- 初期調査方針

shared/progress.md の初期記録例:

- 現在ステータス: TRIAGED
- 次フェーズ: INVESTIGATING
- Supervisor への引き継ぎ事項
- 未確認事項
- 不足時の追加質問

## 8. plan / action 差分

- plan モード: 調査計画の提示に必要な初期整理を優先し、next_action はユーザー承認待ちに向けた文言を設定する
- action モード: 以降の Investigation を開始できる状態にすることを優先し、共有メモリの初期化を必須とする
- ただし Supervisor から差し戻しを受けた場合は、plan / action に関係なく不足情報の確認質問を生成し、WAITING_CUSTOMER_INPUT で停止する
- WAITING_CUSTOMER_INPUT で停止した trace は、同じ trace_id を維持したまま追加回答を与えて再開できるようにする
- 再開時の追加回答は customer_followup_answers に構造化して保持し、再 intake 時の入力文脈にも反映する
- customer_followup_answers は missing field をキーとする辞書構造で保持し、複数回の差し戻しでもどの質問への回答かを安定して識別できるようにする

## 9. 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/intake_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/intake_agent.py) の build_intake_agent_definition に残す
- 複雑化する処理は専用の実行クラスへ切り出す
- workflow 側の intake ノードは実行クラスへの委譲に留める
- 実行クラスは pii_mask、classify_ticket、write_shared_memory を呼び出したうえで、state 更新、共有メモリ初期化、plan / action 分岐を担う
- 実行クラスは Supervisor から渡された intake_missing_fields を見て follow-up 質問を生成できるようにする

## 10. 未決事項

- 分類結果のうち、CaseState に載せた項目以外で共有メモリのみに残す補足情報の境界
- IntakeAgent を単一 execute で扱うか、subgraph builder として扱うか
- 緊急度の表現形式と workflow routing への反映方法