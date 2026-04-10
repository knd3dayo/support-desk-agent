# internal_ticket

## 1. 目的

内部管理チケット情報を取得し、過去対応や保留論点を確認する。

## 2. 利用エージェント

- KnowledgeRetrieverAgent

## 3. 既定実装 / 接続点

- 論理ツール名: internal_ticket
- 既定では未接続で、MCP override または [config.yml](/home/user/source/repos/support-ope-agents/config.yml) の knowledge_retrieval.internal_ticket で構成する
- ToolRegistry 定義: [src/support_ope_agents/tools/registry.py](/home/user/source/repos/support-ope-agents/src/support_ope_agents/tools/registry.py)

## 4. 実装状況

- 既定実装なし