# read_shared_memory

## 1. 目的

shared/context.md、shared/progress.md、shared/summary.md をまとめて読み、case workspace の共有状態を取得する。

## 2. 利用エージェント

- SuperVisorAgent
- BackSupportEscalationAgent

## 3. 既定実装 / 接続点

- 論理ツール名: read_shared_memory
- 既定実装: [src/support_ope_agents/tools/default_read_shared_memory.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/default_read_shared_memory.py)
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)

## 4. 実装状況

- 実装済み