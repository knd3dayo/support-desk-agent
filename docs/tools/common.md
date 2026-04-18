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

## 4. 読み方

- 共通方針を確認したうえで、必要な tool 個別ページを参照する
- agent 文書は role 別ツール設計書ではなく、利用する tool ページへ直接リンクする
- role 別ツール文書は generated 下書きや旧構成との比較用途に限定する

## 5. 実装上の接続点

- ToolRegistry: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)
- builtin tools: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- shared memory payload: [src/support_ope_agents/tools/shared_memory_payload.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/shared_memory_payload.py)
- config override: [config.yml](/home/user/source/repos/support-ope-agents/config.yml)