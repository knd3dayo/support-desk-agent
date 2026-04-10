# ツール共通設計

## 1. 目的

本書は各 role 用ツール設計で共通となる前提を定義する。

## 2. 対象

- ToolRegistry 上の論理ツール名
- builtin 実装
- MCP override による差し替え点
- 共有メモリや workflow state との受け渡し方針

## 3. 基本方針

- agent からは論理ツール名のみを参照し、実装差し替えは ToolRegistry に閉じ込める
- 既定実装は builtin を優先し、外部接続が必要なものは後続で MCP または API adapter に置き換える
- 共有メモリの読み書きは write_shared_memory / read_shared_memory の論理ツール経由に統一する
- 実装未着手のツールでも、設計上の責務と I/O 契約は先に固定する

## 4. 共通ツール

### 4.1 shared memory 系

- read_shared_memory: shared/context.md、shared/progress.md、shared/summary.md をまとめて読む。既定実装は [src/support_ope_agents/tools/default_read_shared_memory.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_read_shared_memory.py) を利用する。
- write_shared_memory: shared/context.md、shared/progress.md、shared/summary.md へ書き込む。既定実装は [src/support_ope_agents/tools/default_write_shared_memory.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_write_shared_memory.py) を利用する。

### 4.2 working memory / draft 系

- write_working_memory: agent 個別の working.md へ作業ログを残すための論理ツール。現状は設計のみで、既定実装は未着手。
- write_draft: 顧客向け回答や問い合わせ文案を生成するための論理ツール。現状は設計のみで、既定実装は未着手。

## 5. 実装状況

- read_shared_memory: 実装済み
- write_shared_memory: 実装済み
- write_working_memory: 未実装
- write_draft: 未実装

## 6. 実装上の接続点

- ToolRegistry: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)
- builtin tools: [src/support_ope_agents/tools/builtin_tools.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/builtin_tools.py)
- shared memory payload: [src/support_ope_agents/tools/shared_memory_payload.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/shared_memory_payload.py)
- config override: [config.yml](/home/user/source/repos/support-ope-agents/config.yml)