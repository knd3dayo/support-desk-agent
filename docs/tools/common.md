# ツール共通設計

## 1. 目的

本書は tool 個別ページで共通となる前提を定義する。

## 2. 対象

- ToolRegistry 上の論理ツール名
- builtin 実装
- MCP override による差し替え点
- 共有メモリや workflow state との受け渡し方針

## 3. 基本方針

- agent からは論理ツール名のみを参照し、実装差し替えは ToolRegistry に閉じ込める
- tool の責務、利用 agent、既定実装、実装状況は tool 個別ページに分離する
- 既定実装は builtin を優先し、外部接続が必要なものは後続で MCP または API adapter に置き換える
- 共有メモリの読み書きは write_shared_memory / read_shared_memory の論理ツール経由に統一する
- shared memory や working memory のような workflow 内部ツールは MCP override 対象に含めない
- external_ticket / internal_ticket の接続先設定は logical_tools ではなく tools.ticket_sources に集約する
- 実装未着手のツールでも、設計上の責務と I/O 契約は先に固定する
- docs/tools/specs 配下のページは ToolRegistry 上の論理ツール名を表し、Python モジュールとの 1:1 対応は前提にしない

## 4. 実装区分

- implemented: 既定 builtin 実装が存在し、ToolRegistry から利用可能
- planned: 論理ツール名と仕様はあるが、現時点では ToolRegistry の placeholder handler のみ
- integration-required: builtin 既定実装は持たず、設定または外部接続を前提に利用する

## 5. builtin / MCP の使い分け基準

- builtin を優先する: case workspace 配下のローカルファイルや shared memory を直接扱う、workflow state や agent 制御に密結合している、1 ケース中に高頻度で細かく呼ばれる
- MCP を優先する: 外部システム接続が本質、組織や環境ごとの差し替え需要が高い、権限境界やネットワーク境界を分けたい
- どちらもあり得る: 現時点では builtin が妥当だが、将来的な共通サービス化や実行隔離の価値がある
- workflow 内部ツールは schema をそろえても transport 越しの利点が薄いため、特別な理由がない限り builtin のままにする
- 外部 ticket 取得や外部 ticket 更新は、builtin で暫定実装できても最終的には MCP または API adapter へ寄せる前提で設計する

## 6. 読み方

- 共通方針を確認したうえで、必要な tool 個別ページを参照する
- agent 文書は role 別ツール設計書ではなく、利用する tool ページへ直接リンクする
- role 別ツール文書は generated 下書きや旧構成との比較用途に限定する

## 7. 実装上の接続点

- ToolRegistry: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)
- builtin tools: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- shared memory payload: [src/support_ope_agents/util/shared_memory_payload.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/util/shared_memory_payload.py)
- config override: [config.yml](/home/user/source/repos/support-ope-agents/config.yml)

## 8. 未実装の論理ツール

以下は ToolRegistry 上の論理ツール名としては存在するが、現時点では builtin 実装ファイルを持たず、registry の not implemented handler で受けているもの。

- inspect_workflow_state
- evaluate_agent_result
- route_phase_agent
- scan_workspace_artifacts
- spawn_log_analyzer_agent
- spawn_knowledge_retriever_agent
- spawn_draft_writer_agent
- spawn_investigate_agent
- spawn_back_support_escalation_agent
- spawn_back_support_inquiry_writer_agent
- read_log_file
- run_python_analysis
- record_approval_decision
- zendesk_reply
- redmine_update