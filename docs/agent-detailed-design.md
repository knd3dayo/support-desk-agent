# エージェント詳細設計書

## 1. 目的

本書は [docs/customer-support-deepagents-design.md](/home/user/source/repos/support-ope-agents/docs/customer-support-deepagents-design.md) を補完し、各エージェントの詳細設計を定義する。
全体アーキテクチャ、責務分離、ワークフロー上の位置付けは親設計書に従い、本書では各エージェントの入力、出力、処理内容、共有メモリ更新、実装方針を具体化する。

## 2. 文書の使い方

- 親設計書: 全体構成、フェーズ分割、共通方針を定義する
- 本書: 各エージェントの詳細仕様と実装指針を定義する
- 初版では IntakeAgent を対象とし、以後同じテンプレートで他エージェントを追記する

各エージェント章では次の観点をそろえる。

- 役割
- 呼び出し元 / 呼び出し先
- 入力
- 出力
- 使用ツール
- 共有メモリ更新
- plan / action 差分
- 実装方針
- 未決事項

## 3. SuperVisorAgent

### 3.1 役割

SuperVisorAgent はケース全体の進行管理を担う親エージェントである。
IntakeAgent の出力を受けて調査方針を決定し、LogAnalyzerAgent と KnowledgeRetrieverAgent の結果を統合したうえで、DraftWriterAgent と ComplianceReviewerAgent による回答案作成とレビューを直接管理する。

### 3.2 呼び出し元 / 呼び出し先

- 呼び出し元: IntakeAgent 後の investigation フェーズ、および draft_review フェーズ
- 呼び出し先: LogAnalyzerAgent、KnowledgeRetrieverAgent、DraftWriterAgent、ComplianceReviewerAgent
- 接続先: 承認前は wait_for_approval フェーズへ結果を引き渡す

### 3.3 入力

SuperVisorAgent が主要入力として扱うものは次のとおり。

- IntakeAgent が整えた CaseState
- shared/context.md に蓄積された確定事実
- shared/progress.md に蓄積された進捗と未解決事項
- 各子エージェントの返却結果
- execution_mode、workflow_kind、approval_decision

### 3.4 出力

SuperVisorAgent の出力は、調査フェーズの統合結果と、ドラフト作成フェーズの統制結果に分かれる。

CaseState へ反映する主な出力:

- current_agent = SuperVisorAgent
- investigation_summary
- draft_response
- next_action

共有メモリへ反映する主な出力:

- shared/context.md: 確定事実、採用した根拠、顧客回答に反映すべき要点
- shared/progress.md: 調査状況、ドラフト差戻し状況、次アクション

### 3.5 使用ツール

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

### 3.6 処理内容

SuperVisorAgent の処理は大きく次の 3 段階に分かれる。

1. 調査フェーズ管理
   IntakeAgent の出力を受け、必要な観点に応じて LogAnalyzerAgent と KnowledgeRetrieverAgent を起動し、結果を収束させる。
2. ドラフト作成フェーズ管理
   調査結果をもとに DraftWriterAgent を起動し、顧客向け回答ドラフトを生成する。
3. レビューループ管理
   ComplianceReviewerAgent の指摘を評価し、差戻しが必要なら DraftWriterAgent を再実行し、承認フェーズへ進める水準まで整える。

### 3.7 共有メモリ更新

shared/context.md には、子エージェントの生ログではなく、Supervisor が採用した事実と判断のみを反映する。

shared/progress.md には次を残す。

- 現在フェーズ
- 実行済み子エージェント
- 差戻しの有無
- 承認前に人間が確認すべき点

### 3.8 plan / action 差分

- plan モード: 調査観点、起動予定エージェント、ドラフト作成方針、レビュー観点を整理して返す
- action モード: 実際に子エージェントを順次起動し、結果を統合して承認待ちへ進める

### 3.9 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/supervisor_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/supervisor_agent.py) の build_supervisor_agent_definition に残す
- investigation と draft_review は workflow 上の別フェーズとして扱うが、どちらも責務主体は SuperVisorAgent とする
- 子エージェント起動の詳細は ToolRegistry と DeepAgentFactory の責務に委ねる
- shared/context.md への反映は Supervisor が最終判断した内容に限定する

### 3.10 未決事項

