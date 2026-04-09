# カスタマーサポート Deep Agents 実装設計書

## 1. 目的

本設計書は、カスタマーサポート業務シナリオを support-ope-agents 上で実装するための初期設計を定義する。
対象業務は、問い合わせ受付、ログ解析、ナレッジ探索、回答ドラフト生成、人間承認、チケット更新である。

本アプリの実装コンセプトは次の通りとする。

- 業務プロセスは LangGraph のワークフローで表現する
- スーパーバイザーおよびサブエージェントは各々 DeepAgent で実装する
- エージェント間の情報共有と進捗共有は共通メモリファイルで行う
- 各エージェントはコンテキスト管理機能を持ち、閾値超過時には圧縮処理を実施する
- 各エージェントは役割に応じたツールを持つ
- 業務プロセスはワークフローに従うが、細部は指示ファイルで追加指示を出せる
- 各エージェントのツールは後から追加可能な構成とする

## 2. 全体アーキテクチャ

### 2.1 責務分離

- LangGraph: ケース全体の状態遷移、分岐、HITL 停止点を管理する
- DeepAgent Supervisor: 担当フェーズの計画立案、サブエージェント起動、結果統合を行う
- DeepAgent Specialist: ログ解析、ナレッジ探索、ドラフト作成、コンプライアンスレビューなどの専門作業を行う
- 共通メモリ: ケース単位の shared memory と圧縮済み summary を保持する
- Tool Registry: エージェントごとのツールセットを構築する
- Instruction Loader: 共通指示、役割別指示、ケース固有上書きを合成する

### 2.2 ケース状態

ケース全体では次の状態遷移を管理する。

- RECEIVED
- TRIAGED
- INVESTIGATING
- DRAFT_READY
- WAITING_APPROVAL
- CLOSED

主要識別子は次の通りとする。

- case_id: 外部問い合わせの識別子
- trace_id: トレース基盤横断の相関 ID
- thread_id: LangGraph の再開対象スレッド ID
- workflow_run_id: 実行インスタンス ID

## 3. DeepAgent 構成

### 3.1 フェーズ別構成

#### IntakeWF

- LangGraph ノードとして実装する
- Intake Supervisor は DeepAgent とし、PII マスキング、カテゴリ判定、初期メモ作成を行う
- 必要に応じて分類系 Specialist を task ツールで起動できる

#### InvestigationWF

- Investigation Supervisor を DeepAgent として実装する
- Log Analyzer Specialist と Knowledge Retriever Specialist を並列起動する
- 両者は共有メモリを参照しつつ、自身のワーキングメモリに詳細ログを保持する

#### ResolutionWF

- Resolution Supervisor を DeepAgent として実装する
- Draft Writer Specialist と Compliance Reviewer Specialist を起動する
- Compliance Reviewer が差戻し判断した場合、Draft Writer を再起動する

#### ApprovalWF

- LangGraph ノードとして WAITING_APPROVAL で interrupt する
- 人間の承認、差戻し、追加調査要求に応じて resume する

#### TicketUpdateWF

- LangGraph ノードとして実装する
- 承認後に Zendesk / Redmine への更新を行う

### 3.2 DeepAgent 間の情報共有

共通メモリはケース単位ディレクトリに次のように保持する。

- shared/context.md: 現在の共通知識、調査方針、重要事実
- shared/progress.md: 進捗、未完了タスク、ブロッカー
- shared/summary.md: 圧縮済みサマリ
- agents/<agent_name>/working.md: 各エージェントの作業ログ
- instructions/<agent_name>.md: ケース固有の追加指示

共有対象は事実、進捗、次アクションに限定する。試行錯誤の生ログは agent 別 working.md に残し、必要に応じて summary.md に圧縮転記する。

## 4. コンテキスト管理

各 DeepAgent は次のルールでコンテキスト圧縮を行う。

- 読み込んだ shared/context.md と working.md の合計文字数を監視する
- 閾値超過時は、古い作業履歴を summary.md に圧縮する
- 圧縮後は working.md から詳細ログを削除せず、要約参照を追記する
- Supervisor は Specialist の最終成果のみ shared/context.md に反映する

この設計により、親エージェントへ不要な試行錯誤を持ち込まず、Deep Agents の context isolation を維持する。

## 5. 指示ファイル設計

指示ファイルは 3 層構成とする。

- 共通指示: instructions/common.md
- 役割別指示: instructions/<role>.md
- ケース固有上書き: runtime/cases/<case_id>/overrides/<role>.md

読み込み時は上から順に結合し、後勝ちで追加指示を適用する。

## 6. ツール設計

ツールは役割別に構成し、Registry から解決する。

- intake_supervisor: pii_mask, classify_ticket, write_shared_memory
- investigation_supervisor: read_shared_memory, spawn_log_analyzer, spawn_knowledge_retriever
- log_analyzer: read_log_file, run_python_analysis, write_working_memory
- knowledge_retriever: search_kb, search_ticket_history, write_working_memory
- resolution_supervisor: read_shared_memory, spawn_draft_writer, spawn_compliance_reviewer
- compliance_reviewer: check_policy, request_revision
- ticket_update: zendesk_reply, redmine_update

初期実装では外部システム接続をスタブ化し、後続で MCP ツールまたは API アダプタに置き換える。

## 7. 実装モジュール

初期実装では次のモジュールを用意する。

- src/support_ope_agents/config: YAML と環境変数の設定ロード
- src/support_ope_agents/memory: 共有メモリファイルの管理
- src/support_ope_agents/instructions: 指示ファイルの解決
- src/support_ope_agents/tools: 役割別ツール登録
- src/support_ope_agents/agents: DeepAgent 定義と生成
- src/support_ope_agents/workflow: LangGraph 状態とワークフロー構築
- src/support_ope_agents/cli.py: 起動用 CLI

## 8. 非同期 HITL

WAITING_APPROVAL では LangGraph interrupt を利用し、State を checkpointer に保存する。
resume 時は次の入力を受け付ける。

- approve: TicketUpdateWF へ進む
- reject: ResolutionWF へ戻す
- reinvestigate: InvestigationWF へ戻す

再開時の人間指示は、ケース固有 override ファイルに追記してからワークフローを再開する。

## 9. 設定方針

- 非秘匿設定は [config.yml](../config.yml) に置く
- API キーなどの秘匿情報は .env または実環境変数に置く
- YAML では os.environ/ENV_NAME 形式で参照する

## 10. 初期実装スコープ

今回の実装で含めるものは次の通り。

- Python プロジェクト骨格
- ケース共有メモリの初期化
- 指示ファイルのロード
- 役割別ツールセットの定義
- DeepAgent 生成用 Factory
- LangGraph ワークフロー定義
- CLI による構成表示とケース初期化

今回の実装では含めないものは次の通り。

- 実 LLM 呼び出し
- 実 Zendesk / Redmine / KB 接続
- 実 checkpointer 永続化
- Web API と画面

## 11. 今後の拡張

- DeepAgent の create_deep_agent 呼び出しを実 LLM に接続する
- LangGraph checkpointer を SQLite / Postgres に置く
- Tool Registry を MCP ベースに差し替える
- LangSmith / Langfuse のトレースを埋め込む
- ガバナンス層による PII / 出力ポリシー検査を追加する