- draft_review フェーズ内で何回まで再レビューを許可するか
- ComplianceReviewerAgent の差戻し結果を構造化して持つかどうか
- 承認前に Supervisor が自動で不足情報を再調査する条件

## 4. IntakeAgent

### 4.1 役割

IntakeAgent は問い合わせ受付時の定型前処理を担当する疑似エージェントである。
LangGraph 上では subgraph または subgraph 相当の段階的処理として実装し、後続の SuperVisorAgent が調査方針を判断できるように、入力問い合わせを正規化したうえで初期メモリを整える。

### 4.2 呼び出し元 / 呼び出し先

- 呼び出し元: receive_case ノード
- 呼び出し先: investigation ノードの前段として SuperVisorAgent に結果を引き渡す
- 参照先: ケース workspace、共有メモリ、IntakeAgent 用ツール

### 4.3 入力

IntakeAgent は CaseState を入力として受け取る。最低限必要な入力は次のとおり。

- case_id
- trace_id
- workflow_kind
- execution_mode
- workspace_path
- raw_issue
- plan_summary
- plan_steps

補助的に、ケース workspace 上の既存ファイル構造も入力文脈として扱う。

- .memory/shared/context.md
- .memory/shared/progress.md
- .memory/shared/summary.md
- .artifacts/
- .evidence/

### 4.4 出力

IntakeAgent の出力は、CaseState 更新と共有メモリ初期化に分かれる。

CaseState へ反映する主な出力:

- status = TRIAGED
- current_agent = IntakeAgent
- masked_issue
- next_action

共有メモリへ反映する主な出力:

- shared/context.md: 問い合わせ要約、分類結果、初期調査方針
- shared/progress.md: 現在フェーズ、未完了タスク、Supervisor への引き継ぎ事項

後続の SuperVisorAgent へ引き継ぐ集約結果として、少なくとも次を確定させる。

- 問い合わせの正規化結果
- PII マスキング済みの問い合わせ本文
- カテゴリ判定結果
- 初期調査観点

### 4.5 使用ツール

IntakeAgent は論理ツールとして次を利用する。

- pii_mask
- classify_ticket
- write_shared_memory

これらは ToolRegistry 上の論理ツール名であり、実装は builtin / MCP override により差し替え可能とする。

### 4.6 処理内容

IntakeAgent の処理は次の 4 段階を基本とする。

1. 入力正規化
   raw_issue の余分なノイズを除去し、問い合わせの主題、事象、期待動作、制約条件を抽出しやすい形へ整える。
2. PII マスキング
   個人情報や秘匿性の高い情報が含まれる場合は masked_issue を生成し、以降の共有出力は原則としてマスキング済み内容を使う。
3. 分類
   問い合わせカテゴリ、緊急度、初期調査の方向性を判定する。必要に応じて workflow_kind 判断の補助情報としても利用する。
4. 共有メモリ初期化
   shared/context.md と shared/progress.md に初期状態を書き込み、後続フェーズが必要な情報を読み取れる状態にする。

### 4.7 共有メモリ更新

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

### 4.8 plan / action 差分

- plan モード: 調査計画の提示に必要な初期整理を優先し、next_action はユーザー承認待ちに向けた文言を設定する
- action モード: 以降の Investigation を開始できる状態にすることを優先し、共有メモリの初期化を必須とする

### 4.9 実装方針

- agent 定義メタデータは [src/support_ope_agents/agents/intake_agent.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/agents/intake_agent.py) の build_intake_agent_definition に残す
- 複雑化する処理は専用の実行クラスへ切り出す
- workflow 側の intake ノードは実行クラスへの委譲に留める
- 実行クラスは state 更新、共有メモリ初期化、plan / action 分岐を責務とする

### 4.10 未決事項

- 分類結果のうち、CaseState に載せる項目と共有メモリのみに書く項目の境界
- IntakeAgent を単一 execute で扱うか、subgraph builder として扱うか
- 緊急度の表現形式と workflow routing への反映方法

## 5. 他エージェントへの展開方針

Supervisor、LogAnalyzer、KnowledgeRetriever、DraftWriter、ComplianceReviewer についても、IntakeAgent と同じ章構成で追記する。
特に入力、出力、共有メモリ更新、plan / action 差分を固定項目としてそろえることで、責務の重複や境界の曖昧さを防ぐ。